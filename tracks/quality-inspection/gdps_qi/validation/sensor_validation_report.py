from __future__ import annotations

import enum
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ValidationScenario(str, enum.Enum):
    A_STATIC = "A_static_both_static"
    B_TARGET_LEFT = "B_target_left"
    C_TARGET_RIGHT = "C_target_right"
    D_FAR = "D_far"
    E_NEAR = "E_near"
    F_AFTER_LATERAL = "F_after_lateral"
    G_AFTER_WAIST = "G_after_waist"
    H_DEPTH_INVALID = "H_depth_invalid"
    I_LIDAR_DEPTH_CONFLICT = "I_lidar_depth_conflict"


@dataclass
class SensorSample:
    scenario: str
    pixel_du: float
    pixel_dv: float
    rgbd_p_base: Optional[tuple]
    lidar_range_m: Optional[float]
    odom_xy: Optional[tuple]
    tf_version: str
    depth_axis_m: Optional[float]
    horizontal_range_m: Optional[float]
    latency_ms: Optional[float]
    failure_reason: str = ""
    data_source: str = "replay"


@dataclass
class SensorValidationReport:
    generated_at: float = field(default_factory=time.time)
    samples: List[SensorSample] = field(default_factory=list)
    allow_cross_sensor_fusion: bool = False
    fusion_reasons: List[str] = field(default_factory=list)

    def add(self, sample: SensorSample) -> None:
        self.samples.append(sample)

    def summary(self) -> Dict[str, Any]:
        dus = [s.pixel_du for s in self.samples if not s.failure_reason]
        return {
            "generated_at": self.generated_at,
            "n_samples": len(self.samples),
            "pixel_du_std": _std(dus),
            "allow_cross_sensor_fusion": self.allow_cross_sensor_fusion,
            "fusion_reasons": self.fusion_reasons,
            "samples": [s.__dict__ for s in self.samples],
        }


def _std(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5


@dataclass
class LidarDepthAgreement:
    fusion_allowed: bool
    compare_allowed: bool
    reasons: List[str] = field(default_factory=list)


def assess_lidar_depth_agreement(
    depth_m: Optional[float],
    lidar_m: Optional[float],
    extrinsic_verified: bool,
    overlap_assumed: bool,
    same_target_correspondence: bool,
    tf_trusted: bool,
    tolerance_m: float = 0.25,
) -> LidarDepthAgreement:
    reasons: List[str] = []
    if not extrinsic_verified:
        reasons.append("extrinsic_unverified")
    if not overlap_assumed:
        reasons.append("fov_overlap_unverified")
    if not same_target_correspondence:
        reasons.append("target_correspondence_unverified")
    if not tf_trusted:
        reasons.append("tf_not_trusted")
    if depth_m is None or lidar_m is None:
        reasons.append("missing_measurement")
        return LidarDepthAgreement(False, False, reasons)
    if not math.isfinite(depth_m) or not math.isfinite(lidar_m) or min(depth_m, lidar_m) <= 0:
        reasons.append("invalid_measurement")
    if reasons:
        return LidarDepthAgreement(False, False, reasons)
    compare_allowed = abs(depth_m - lidar_m) <= tolerance_m
    if not compare_allowed:
        reasons.append("range_conflict")
    return LidarDepthAgreement(fusion_allowed=False, compare_allowed=compare_allowed, reasons=reasons)
