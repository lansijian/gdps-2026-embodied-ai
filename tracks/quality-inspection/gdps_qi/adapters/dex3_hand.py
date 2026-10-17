from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from gdps_qi.types import VerificationStatus


@dataclass(frozen=True)
class HandState:
    side: str
    joint_positions: Tuple[float, ...]
    stamp: float
    source: str = "mock"


@dataclass(frozen=True)
class HandCommand:
    side: str
    joint_targets: Tuple[float, ...]
    mode: str = "position"


# Dex3-1 seven actuated joints per hand (indices per unitree_sdk2 dex3 example — DOCUMENTED_UNVERIFIED on-site).
DEX3_JOINT_COUNT = 7

# Grasp templates: normalized open / pinch for offline planning (radians, UNVERIFIED scale).
GRASP_OPEN = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
GRASP_TABLET_PINCH = (0.35, 0.55, 0.55, 0.2, 0.2, 0.15, 0.15)
GRASP_TUBE_BODY = (0.25, 0.4, 0.4, 0.3, 0.3, 0.2, 0.2)
GRASP_CAP_TWIST = (0.3, 0.5, 0.45, 0.25, 0.25, 0.18, 0.18)


@dataclass
class Dex3HandAdapter:
    interface_status: VerificationStatus = VerificationStatus.DOCUMENTED_UNVERIFIED
    _state: Dict[str, HandState] = field(default_factory=dict)
    _cmd_log: List[Dict[str, object]] = field(default_factory=list)
    hardware_writes_enabled: bool = False

    def connect(self) -> int:
        now = time.time()
        for side in ("left", "right"):
            self._state[side] = HandState(
                side=side,
                joint_positions=GRASP_OPEN,
                stamp=now,
            )
        return 0

    def get_state(self, side: str) -> HandState:
        if side not in self._state:
            raise KeyError(side)
        return self._state[side]

    def send_command(self, cmd: HandCommand, allow_live: bool) -> Tuple[bool, str]:
        if len(cmd.joint_targets) != DEX3_JOINT_COUNT:
            return False, "joint count mismatch"
        if allow_live:
            return False, "hardware_writes_disabled"
        self._cmd_log.append(
            {
                "type": "hand_dry_run",
                "side": cmd.side,
                "targets": cmd.joint_targets,
                "mode": cmd.mode,
                "stamp": time.time(),
            }
        )
        self._state[cmd.side] = HandState(
            side=cmd.side,
            joint_positions=cmd.joint_targets,
            stamp=time.time(),
            source="mock",
        )
        return True, "dry_run_recorded"

    @property
    def command_log(self) -> List[Dict[str, object]]:
        return list(self._cmd_log)
