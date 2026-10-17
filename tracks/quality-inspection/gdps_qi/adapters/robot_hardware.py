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
    """Exclusive owner for body/arm motion requests. Live actuation disabled by default."""

    owner: str = "gdps_quality_inspection"
    interface_status: VerificationStatus = VerificationStatus.DOCUMENTED_UNVERIFIED
    _joint_state: JointStateSnapshot = field(
        default_factory=lambda: JointStateSnapshot(
            names=tuple(f"joint_{i}" for i in range(29)),
            positions=tuple(0.0 for _ in range(29)),
            stamp=time.time(),
            source="mock",
        )
    )
    _motion_log: List[Dict[str, object]] = field(default_factory=list)
    _live_enabled: bool = False

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
        if not allow_live or not self._live_enabled:
            self._motion_log.append(
                {
                    "type": "arm_joint_dry_run",
                    "arm": arm,
                    "targets": joint_targets,
                    "reason": reason,
                    "stamp": time.time(),
                }
            )
            return True, "dry_run_recorded"
        return False, "live_arm_motion_not_implemented"

    def enable_live_motion(self, token: str, confirm: str) -> None:
        if confirm != "ENABLE LIVE ARM":
            raise PermissionError("confirm phrase mismatch")
        if token != "UNSET":
            raise PermissionError("live token not configured for arms")
        self._live_enabled = True

    @property
    def motion_log(self) -> List[Dict[str, object]]:
        return list(self._motion_log)
