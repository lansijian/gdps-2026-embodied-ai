from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class DeadlineManager:
    total_budget_s: float = 30 * 60.0
    started_at: float = field(default_factory=time.time)
    action_estimates_s: Dict[str, float] = field(
        default_factory=lambda: {
            "P1": 120.0,
            "P2": 180.0,
            "P3": 90.0,
            "P4": 60.0,
            "P5": 90.0,
            "P6": 60.0,
        }
    )
    safety_margin_s: float = 120.0

    def remaining_s(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        elapsed = now - self.started_at
        return max(0.0, self.total_budget_s - elapsed)

    def should_continue(self, upcoming_phases: Tuple[str, ...], retry_risk: float = 0.0) -> Tuple[bool, str]:
        need = self.safety_margin_s + retry_risk * 60.0
        for ph in upcoming_phases:
            need += self.action_estimates_s.get(ph, 60.0)
        rem = self.remaining_s()
        if rem < need:
            return False, f"insufficient_time need={need:.0f}s rem={rem:.0f}s"
        return True, "ok"
