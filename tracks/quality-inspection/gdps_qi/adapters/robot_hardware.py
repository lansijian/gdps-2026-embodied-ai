from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from gdps_qi.types import VerificationStatus


@dataclass
class JointStateSnapshot:
    names: Tuple[str, ...]
    positions: Tuple[float, ...]
    stamp: float
    frame_id: str = "robot_center"
    source: str = "mock"


@dataclass
class RobotHardwareAdapter:
    """Arm motion write path is disabled for Phase 2 (read-only field prep)."""

    owner: str = "gdps_quality_inspection"
    interface_status: VerificationStatus = VerificationStatus.DOCUMENTED_UNVERIFIED
    hardware_writes_enabled: bool = False
    _joint_state: JointStateSnapshot = field(
        default_factory=lambda: JointStateSnapshot(
            names=tuple(f"joint_{i}" for i in range(29)),
            positions=tuple(0.0 for _ in range(29)),
            stamp=time.time(),
            source="mock",
        )
    )
    _motion_log: List[Dict[str, object]] = field(default_factory=list)

    def connect(self) -> int:
        return 0

    def get_joint_state(self) -> JointStateSnapshot:
        return self._joint_state

    def set_mock_joint_state(
        self, positions: Tuple[float, ...], stamp: Optional[float] = None
    ) -> None:
        if len(positions) != len(self._joint_state.names):
            raise ValueError("position count mismatch")
        self._joint_state = JointStateSnapshot(
            names=self._joint_state.names,
            positions=positions,
            stamp=stamp if stamp is not None else time.time(),
            frame_id=self._joint_state.frame_id,
            source="mock",
        )

    def request_arm_joint_targets(
        self,
        arm: str,
        joint_targets: Tuple[float, ...],
        reason: str,
        allow_live: bool,
    ) -> Tuple[bool, str]:
        if arm not in ("left", "right"):
            return False, "invalid arm"
        self._motion_log.append(
            {
                "type": "arm_joint_dry_run",
                "arm": arm,
                "targets": joint_targets,
                "reason": reason,
                "stamp": time.time(),
                "allow_live_requested": allow_live,
            }
        )
        if allow_live:
            return False, "hardware_writes_disabled"
        return True, "dry_run_recorded"

    @property
    def motion_log(self) -> List[Dict[str, object]]:
        return list(self._motion_log)
