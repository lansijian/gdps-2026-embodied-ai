from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import numpy as np

from gdps_qi.kinematics.arm_kinematics import ArmKinematics, IkResult


class KinematicsBackendKind(str, enum.Enum):
    SIMPLIFIED_MATH_TEST_ONLY = "SIMPLIFIED_MATH_TEST_ONLY"
    G1_URDF_UNVERIFIED = "G1_URDF_UNVERIFIED"
    G1_URDF_VERIFIED = "G1_URDF_VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class KinematicsBackend(ABC):
    kind: KinematicsBackendKind

    @abstractmethod
    def allow_hardware_joint_targets(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fk(self, joint_positions: Sequence[float], frame: str = "wrist") -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def ik(
        self,
        target_t: np.ndarray,
        seed: Sequence[float],
        frame: str = "wrist",
    ) -> IkResult:
        raise NotImplementedError

    def check_segment_reachable(
        self, start_joints: Sequence[float], target_t: np.ndarray, label: str
    ) -> Tuple[bool, IkResult]:
        ik = self.ik(target_t, start_joints)
        if not ik.success:
            return False, ik
        fk = self.fk(ik.joint_positions)
        err = float(np.linalg.norm(fk[:3, 3] - target_t[:3, 3]))
        if err > max(ik.position_error_m * 2.0, 0.005):
            ik.success = False
            ik.message = f"{label}_fk_residual"
        return ik.success, ik


@dataclass
class SimplifiedTestKinematics(KinematicsBackend):
    """Explicitly for math unit tests — never drives hardware."""

    kind: KinematicsBackendKind = KinematicsBackendKind.SIMPLIFIED_MATH_TEST_ONLY
    _impl: ArmKinematics = field(default_factory=ArmKinematics)

    def allow_hardware_joint_targets(self) -> bool:
        return False

    def fk(self, joint_positions: Sequence[float], frame: str = "wrist") -> np.ndarray:
        return self._impl.fk(joint_positions)

    def ik(self, target_t: np.ndarray, seed: Sequence[float], frame: str = "wrist") -> IkResult:
        return self._impl.ik(target_t, seed)


@dataclass
class G1UrdfKinematicsAdapter(KinematicsBackend):
    """Loads G1 URDF when path exists; uses Pinocchio if importable."""

    urdf_path: Optional[str] = None
    verified_on_robot: bool = False
    kind: KinematicsBackendKind = KinematicsBackendKind.UNAVAILABLE
    _pin_model: object = None
    _left_wrist_frame: str = "left_wrist_yaw_link"
    _right_wrist_frame: str = "right_wrist_yaw_link"

    def __post_init__(self) -> None:
        if not self.urdf_path:
            self.kind = KinematicsBackendKind.UNAVAILABLE
            return
        from pathlib import Path

        if not Path(self.urdf_path).is_file():
            self.kind = KinematicsBackendKind.UNAVAILABLE
            return
        try:
            import pinocchio as pin  # type: ignore

            self._pin_model = pin.buildModelFromUrdf(self.urdf_path)
            self.kind = (
                KinematicsBackendKind.G1_URDF_VERIFIED
                if self.verified_on_robot
                else KinematicsBackendKind.G1_URDF_UNVERIFIED
            )
        except Exception:
            self._pin_model = None
            self.kind = KinematicsBackendKind.G1_URDF_UNVERIFIED

    def allow_hardware_joint_targets(self) -> bool:
        return self.kind is KinematicsBackendKind.G1_URDF_VERIFIED

    def fk(self, joint_positions: Sequence[float], frame: str = "wrist") -> np.ndarray:
        raise NotImplementedError("G1 URDF FK requires configured joint index map (UNVERIFIED)")

    def ik(self, target_t: np.ndarray, seed: Sequence[float], frame: str = "wrist") -> IkResult:
        return IkResult(
            False,
            tuple(seed),
            1.0,
            1.0,
            0,
            "g1_urdf_ik_not_wired_without_verified_joint_map",
        )
