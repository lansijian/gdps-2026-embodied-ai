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


@dataclass
class JointConfigureResult:
    ok: bool
    q: Optional[np.ndarray]
    missing: Tuple[str, ...]
    message: str


@dataclass
class G1UrdfModel:
    urdf_path: str
    base_frame: str = "pelvis"
    robot_variant: str = "UNKNOWN"
    _pin: object = None
    _data: object = None
    _frame_ids: Dict[str, int] = field(default_factory=dict)
    _joint_name_to_q: Dict[str, int] = field(default_factory=dict)
    _joint_limits: Dict[int, Tuple[float, float]] = field(default_factory=dict)
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
                    if self._pin.upperPositionLimit.size > jid:
                        lo = float(self._pin.lowerPositionLimit[jid])
                        hi = float(self._pin.upperPositionLimit[jid])
                        self._joint_limits[self._joint_name_to_q[jname]] = (lo, hi)
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

    def frame_exists(self, frame_name: str) -> bool:
        if self._pin is None:
            return False
        try:
            import pinocchio as pin  # type: ignore

            fid = self._pin.getFrameId(frame_name)
            return fid < self._pin.nframes
        except Exception:
            return False

    def configure_required_joints(
        self, joint_positions: Dict[str, float], required: Sequence[str]
    ) -> JointConfigureResult:
        if self._pin is None:
            return JointConfigureResult(False, None, tuple(required), "model_not_loaded")
        missing = tuple(n for n in required if n not in joint_positions)
        if missing:
            return JointConfigureResult(False, None, missing, "missing_required_joints")
        q = np.zeros(self._pin.nq)
        for name, val in joint_positions.items():
            idx = self._joint_name_to_q.get(name)
            if idx is not None:
                q[idx] = float(val)
        return JointConfigureResult(True, q, (), "ok")

    def set_named_joints(self, joint_positions: Dict[str, float]) -> np.ndarray:
        import pinocchio as pin  # type: ignore

        cfg = self.configure_required_joints(joint_positions, joint_positions.keys())
        if not cfg.ok or cfg.q is None:
            raise ValueError(cfg.message)
        pin.forwardKinematics(self._pin, self._data, cfg.q)
        pin.updateFramePlacements(self._pin, self._data)
        return cfg.q

    def frame_placement(self, frame_name: str, q: Optional[np.ndarray] = None) -> np.ndarray:
        import pinocchio as pin  # type: ignore

        if self._pin is None or self._data is None:
            raise RuntimeError("model not loaded")
        if not self.frame_exists(frame_name):
            raise ValueError(f"frame_missing:{frame_name}")
        if q is not None:
            pin.forwardKinematics(self._pin, self._data, q)
            pin.updateFramePlacements(self._pin, self._data)
        fid = self._frame_ids.get(frame_name) or self._pin.getFrameId(frame_name)
        se3 = self._data.oMf[fid]
        t = np.eye(4)
        t[:3, :3] = np.array(se3.rotation)
        t[:3, 3] = np.array(se3.translation).reshape(3)
        return t

    def fk_arm_wrist(self, side: str, joint_positions: Dict[str, float]) -> np.ndarray:
        names = list(G1_LEFT_ARM_JOINTS if side == "left" else G1_RIGHT_ARM_JOINTS)
        names += list(G1_WAIST_JOINTS)
        cfg = self.configure_required_joints(joint_positions, names)
        if not cfg.ok or cfg.q is None:
            raise ValueError(cfg.message)
        frame = URDF_FRAME_LEFT_WRIST if side == "left" else URDF_FRAME_RIGHT_WRIST
        return self.frame_placement(frame, cfg.q)

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
        if not self.frame_exists(frame_name):
            return IkResult(False, tuple(seed_q.tolist()), 1.0, 1.0, 0, "frame_missing")
        q = seed_q.copy()
        fid = self._frame_ids.get(frame_name) or self._pin.getFrameId(frame_name)
        idxs = []
        for jn in arm_joint_names:
            idx = self._joint_name_to_q.get(jn)
            if idx is not None:
                idxs.append(idx)
        if not idxs:
            return IkResult(False, tuple(q.tolist()), 1.0, 1.0, 0, "no_joint_indices")
        pos_norm = 1.0
        angle = 1.0
        for it in range(max_iter):
            pin.forwardKinematics(self._pin, self._data, q)
            pin.updateFramePlacements(self._pin, self._data)
            cur = self._data.oMf[fid]
            cur_t = np.eye(4)
            cur_t[:3, :3] = np.array(cur.rotation)
            cur_t[:3, 3] = np.array(cur.translation).reshape(3)
            pos_err = target_t[:3, 3] - cur_t[:3, 3]
            r_err = np.array(target_t[:3, :3]) @ np.array(cur.rotation).T
            rot_err = pin.log3(r_err)
            pos_norm = float(np.linalg.norm(pos_err))
            angle = float(np.linalg.norm(rot_err))
            if pos_norm < 0.003 and angle < 0.05:
                fk_check = self.frame_placement(frame_name, q)
                fk_err = float(np.linalg.norm(fk_check[:3, 3] - target_t[:3, 3]))
                if fk_err > 0.005:
                    return IkResult(False, tuple(q.tolist()), fk_err, angle, it + 1, "fk_residual")
                return IkResult(True, tuple(q.tolist()), pos_norm, angle, it + 1, "ok")
            j = pin.computeFrameJacobian(self._pin, self._data, q, fid, pin.LOCAL_WORLD_ALIGNED)
            j_arm = j[:, idxs]
            err6 = np.hstack([pos_err, rot_err])
            jj = j_arm @ j_arm.T + 0.05 * np.eye(6)
            dq = j_arm.T @ np.linalg.solve(jj, err6)
            for i, idx in enumerate(idxs):
                q[idx] += 0.25 * dq[i]
                lim = self._joint_limits.get(idx)
                if lim:
                    q[idx] = max(lim[0], min(lim[1], q[idx]))
        return IkResult(False, tuple(q.tolist()), pos_norm, angle, max_iter, "max_iter_unreachable")
