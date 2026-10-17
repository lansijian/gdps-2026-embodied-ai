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
    forward_angle_offset_rad: float = 0.0
    frame_extrinsic_verified: bool = False
    blind_zone_m: float = 0.40  # returns closer than this are uncertain (self/near-blind)
    min_forward_points: int = 3  # need at least this many front returns to decide
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
            wrapped = math.atan2(
                math.sin(angle - self.forward_angle_offset_rad),
                math.cos(angle - self.forward_angle_offset_rad),
            )
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
        # Too few front returns -> uncertain, NOT clear.
        if len(valid) < self.min_forward_points:
            self.last_min_forward = None
            self.last_decision = AvoidDecision.NO_SENSOR
            return self.last_decision
        # Exclude blind-zone returns from the decision (self-occlusion / near-blind).
        reliable = [r for r in valid if r >= self.blind_zone_m]
        if not reliable:
            # All front returns are in the blind zone -> uncertain, NOT clear.
            self.last_min_forward = min(valid)
            self.last_decision = AvoidDecision.NO_SENSOR
            return self.last_decision
        min_fwd = min(reliable)
        self.last_min_forward = min_fwd
        if min_fwd <= self.stop_distance_m:
            self.last_decision = AvoidDecision.STOP
            return self.last_decision
        if min_fwd <= self.slow_distance_m:
            left_min = min((r for r in left if r >= self.blind_zone_m), default=scan.range_max)
            right_min = min((r for r in right if r >= self.blind_zone_m), default=scan.range_max)
            if left_min > right_min + 0.15:
                self.last_decision = AvoidDecision.DETOUR_LEFT
            elif right_min > left_min + 0.15:
                self.last_decision = AvoidDecision.DETOUR_RIGHT
            else:
                self.last_decision = AvoidDecision.SLOW
            return self.last_decision
        self.last_decision = AvoidDecision.CLEAR
        return self.last_decision

    def sector_ranges(self) -> dict:
        """Last-scan sector mins (lidar frame unless extrinsic verified)."""
        return {
            "min_forward_m": self.last_min_forward,
            "n_forward": self.stats.get("n_forward"),
            "n_left": self.stats.get("n_left"),
            "n_right": self.stats.get("n_right"),
            "decision": self.last_decision.value,
            "frame_extrinsic_verified": self.frame_extrinsic_verified,
        }
