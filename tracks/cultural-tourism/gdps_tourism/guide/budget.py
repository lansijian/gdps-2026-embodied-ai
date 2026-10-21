"""30-minute mission budget: walking + narration + listening must fit in time.

The competition gives ~30 minutes for the whole autonomous tour.  This module
turns that into per-station caps and answers three questions the workflow asks:

  - how much time is left?
  - how long may this station narrate (keeping a reserve)?
  - has the station / the whole mission overrun?
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Budget:
    total_s: float = 1800.0      # 30 minutes for the whole mission
    reserve_s: float = 180.0     # keep 3 minutes for the closing / recovery
    max_narration_s: float = 90.0
    max_listen_s: float = 60.0
    max_station_s: float = 180.0  # hard cap per station (walk+observe+talk)
    started_at: Optional[float] = None
    station_started_at: Optional[float] = None
    station_id: Optional[str] = None
    per_station_s: Dict[str, float] = field(default_factory=dict)

    # -- lifecycle ---------------------------------------------------------
    def start(self, now: Optional[float] = None) -> None:
        self.started_at = self._now(now)

    def start_station(self, station_id: str, now: Optional[float] = None) -> None:
        moment = self._now(now)
        self.station_id = station_id
        self.station_started_at = moment

    def finish_station(self, now: Optional[float] = None) -> float:
        if self.station_started_at is None or not self.station_id:
            return 0.0
        spent = self._now(now) - self.station_started_at
        self.per_station_s[self.station_id] = round(spent, 1)
        self.station_started_at = None
        self.station_id = None
        return spent

    # -- queries -----------------------------------------------------------
    def elapsed_s(self, now: Optional[float] = None) -> float:
        if self.started_at is None:
            return 0.0
        return self._now(now) - self.started_at

    def remaining_s(self, now: Optional[float] = None) -> float:
        return max(0.0, self.total_s - self.elapsed_s(now))

    def remaining_work_s(self, now: Optional[float] = None) -> float:
        """Remaining time minus the closing reserve."""

        return max(0.0, self.remaining_s(now) - self.reserve_s)

    def station_elapsed_s(self, now: Optional[float] = None) -> float:
        if self.station_started_at is None:
            return 0.0
        return self._now(now) - self.station_started_at

    def narration_cap_s(self, stations_left: int, now: Optional[float] = None) -> float:
        """How long this station may talk without eating the rest of the tour."""

        if stations_left <= 0:
            return min(self.max_narration_s, self.remaining_work_s(now))
        share = self.remaining_work_s(now) / float(stations_left)
        allowance = share - 30.0  # walking + observation + listening per station
        return max(20.0, min(self.max_narration_s, allowance))

    def station_overrun(self, now: Optional[float] = None) -> bool:
        return self.station_elapsed_s(now) > self.max_station_s

    def mission_overrun(self, now: Optional[float] = None) -> bool:
        return self.remaining_s(now) <= self.reserve_s

    # -- internal ----------------------------------------------------------
    @staticmethod
    def _now(now: Optional[float]) -> float:
        return time.monotonic() if now is None else now


__all__ = ["Budget"]
