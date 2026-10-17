from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class JointValidity(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    VALID = "VALID"


@dataclass
class JointSnapshot:
    positions: Dict[str, float]
    stamp_sec: Optional[float]
    source: str
    validity: JointValidity
    mapping_basis: str
    missing_joints: Tuple[str, ...] = ()
    raw_joint_count: int = 0

    def get_position(self, name: str) -> Tuple[Optional[float], str]:
        if name in self.positions:
            return self.positions[name], "ok"
        return None, "missing"
