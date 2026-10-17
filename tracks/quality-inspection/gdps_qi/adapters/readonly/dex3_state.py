from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from gdps_qi.adapters.dex3_hand import HandState
from gdps_qi.hardware.g1_joint_map import DEX3_JOINT_NAMES_LEFT, DEX3_JOINT_NAMES_RIGHT
from gdps_qi.types import VerificationStatus


@dataclass
class Dex3StateReadOnly:
    hand_state_topic_left: str = "rt/lf/dex3/state"
    hand_state_topic_right: str = "rt/rf/dex3/state"
    status: VerificationStatus = VerificationStatus.DOCUMENTED_UNVERIFIED
    _cache: Dict[str, HandState] = field(default_factory=dict)
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "dex3_hands",
            "left_topic": self.hand_state_topic_left,
            "right_topic": self.hand_state_topic_right,
            "joint_names_left": DEX3_JOINT_NAMES_LEFT,
            "joint_names_right": DEX3_JOINT_NAMES_RIGHT,
            "tactile_fields": "UNKNOWN",
            "missing": [],
        }
        if not live:
            report["mode"] = "dry_run_schema"
            self._last_probe = report
            return report
        report["mode"] = "live_readonly"
        try:
            from unitree_sdk2py.core.channel import ChannelSubscriber  # type: ignore
        except ImportError as exc:
            report["dds"] = {"ok": False, "error": f"unitree_sdk2py_unavailable:{exc}"}
            return report
        report["dds"] = {
            "ok": False,
            "error": "hand_state_subscriber_requires_on_robot_manual_run",
            "sdk_import": True,
        }
        self._last_probe = report
        return report

    def get_hand(self, side: str) -> Optional[HandState]:
        return self._cache.get(side)
