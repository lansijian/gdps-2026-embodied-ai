from __future__ import annotations

import enum
import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.perception.detection_types import Detection
from gdps_qi.perception.rgbd_target_geometry import (
    estimate_target_range,
    pixel_error_vs_principal_point,
)
from gdps_qi.transforms.transform_manager import TransformError, TransformManager


class CenteringMode(str, enum.Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    CENTER_BY_BODY_LATERAL = "CENTER_BY_BODY_LATERAL"
    CENTER_BY_WAIST_PREVIEW = "CENTER_BY_WAIST_PREVIEW"
    DOCK_FOR_MANIPULATION = "DOCK_FOR_MANIPULATION"
    SAFE_HOLD = "SAFE_HOLD"


@dataclass
class CenteringConfig:
    pixel_deadzone_px: float = 12.0
    bearing_deadzone_rad: float = 0.04
    confirm_frames: int = 3
    max_steps: int = 12
    max_duration_s: float = 120.0
    max_lateral_step_m: float = 0.08
    oscillation_window: int = 6
    min_depth_m: float = 0.25
    max_depth_m: float = 1.8


@dataclass
class CenteringStepResult:
    mode: CenteringMode
    centered: bool
    pixel_du: float
    pixel_dv: float
    bearing_rad: Optional[float]
    p_camera: Optional[Tuple[float, float, float]]
    p_base: Optional[Tuple[float, float, float]]
    recommended_lateral: str
    safe: bool
    reasons: List[str]
    step_index: int


@dataclass
class TargetCenteringController:
    tf: TransformManager
    base_frame: str = "robot_center"
    camera_frame: str = "camera_color_optical_frame"
    cfg: CenteringConfig = field(default_factory=CenteringConfig)
    _confirm: int = 0
    _steps: int = 0
    _t0: float = 0.0
    _bearing_history: List[float] = field(default_factory=list)

    def reset(self) -> None:
        self._confirm = 0
        self._steps = 0
        self._t0 = time.time()
        self._bearing_history.clear()

    def _t_base_camera(self, stamp: Optional[float]) -> Optional[np.ndarray]:
        try:
            if self.tf.can_transform(self.base_frame, self.camera_frame):
                return self.tf.lookup(self.base_frame, self.camera_frame, stamp)
            if self.tf.can_transform(self.base_frame, "head_camera_optical"):
                return self.tf.lookup(self.base_frame, "head_camera_optical", stamp)
        except TransformError:
            return None
        return None

    def bearing_in_base_horizontal(
        self, p_base: Tuple[float, float, float]
    ) -> float:
        """Angle from base +X to target in XY plane (+ = target left of forward)."""
        x, y = p_base[0], p_base[1]
        if abs(x) < 1e-6 and abs(y) < 1e-6:
            return 0.0
        return math.atan2(y, x)

    def lateral_direction_from_tf(
        self, bearing_rad: float
    ) -> Tuple[str, CenteringMode]:
        if abs(bearing_rad) <= self.cfg.bearing_deadzone_rad:
            return "none", CenteringMode.OBSERVE_ONLY
        # Target left of forward (+bearing) -> move body left (positive base y).
        if bearing_rad > 0:
            return "left", CenteringMode.CENTER_BY_BODY_LATERAL
        return "right", CenteringMode.CENTER_BY_BODY_LATERAL

    def step(
        self,
        frame: CameraFrame,
        detection: Optional[Detection],
        lidar_allows_lateral: bool = True,
        waist_preview_only: bool = True,
    ) -> CenteringStepResult:
        reasons: List[str] = []
        if self._t0 <= 0:
            self._t0 = time.time()
        if (time.time() - self._t0) > self.cfg.max_duration_s:
            return self._hold("timeout", 0, 0, reasons + ["max_duration"])
        if self._steps >= self.cfg.max_steps:
            return self._hold("max_steps", 0, 0, reasons + ["max_steps"])
        if detection is None or frame.info is None or not frame.intrinsics_trusted:
            self._confirm = 0
            return self._hold("no_detection_or_intrinsics", 0, 0, ["target_lost"])

        info: CameraInfo = frame.info
        u, v = detection.center_uv
        du, dv = pixel_error_vs_principal_point(u, v, info)
        t_bc = self._t_base_camera(frame.stamp)
        if t_bc is None:
            return self._hold("tf_missing", du, dv, ["T_base_camera_unavailable"])

        est = estimate_target_range(frame, u, v, t_bc, self.base_frame)
        bearing = None
        recommended = "none"
        mode = CenteringMode.OBSERVE_ONLY

        if est.p_base is not None:
            bearing = self.bearing_in_base_horizontal(est.p_base)
            self._bearing_history.append(bearing)
            if len(self._bearing_history) > self.cfg.oscillation_window:
                self._bearing_history.pop(0)
            if self._oscillating():
                return self._hold("oscillation", du, dv, ["bearing_oscillation"])

        pixel_centered = abs(du) <= self.cfg.pixel_deadzone_px and abs(dv) <= self.cfg.pixel_deadzone_px

        if est.depth_axis_m is not None:
            if est.depth_axis_m < self.cfg.min_depth_m or est.depth_axis_m > self.cfg.max_depth_m:
                return self._hold("depth_out_of_range", du, dv, ["depth_range"])

        if pixel_centered and est.valid:
            self._confirm += 1
        else:
            self._confirm = 0

        centered = self._confirm >= self.cfg.confirm_frames

        if centered:
            mode = CenteringMode.DOCK_FOR_MANIPULATION
        elif bearing is not None:
            lat, mode = self.lateral_direction_from_tf(bearing)
            recommended = lat
            if abs(du) <= self.cfg.pixel_deadzone_px * 2 and abs(bearing) <= self.cfg.bearing_deadzone_rad * 2:
                mode = CenteringMode.OBSERVE_ONLY
            elif not lidar_allows_lateral and mode is CenteringMode.CENTER_BY_BODY_LATERAL:
                mode = CenteringMode.SAFE_HOLD
                reasons.append("lidar_blocks_lateral")
            elif abs(du) < abs(dv) * 0.5 and waist_preview_only:
                mode = CenteringMode.CENTER_BY_WAIST_PREVIEW
                reasons.append("waist_preview_only_no_lowcmd")
        else:
            reasons.append("no_valid_3d_for_bearing")

        self._steps += 1
        safe = mode is not CenteringMode.SAFE_HOLD
        return CenteringStepResult(
            mode=mode,
            centered=centered,
            pixel_du=du,
            pixel_dv=dv,
            bearing_rad=bearing,
            p_camera=est.p_camera,
            p_base=est.p_base,
            recommended_lateral=recommended,
            safe=safe,
            reasons=reasons,
            step_index=self._steps,
        )

    def _oscillating(self) -> bool:
        if len(self._bearing_history) < 4:
            return False
        signs = [1 if b > 0 else -1 for b in self._bearing_history[-4:]]
        return len(set(signs)) > 1 and all(abs(b) > self.cfg.bearing_deadzone_rad for b in self._bearing_history[-4:])

    def _hold(self, reason: str, du: float, dv: float, reasons: List[str]) -> CenteringStepResult:
        return CenteringStepResult(
            mode=CenteringMode.SAFE_HOLD,
            centered=False,
            pixel_du=du,
            pixel_dv=dv,
            bearing_rad=None,
            p_camera=None,
            p_base=None,
            recommended_lateral="none",
            safe=False,
            reasons=reasons + [reason],
            step_index=self._steps,
        )
