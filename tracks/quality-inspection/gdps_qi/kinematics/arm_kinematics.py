from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from gdps_qi.math_se3 import (
    compose_transform,
    invert_transform,
    make_transform,
    rot_to_quat,
    transform_from_pose,
)

# Simplified 7-DoF serial chain for offline IK/FK validation only.
# Real G1 EDU chain must be loaded from verified URDF (DOCUMENTED_UNVERIFIED).
ARM_JOINT_NAMES_LEFT = tuple(f"left_arm_joint_{i}" for i in range(7))
ARM_JOINT_NAMES_RIGHT = tuple(f"right_arm_joint_{i}" for i in range(7))

_DH_PARAMS = [
    (0.0, 0.0, 0.15, 0.0),
    (0.0, -math.pi / 2, 0.0, 0.0),
    (0.0, math.pi / 2, 0.30, 0.0),
    (0.0, -math.pi / 2, 0.0, 0.0),
    (0.0, math.pi / 2, 0.25, 0.0),
    (0.0, -math.pi / 2, 0.0, 0.0),
    (0.0, 0.0, 0.10, 0.0),
]

_JOINT_LIMITS = [(-2.8, 2.8)] * 7


def _dh_transform(a: float, alpha: float, d: float, theta: float) -> np.ndarray:
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array(
        [
            [ct, -st * ca, st * sa, a * ct],
            [st, ct * ca, -ct * sa, a * st],
            [0, sa, ca, d],
            [0, 0, 0, 1],
        ],
        dtype=float,
    )


@dataclass
class IkResult:
    success: bool
    joint_positions: Tuple[float, ...]
    position_error_m: float
    orientation_error_rad: float
    iterations: int
    message: str = ""


@dataclass
class ArmKinematics:
    joint_limits: List[Tuple[float, float]] = field(default_factory=lambda: list(_JOINT_LIMITS))
    max_iterations: int = 80
    position_tolerance_m: float = 0.002
    orientation_tolerance_rad: float = 0.05
    damping: float = 0.05

    def fk(self, joint_positions: Sequence[float], base_to_shoulder: Optional[np.ndarray] = None) -> np.ndarray:
        if len(joint_positions) != 7:
            raise ValueError("expected 7 joints")
        t = base_to_shoulder if base_to_shoulder is not None else np.eye(4)
        for i, q in enumerate(joint_positions):
            a, alpha, d, theta0 = _DH_PARAMS[i]
            t = compose_transform(t, _dh_transform(a, alpha, d, q + theta0))
        return t

    def fk_wrist_pose(
        self, joint_positions: Sequence[float], base_to_shoulder: Optional[np.ndarray] = None
    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]:
        t = self.fk(joint_positions, base_to_shoulder)
        p = t[:3, 3]
        q = rot_to_quat(t[:3, :3])
        return (float(p[0]), float(p[1]), float(p[2])), (
            float(q[0]),
            float(q[1]),
            float(q[2]),
            float(q[3]),
        )

    def jacobian(self, joint_positions: Sequence[float], base_to_shoulder: Optional[np.ndarray] = None) -> np.ndarray:
        eps = 1e-6
        t0 = self.fk(joint_positions, base_to_shoulder)
        p0 = t0[:3, 3]
        j = np.zeros((6, 7), dtype=float)
        for i in range(7):
            q2 = list(joint_positions)
            q2[i] += eps
            t1 = self.fk(q2, base_to_shoulder)
            p1 = t1[:3, 3]
            j[0:3, i] = (p1 - p0) / eps
            r0 = t0[:3, :3]
            r1 = t1[:3, :3]
            w = np.cross(r0[:, 0], r1[:, 0])
            j[3:6, i] = w / eps
        return j

    def ik(
        self,
        target_t_base_wrist: np.ndarray,
        seed: Sequence[float],
        base_to_shoulder: Optional[np.ndarray] = None,
    ) -> IkResult:
        q = np.asarray(seed, dtype=float).copy()
        if q.shape[0] != 7:
            return IkResult(False, tuple(seed), 1.0, 1.0, 0, "bad seed")
        t_shoulder_target = target_t_base_wrist
        if base_to_shoulder is not None:
            t_shoulder_target = compose_transform(invert_transform(base_to_shoulder), target_t_base_wrist)
        for it in range(self.max_iterations):
            t_cur = self.fk(q, base_to_shoulder)
            pos_err = t_shoulder_target[:3, 3] - t_cur[:3, 3]
            r_err = t_shoulder_target[:3, :3] @ t_cur[:3, :3].T
            angle = math.acos(max(-1.0, min(1.0, (np.trace(r_err) - 1.0) / 2.0)))
            pos_norm = float(np.linalg.norm(pos_err))
            if pos_norm < self.position_tolerance_m and angle < self.orientation_tolerance_rad:
                return IkResult(True, tuple(q.tolist()), pos_norm, angle, it + 1, "ok")
            j = self.jacobian(q, base_to_shoulder)
            err = np.zeros(6)
            err[0:3] = pos_err
            err[3:6] = np.array([r_err[2, 1] - r_err[1, 2], r_err[0, 2] - r_err[2, 0], r_err[1, 0] - r_err[0, 1]])
            jj = j @ j.T + (self.damping ** 2) * np.eye(6)
            dq = j.T @ np.linalg.solve(jj, err)
            q = q + 0.35 * dq
            for i, (lo, hi) in enumerate(self.joint_limits):
                q[i] = max(lo, min(hi, q[i]))
        t_final = self.fk(q, base_to_shoulder)
        pos_norm = float(np.linalg.norm(t_shoulder_target[:3, 3] - t_final[:3, 3]))
        r_err = t_shoulder_target[:3, :3] @ t_final[:3, :3].T
        angle = math.acos(max(-1.0, min(1.0, (np.trace(r_err) - 1.0) / 2.0)))
        ok = pos_norm < self.position_tolerance_m and angle < self.orientation_tolerance_rad
        return IkResult(ok, tuple(q.tolist()), pos_norm, angle, self.max_iterations, "max_iter")

    def wrist_target_from_tcp(
        self,
        t_base_tcp: np.ndarray,
        t_wrist_tcp: np.ndarray,
    ) -> np.ndarray:
        return compose_transform(t_base_tcp, invert_transform(t_wrist_tcp))
