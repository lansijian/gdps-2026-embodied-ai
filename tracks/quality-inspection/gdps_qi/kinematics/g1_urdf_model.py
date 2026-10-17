from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from gdps_qi.hardware.g1_joint_map import (
    G1_LEFT_ARM_JOINTS,
    G1_RIGHT_ARM_JOINTS,
    G1_WAIST_JOINTS,
    URDF_FRAME_LEFT_WRIST,
    URDF_FRAME_RIGHT_WRIST,
)
from gdps_qi.kinematics.arm_kinematics import IkResult
from gdps_qi.math_se3 import rot_to_quat


@dataclass
class G1UrdfModel:
    urdf_path: str
    base_frame: str = "pelvis"
    _pin: object = None
    _data: object = None
    _frame_ids: Dict[str, int] = field(default_factory=dict)
    _joint_name_to_q: Dict[str, int] = field(default_factory=dict)
    load_error: str = ""

    def load(self) -> bool:
        try:
            import pinocchio as pin  # type: ignore
        except ImportError:
            self.load_error = "pinocchio_not_installed"
            return False
        try:
            self._pin = pin.buildModelFromUrdf(self.urdf_path)
            self._data = self._pin.createData()
            for jname in self._pin.names[1:]:
                jid = self._pin.getJointId(jname)
                if jid > 0:
                    self._joint_name_to_q[jname] = self._pin.joints[jid].idx_q
            for fname in (
                self.base_frame,
                URDF_FRAME_LEFT_WRIST,
                URDF_FRAME_RIGHT_WRIST,
                "torso_link",
                "head_camera_link",
            ):
                try:
                    self._frame_ids[fname] = self._pin.getFrameId(fname)
                except Exception:
                    pass
            return True
        except Exception as exc:
            self.load_error = str(exc)
            return False

    def neutral_q(self) -> np.ndarray:
        if self._pin is None:
            raise RuntimeError("model not loaded")
        return np.zeros(self._pin.nq)

    def set_named_joints(self, joint_positions: Dict[str, float]) -> np.ndarray:
        import pinocchio as pin  # type: ignore

        q = self.neutral_q()
        for name, val in joint_positions.items():
            idx = self._joint_name_to_q.get(name)
            if idx is not None:
                q[idx] = val
        pin.forwardKinematics(self._pin, self._data, q)
        pin.updateFramePlacements(self._pin, self._data)
        return q

    def frame_placement(self, frame_name: str, q: Optional[np.ndarray] = None) -> np.ndarray:
        import pinocchio as pin  # type: ignore

        if self._pin is None or self._data is None:
            raise RuntimeError("model not loaded")
        if q is not None:
            pin.forwardKinematics(self._pin, self._data, q)
            pin.updateFramePlacements(self._pin, self._data)
        fid = self._frame_ids.get(frame_name)
        if fid is None:
            fid = self._pin.getFrameId(frame_name)
            self._frame_ids[frame_name] = fid
        se3 = self._data.oMf[fid]
        t = np.eye(4)
        t[:3, :3] = np.array(se3.rotation)
        t[:3, 3] = np.array(se3.translation).reshape(3)
        return t

    def fk_arm_wrist(self, side: str, joint_positions: Dict[str, float]) -> np.ndarray:
        names = G1_LEFT_ARM_JOINTS if side == "left" else G1_RIGHT_ARM_JOINTS
        subset = {n: joint_positions.get(n, 0.0) for n in names}
        for w in G1_WAIST_JOINTS:
            if w in joint_positions:
                subset[w] = joint_positions[w]
        q = self.set_named_joints(subset)
        frame = URDF_FRAME_LEFT_WRIST if side == "left" else URDF_FRAME_RIGHT_WRIST
        return self.frame_placement(frame, q)

    def ik_frame_dls(
        self,
        frame_name: str,
        target_t: np.ndarray,
        seed_q: np.ndarray,
        arm_joint_names: Sequence[str],
        max_iter: int = 80,
    ) -> IkResult:
        import pinocchio as pin  # type: ignore

        if self._pin is None or self._data is None:
            return IkResult(False, tuple(seed_q.tolist()), 1.0, 1.0, 0, "model_not_loaded")
        q = seed_q.copy()
        fid = self._frame_ids.get(frame_name) or self._pin.getFrameId(frame_name)
        idxs = []
        for jn in arm_joint_names:
            idx = self._joint_name_to_q.get(jn)
            if idx is not None:
                idxs.append(idx)
        if not idxs:
            return IkResult(False, tuple(q.tolist()), 1.0, 1.0, 0, "no_joint_indices")
        for it in range(max_iter):
            pin.forwardKinematics(self._pin, self._data, q)
            pin.updateFramePlacements(self._pin, self._data)
            cur = self._data.oMf[fid]
            cur_t = np.eye(4)
            cur_t[:3, :3] = np.array(cur.rotation)
            cur_t[:3, 3] = np.array(cur.translation).reshape(3)
            pos_err = target_t[:3, 3] - cur_t[:3, 3]
            r_err = target_t[:3, :3] @ cur_t[:3, :3].T
            angle = math.acos(max(-1.0, min(1.0, (np.trace(r_err) - 1.0) / 2.0)))
            pos_norm = float(np.linalg.norm(pos_err))
            if pos_norm < 0.003 and angle < 0.05:
                return IkResult(True, tuple(q.tolist()), pos_norm, angle, it + 1, "ok")
            j = pin.computeFrameJacobian(self._pin, self._data, q, fid, pin.LOCAL_WORLD_ALIGNED)
            j_arm = j[:, idxs]
            err6 = np.zeros(6)
            err6[0:3] = pos_err
            err6[3:6] = np.array(
                [r_err[2, 1] - r_err[1, 2], r_err[0, 2] - r_err[2, 0], r_err[1, 0] - r_err[0, 1]]
            )
            jj = j_arm @ j_arm.T + 0.05 * np.eye(6)
            dq = j_arm.T @ np.linalg.solve(jj, err6)
            for i, idx in enumerate(idxs):
                q[idx] += 0.35 * dq[i]
        return IkResult(False, tuple(q.tolist()), pos_norm, angle, max_iter, "max_iter")
