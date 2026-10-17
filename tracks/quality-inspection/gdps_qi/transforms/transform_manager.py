from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from gdps_qi.math_se3 import (
    compose_transform,
    invert_transform,
    transform_from_pose,
)
from gdps_qi.types import PoseRecord, Uncertainty


@dataclass
class TransformEdge:
    parent: str
    child: str
    t_parent_child: np.ndarray
    stamp: float
    calibration_id: str
    static: bool = False


class TransformError(Exception):
    pass


@dataclass
class TransformManager:
    max_age_s: float = 0.25
    _edges: Dict[Tuple[str, str], TransformEdge] = field(default_factory=dict)
    _history: Dict[Tuple[str, str], List[TransformEdge]] = field(default_factory=dict)
    version: str = "v0"

    def set_transform(
        self,
        parent: str,
        child: str,
        t_parent_child: np.ndarray,
        stamp: float,
        calibration_id: str,
        static: bool = False,
        allow_conflict: bool = False,
    ) -> None:
        key = (parent, child)
        if key in self._edges and not allow_conflict:
            prev = self._edges[key]
            if not np.allclose(prev.t_parent_child, t_parent_child, atol=1e-9):
                raise TransformError(f"conflicting edge {parent}->{child}")
        if self._introduces_cycle(parent, child, key):
            raise TransformError(f"cycle if adding {parent}->{child}")
        edge = TransformEdge(
            parent=parent,
            child=child,
            t_parent_child=t_parent_child.copy(),
            stamp=stamp,
            calibration_id=calibration_id,
            static=static,
        )
        self._edges[key] = edge
        hist = self._history.setdefault(key, [])
        hist.append(edge)
        self.version = f"v{int(stamp * 1000)}"

    def lookup(self, parent: str, child: str, stamp: Optional[float] = None) -> np.ndarray:
        if parent == child:
            return np.eye(4, dtype=float)
        query_stamp = stamp if stamp is not None else time.time()
        path = self._find_path(parent, child)
        if not path:
            raise TransformError(f"no path from {child} to {parent}")
        t = np.eye(4)
        for edge in path:
            edge_tf = self._edge_at_stamp(edge, query_stamp)
            if not edge.static and (query_stamp - edge_tf.stamp) > self.max_age_s:
                raise TransformError(f"stale transform {edge.parent}->{edge.child}")
            t = compose_transform(edge_tf.t_parent_child, t)
        return t

    def lookup_inverse(self, child: str, parent: str, stamp: Optional[float] = None) -> np.ndarray:
        t_parent_child = self.lookup(parent, child, stamp)
        return invert_transform(t_parent_child)

    def can_transform(self, parent: str, child: str) -> bool:
        try:
            self.lookup(parent, child)
            return True
        except TransformError:
            return False

    def _edge_at_stamp(self, edge: TransformEdge, query_stamp: float) -> TransformEdge:
        if edge.static:
            return edge
        key = (edge.parent, edge.child)
        hist = self._history.get(key, [edge])
        best = edge
        best_dt = abs(query_stamp - edge.stamp)
        for candidate in hist:
            dt = abs(query_stamp - candidate.stamp)
            if dt < best_dt:
                best_dt = dt
                best = candidate
        return best

    def _introduces_cycle(self, parent: str, child: str, new_key: Tuple[str, str]) -> bool:
        if parent == child:
            return True
        if new_key in self._edges:
            return False
        return self._find_path(parent, child) is not None

    def lookup_pose(
        self, target_frame: str, source_frame: str, stamp: Optional[float] = None
    ) -> PoseRecord:
        t = self.lookup(target_frame, source_frame, stamp)
        r = t[:3, :3]
        p = t[:3, 3]
        from gdps_qi.math_se3 import rot_to_quat

        q = rot_to_quat(r)
        return PoseRecord(
            frame_id=target_frame,
            stamp=stamp or time.time(),
            position=(float(p[0]), float(p[1]), float(p[2])),
            orientation_xyzw=(float(q[0]), float(q[1]), float(q[2]), float(q[3])),
            calibration_id=self.version,
            uncertainty=Uncertainty(0.001, 0.01, source="tf_lookup"),
            confidence=1.0,
            source="transform_manager",
        )

    def _find_path(self, parent: str, child: str) -> Optional[list]:
        if parent == child:
            return []
        from collections import deque

        q = deque([(child, [])])
        visited = {child}
        while q:
            frame, edges_acc = q.popleft()
            if frame == parent:
                return edges_acc
            for (p, c), edge in self._edges.items():
                if c != frame or p in visited:
                    continue
                visited.add(p)
                q.append((p, edges_acc + [edge]))
        return None

    def set_from_pose_record(self, parent: str, child: str, pose: PoseRecord, static: bool = False) -> None:
        t = transform_from_pose(pose.position, pose.orientation_xyzw)
        self.set_transform(parent, child, t, pose.stamp, pose.calibration_id, static=static)
