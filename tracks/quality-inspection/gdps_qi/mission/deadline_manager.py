from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class DeadlineManager:
    total_budget_s: float = 30 * 60.0
    started_mono: float = field(default_factory=time.monotonic)
    per_sample_p1_s: float = 120.0
    per_sample_p2_s: float = 180.0
    centrifuge_fixed_s: float = 300.0
    p4_s: float = 60.0
    p5_per_sample_s: float = 15.0
    p6_s: float = 60.0
    sample_count: int = 6
    safety_margin_s: float = 120.0
    retry_risk_factor_s: float = 60.0

    def remaining_s(self, now_mono: Optional[float] = None) -> float:
        now_mono = now_mono if now_mono is not None else time.monotonic()
        elapsed = now_mono - self.started_mono
        return max(0.0, self.total_budget_s - elapsed)

    def estimate_remaining_work_s(
        self,
        samples_remaining: int,
        include_centrifuge: bool,
        include_p4_p5_p6: bool,
        retry_risk: float = 0.0,
    ) -> float:
        samples_remaining = max(0, min(self.sample_count, samples_remaining))
        need = self.safety_margin_s + retry_risk * self.retry_risk_factor_s
        need += samples_remaining * (self.per_sample_p1_s + self.per_sample_p2_s)
        if include_centrifuge:
            need += self.centrifuge_fixed_s
        if include_p4_p5_p6:
            need += self.p4_s + self.sample_count * self.p5_per_sample_s + self.p6_s
        return need

    def should_continue(
        self,
        samples_remaining: int = 6,
        include_centrifuge: bool = True,
        include_p4_p5_p6: bool = True,
        retry_risk: float = 0.0,
        now_mono: Optional[float] = None,
    ) -> Tuple[bool, str]:
        need = self.estimate_remaining_work_s(
            samples_remaining, include_centrifuge, include_p4_p5_p6, retry_risk
        )
        rem = self.remaining_s(now_mono)
        if rem < need:
            return False, f"insufficient_time need={need:.0f}s rem={rem:.0f}s"
        return True, "ok"

    # Back-compat for legacy phase tuple API used in tests
    def should_continue_phases(
        self, upcoming_phases: Tuple[str, ...], retry_risk: float = 0.0
    ) -> Tuple[bool, str]:
        legacy = {
            "P1": self.per_sample_p1_s,
            "P2": self.per_sample_p2_s,
            "P3": self.centrifuge_fixed_s,
            "P4": self.p4_s,
            "P5": self.p5_per_sample_s * self.sample_count,
            "P6": self.p6_s,
        }
        need = self.safety_margin_s + retry_risk * self.retry_risk_factor_s
        for ph in upcoming_phases:
            need += legacy.get(ph, 60.0)
        rem = self.remaining_s()
        if rem < need:
            return False, f"insufficient_time need={need:.0f}s rem={rem:.0f}s"
        return True, "ok"
