from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from gdps_qi.adapters.dex3_hand import HandState
from gdps_qi.adapters.readonly.dds_readonly import DdsReadOnlyConfig, parse_hand_state, subscribe_dds_once
from gdps_qi.hardware.g1_joint_map import DEX3_JOINT_NAMES_LEFT, DEX3_JOINT_NAMES_RIGHT
from gdps_qi.types import VerificationStatus


@dataclass
class Dex3StateReadOnly:
    hand_state_topic_left: str = "rt/lf/dex3/state"
    hand_state_topic_right: str = "rt/rf/dex3/state"
    dds_cfg: DdsReadOnlyConfig = field(default_factory=DdsReadOnlyConfig)
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _cache: Dict[str, HandState] = field(default_factory=dict)
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "dex3_hands",
            "left_topic": self.hand_state_topic_left,
            "right_topic": self.hand_state_topic_right,
            "joint_names_left": DEX3_JOINT_NAMES_LEFT,
            "joint_names_right": DEX3_JOINT_NAMES_RIGHT,
            "left_validity": "UNKNOWN",
            "right_validity": "UNKNOWN",
        }
        self._cache.clear()
        if not live:
            report["mode"] = "dry_run_schema"
            self._last_probe = report
            return report
        report["mode"] = "live_readonly"
        try:
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandState_  # type: ignore
        except ImportError as exc:
            report["dds"] = {"ok": False, "error": f"hand_state_idl_unavailable:{exc}"}
            self._last_probe = report
            return report
        left = subscribe_dds_once(
            self.hand_state_topic_left,
            HandState_,
            timeout_s,
            lambda m: parse_hand_state(m, "left"),
            self.dds_cfg,
        )
        right = subscribe_dds_once(
            self.hand_state_topic_right,
            HandState_,
            timeout_s,
            lambda m: parse_hand_state(m, "right"),
            self.dds_cfg,
        )
        report["left"] = left
        report["right"] = right
        import time

        now = time.time()
        if left.get("ok"):
            report["left_validity"] = left.get("validity", "UNKNOWN")
            joints = left.get("joint_positions")
            if isinstance(joints, list) and len(joints) == 7:
                stamp = left.get("host_received_at", now)
                self._cache["left"] = HandState("left", tuple(float(x) for x in joints), float(stamp), "dds")
        if right.get("ok"):
            report["right_validity"] = right.get("validity", "UNKNOWN")
            joints = right.get("joint_positions")
            if isinstance(joints, list) and len(joints) == 7:
                stamp = right.get("host_received_at", now)
                self._cache["right"] = HandState("right", tuple(float(x) for x in joints), float(stamp), "dds")
        if self._cache:
            self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        self._last_probe = report
        return report

    def get_hand(self, side: str) -> Optional[HandState]:
        return self._cache.get(side)
