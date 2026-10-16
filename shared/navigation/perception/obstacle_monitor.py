from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class AvoidDecision(str, Enum):
    NO_SENSOR = "no_sensor"
    STOP = "stop"
    SLOW = "slow"
    DETOUR_LEFT = "detour_left"
    DETOUR_RIGHT = "detour_right"
    CLEAR = "clear"


@dataclass(frozen=True)
class ScanFrame:
    ranges: tuple[float, ...]
    angle_min: float
    angle_increment: float
    range_min: float = 0.05
    range_max: float = 20.0
    frame_id: str = "unverified_lidar_frame"


@dataclass
class ObstacleMonitor:
    """2D obstacle gating from a laser/scan-like range array.

    This is local avoidance only. It is not SLAM or Nav2.
    """

    stop_distance_m: float = 0.60
    slow_distance_m: float = 1.20
    forward_half_angle_rad: float = 0.60
    invalid_range: float = 0.0
    last_scan: ScanFrame | None = None
    last_min_forward: float | None = None
    last_decision: AvoidDecision = AvoidDecision.NO_SENSOR
    stats: dict[str, float] = field(default_factory=dict)

    def update(self, scan: ScanFrame) -> AvoidDecision:
        self.last_scan = scan
        valid = []
        left = []
        right = []
        for i, raw in enumerate(scan.ranges):
            if raw is None or math.isnan(raw) or math.isinf(raw):
                continue
            if raw <= scan.range_min or raw >= scan.range_max:
                continue
            angle = scan.angle_min + i * scan.angle_increment
            wrapped = math.atan2(math.sin(angle), math.cos(angle))
            if abs(wrapped) <= self.forward_half_angle_rad:
                valid.append(raw)
            if 0.15 < wrapped <= 1.2:
                left.append(raw)
            if -1.2 <= wrapped < -0.15:
                right.append(raw)
        self.stats = {
            "n_forward": float(len(valid)),
            "n_left": float(len(left)),
            "n_right": float(len(right)),
        }
        if not valid:
            self.last_min_forward = None
            self.last_decision = AvoidDecision.NO_SENSOR
            return self.last_decision
        min_fwd = min(valid)
        self.last_min_forward = min_fwd
        if min_fwd <= self.stop_distance_m:
            self.last_decision = AvoidDecision.STOP
            return self.last_decision
        if min_fwd <= self.slow_distance_m:
            left_min = min(left) if left else scan.range_max
            right_min = min(right) if right else scan.range_max
            if left_min > right_min + 0.15:
                self.last_decision = AvoidDecision.DETOUR_LEFT
            elif right_min > left_min + 0.15:
                self.last_decision = AvoidDecision.DETOUR_RIGHT
            else:
                self.last_decision = AvoidDecision.SLOW
            return self.last_decision
        self.last_decision = AvoidDecision.CLEAR
        return self.last_decision
