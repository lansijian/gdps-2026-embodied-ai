from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VelocityCommand:
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0
    duration_s: float = 1.0
    source: str = "unknown"

    def is_zero(self, eps: float = 1e-6) -> bool:
        return abs(self.vx) < eps and abs(self.vy) < eps and abs(self.wz) < eps
