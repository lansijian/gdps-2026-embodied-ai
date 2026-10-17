from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import numpy as np

from gdps_qi.hardware.g1_joint_map import G1_LEFT_ARM_JOINTS, G1_RIGHT_ARM_JOINTS
from gdps_qi.kinematics.arm_kinematics import ArmKinematics, IkResult
from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel


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
        side: str = "left",
    ) -> IkResult:
        raise NotImplementedError

    def check_segment_reachable(
        self, start_joints: Sequence[float], target_t: np.ndarray, label: str, side: str = "left"
    ) -> Tuple[bool, IkResult]:
        ik = self.ik(target_t, start_joints, side=side)
        if not ik.success:
            return False, ik
        fk = self.fk(ik.joint_positions, side=side)
        err = float(np.linalg.norm(fk[:3, 3] - target_t[:3, 3]))
        if err > max(ik.position_error_m * 2.0, 0.005):
            ik.success = False
            ik.message = f"{label}_fk_residual"
        return ik.success, ik


@dataclass
class SimplifiedTestKinematics(KinematicsBackend):
    kind: KinematicsBackendKind = KinematicsBackendKind.SIMPLIFIED_MATH_TEST_ONLY
    _impl: ArmKinematics = field(default_factory=ArmKinematics)

    def allow_hardware_joint_targets(self) -> bool:
        return False

    def fk(self, joint_positions: Sequence[float], frame: str = "wrist", side: str = "left") -> np.ndarray:
        return self._impl.fk(joint_positions)

    def ik(
        self, target_t: np.ndarray, seed: Sequence[float], frame: str = "wrist", side: str = "left"
    ) -> IkResult:
        return self._impl.ik(target_t, seed)


@dataclass
class G1UrdfKinematicsAdapter(KinematicsBackend):
    urdf_path: Optional[str] = None
    verified_on_robot: bool = False
    kind: KinematicsBackendKind = KinematicsBackendKind.UNAVAILABLE
    _model: Optional[G1UrdfModel] = None

    def __post_init__(self) -> None:
        if not self.urdf_path:
            self.kind = KinematicsBackendKind.UNAVAILABLE
            return
        self._model = G1UrdfModel(self.urdf_path)
        if self._model.load():
            self.kind = (
                KinematicsBackendKind.G1_URDF_VERIFIED
                if self.verified_on_robot
                else KinematicsBackendKind.G1_URDF_UNVERIFIED
            )
        else:
            self.kind = KinematicsBackendKind.UNAVAILABLE

    def allow_hardware_joint_targets(self) -> bool:
        return self.kind is KinematicsBackendKind.G1_URDF_VERIFIED

    def fk(self, joint_positions: Sequence[float], frame: str = "wrist", side: str = "left") -> np.ndarray:
        if self._model is None:
            raise RuntimeError("urdf_not_loaded")
        if isinstance(joint_positions, dict):
            joints = joint_positions
        else:
            names = G1_LEFT_ARM_JOINTS if side == "left" else G1_RIGHT_ARM_JOINTS
            joints = {n: joint_positions[i] for i, n in enumerate(names) if i < len(joint_positions)}
        return self._model.fk_arm_wrist(side, joints)

    def ik(
        self, target_t: np.ndarray, seed: Sequence[float], frame: str = "wrist", side: str = "left"
    ) -> IkResult:
        if self._model is None or self._model._pin is None:
            return IkResult(False, tuple(seed), 1.0, 1.0, 0, "urdf_model_unavailable")
        from gdps_qi.hardware.g1_joint_map import URDF_FRAME_LEFT_WRIST, URDF_FRAME_RIGHT_WRIST

        frame_name = URDF_FRAME_LEFT_WRIST if side == "left" else URDF_FRAME_RIGHT_WRIST
        arm_names = G1_LEFT_ARM_JOINTS if side == "left" else G1_RIGHT_ARM_JOINTS
        seed_q = self._model.neutral_q()
        for i, n in enumerate(arm_names):
            idx = self._model._joint_name_to_q.get(n)
            if idx is not None and i < len(seed):
                seed_q[idx] = seed[i]
        return self._model.ik_frame_dls(frame_name, target_t, seed_q, arm_names)
