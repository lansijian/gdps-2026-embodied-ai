from __future__ import annotations

from typing import Optional

import numpy as np

from gdps_qi.transforms.frame_registry import FrameGraphReport, LogicalFrame, TransformChainStatus
from gdps_qi.transforms.transform_manager import TransformError, TransformManager


def _mat4_to_nested(t: np.ndarray) -> list:
    return t.reshape(4, 4).tolist()


def _resolve_frame(tf: TransformManager, base: str, logical: LogicalFrame, aliases: tuple[str, ...]) -> Optional[str]:
    for name in aliases:
        if tf.can_transform(base, name):
            return name
    return None


def build_frame_graph_report(
    tf: TransformManager,
    base_frame: str = LogicalFrame.ROBOT_CENTER.value,
    odom_frame: str = LogicalFrame.ODOM.value,
    stamp: Optional[float] = None,
) -> FrameGraphReport:
    rep = FrameGraphReport(base_frame=base_frame)
    required_edges = [
        (base_frame, LogicalFrame.PELVIS.value),
        (LogicalFrame.PELVIS.value, LogicalFrame.TORSO.value),
        (LogicalFrame.TORSO.value, LogicalFrame.HEAD_CAMERA_LINK.value),
        (LogicalFrame.HEAD_CAMERA_LINK.value, LogicalFrame.CAMERA_COLOR_OPTICAL.value),
    ]
    for parent, child in required_edges:
        ok = tf.can_transform(parent, child)
        reason = "" if ok else "missing_or_stale"
        rep.statuses.append(
            TransformChainStatus(
                edge=f"{parent}->{child}",
                parent=parent,
                child=child,
                available=ok,
                stamp=stamp,
                calibration_id=tf.version if ok else "",
                reason=reason,
            )
        )
        if not ok:
            rep.errors.append(f"missing_edge:{parent}->{child}")

    cam_name = _resolve_frame(
        tf,
        base_frame,
        LogicalFrame.CAMERA_COLOR_OPTICAL,
        (LogicalFrame.CAMERA_COLOR_OPTICAL.value, "head_camera_optical"),
    )
    lidar_name = _resolve_frame(tf, base_frame, LogicalFrame.LIVOX, ("livox_frame",))
    try:
        if cam_name:
            rep.T_base_camera = _mat4_to_nested(tf.lookup(base_frame, cam_name, stamp))
    except TransformError as exc:
        rep.errors.append(f"T_base_camera:{exc}")
    try:
        if lidar_name:
            rep.T_base_lidar = _mat4_to_nested(tf.lookup(base_frame, lidar_name, stamp))
    except TransformError as exc:
        rep.errors.append(f"T_base_lidar:{exc}")
    try:
        if tf.can_transform(base_frame, LogicalFrame.TARGET.value):
            rep.T_base_target = _mat4_to_nested(tf.lookup(base_frame, LogicalFrame.TARGET.value, stamp))
    except TransformError as exc:
        rep.errors.append(f"T_base_target:{exc}")
    try:
        if tf.can_transform(odom_frame, base_frame):
            rep.T_odom_base = _mat4_to_nested(tf.lookup(odom_frame, base_frame, stamp))
    except TransformError as exc:
        rep.errors.append(f"T_odom_base:{exc}")
    return rep
