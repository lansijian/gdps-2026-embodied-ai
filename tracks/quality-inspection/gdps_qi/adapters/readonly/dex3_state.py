from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from gdps_qi.adapters.dex3_hand import HandState
from gdps_qi.types import VerificationStatus


@dataclass
class Dex3StateReadOnly:
    status: VerificationStatus = VerificationStatus.DOCUMENTED_UNVERIFIED
    hand_state_topic_left: str = "rt/lf/dex3/state"
    hand_state_topic_right: str = "rt/rf/dex3/state"
    _cache: Dict[str, HandState] = {}

    def connect(self) -> Tuple[bool, str]:
        return False, "dds_hand_state_subscription_not_wired_in_phase2"

    def get_hand(self, side: str) -> Optional[HandState]:
        return self._cache.get(side)

    def field_check_steps(self) -> Tuple[str, ...]:
        return (
            "unitree_sdk2_python: subscribe HandState only (no HandCmd)",
            "Confirm 7 joint indices per hand vs g1_dex3_example.cpp",
            "Check whether current/force/tactile fields are populated",
        )
