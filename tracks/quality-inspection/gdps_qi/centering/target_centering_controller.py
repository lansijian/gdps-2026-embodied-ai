from __future__ import annotations

import enum
import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.perception.camera_geometry import (
    ProjectionStatus,
    choose_lateral_direction_by_reprojection,
    project_base_point_to_pixel,
)
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
    max_observe_frames: int = 40
    max_motion_steps: int = 12
    max_duration_s: float = 120.0
    max_lateral_step_m: float = 0.08
    oscillation_window: int = 6
    min_depth_m: float = 0.25
    max_depth_m: float = 1.8
    trial_dy_m: float = 0.05


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
    observe_frames: int = 0
    motion_steps: int = 0
    locked_target_id: str = ""


@dataclass
class TargetCenteringController:
    tf: TransformManager
    base_frame: str = "robot_center"
    camera_frame: str = "camera_color_optical_frame"
    cfg: CenteringConfig = field(default_factory=CenteringConfig)
    _confirm: int = 0
    _observe_frames: int = 0
    _motion_steps: int = 0
    _t0_mono: float = 0.0
    _locked_target_id: str = ""
    _last_abs_du: Optional[float] = None
    _last_lateral: str = "none"
    _halt_reason: str = ""
    _last_frame_stamp: Optional[float] = None
    _bearing_history: List[float] = field(default_factory=list)

    def reset(self) -> None:
        self._confirm = 0
        self._halt_reason = ""
        self._last_frame_stamp = None
        self._observe_frames = 0
        self._motion_steps = 0
        self._t0_mono = time.monotonic()
        self._locked_target_id = ""
        self._last_abs_du = None
        self._last_lateral = "none"
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

    def bearing_in_base_horizontal(self, p_base: Tuple[float, float, float]) -> float:
        x, y = p_base[0], p_base[1]
        if abs(x) < 1e-6 and abs(y) < 1e-6:
            return 0.0
        return math.atan2(y, x)

    def step(
        self,
        frame: CameraFrame,
        detection: Optional[Detection],
        lidar_allows_lateral: bool = True,
        waist_preview_only: bool = True,
        workspace_ok: bool = False,
        moved_since_last: bool = False,
    ) -> CenteringStepResult:
        reasons: List[str] = []
        if self._halt_reason:
            return self._hold(self._halt_reason, 0, 0, ["reset_required"])
        if self._last_frame_stamp is not None and frame.stamp <= self._last_frame_stamp:
            return self._hold("non_increasing_frame_stamp", 0, 0, [])
        self._last_frame_stamp = frame.stamp
        self._observe_frames += 1
        if moved_since_last:
            self._motion_steps += 1
        if self._t0_mono <= 0:
            self._t0_mono = time.monotonic()
        if (time.monotonic() - self._t0_mono) > self.cfg.max_duration_s:
            return self._hold("timeout", 0, 0, reasons + ["max_duration"])
        if self._observe_frames > self.cfg.max_observe_frames:
            return self._hold("max_observe_frames", 0, 0, reasons + ["max_observe_frames"])
        if self._motion_steps > self.cfg.max_motion_steps:
            return self._hold("max_motion_steps", 0, 0, reasons + ["max_motion_steps"])
        if detection is None or frame.info is None or not frame.intrinsics_trusted:
            self._confirm = 0
            return self._hold("no_detection_or_intrinsics", 0, 0, ["target_lost"])

        tid = str(detection.object_id or "")
        if not tid:
            return self._hold("target_id_missing", 0, 0, ["stable_target_id_required"])
        if self._locked_target_id and tid != self._locked_target_id:
            self._confirm = 0
            return self._hold("target_id_changed", 0, 0, ["target_id_mismatch", tid])
        if not self._locked_target_id:
            self._locked_target_id = tid

        info: CameraInfo = frame.info
        u, v = detection.center_uv
        du, dv = pixel_error_vs_principal_point(u, v, info)
        t_bc = self._t_base_camera(frame.stamp)
        if t_bc is None:
            return self._hold("tf_missing", du, dv, ["T_base_camera_unavailable"])

        est = estimate_target_range(frame, u, v, t_bc, self.base_frame)
        if not est.valid:
            return self._hold("range_invalid", du, dv, est.reasons)
        if est.p_camera is not None and est.p_camera[2] <= 0.02:
            return self._hold("behind_camera", du, dv, ["INVALID_TARGET_BEHIND_CAMERA"])
        if est.p_base is not None:
            pr = project_base_point_to_pixel(est.p_base, t_bc, info)
            if pr.status is ProjectionStatus.INVALID_TARGET_BEHIND_CAMERA:
                return self._hold("behind_camera", du, dv, ["INVALID_TARGET_BEHIND_CAMERA"])

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

        pixel_centered = abs(du) <= self.cfg.pixel_deadzone_px

        if est.depth_axis_m is not None:
            if est.depth_axis_m < self.cfg.min_depth_m or est.depth_axis_m > self.cfg.max_depth_m:
                return self._hold("depth_out_of_range", du, dv, ["depth_range"])

        if moved_since_last and self._last_abs_du is not None:
            if abs(du) > self._last_abs_du + 2.0:
                return self._hold("error_increased_after_motion", du, dv, ["error_grew"])

        if pixel_centered and est.valid:
            self._confirm += 1
        else:
            self._confirm = 0

        centered = self._confirm >= self.cfg.confirm_frames

        if centered and not workspace_ok:
            mode = CenteringMode.OBSERVE_ONLY
            reasons.append("centered_but_workspace_not_ready")
        elif centered:
            mode = CenteringMode.DOCK_FOR_MANIPULATION
        elif est.p_base is not None:
            if self._motion_steps >= self.cfg.max_motion_steps:
                return self._hold("max_motion_steps", du, dv, [])
            lat, du0, _ = choose_lateral_direction_by_reprojection(
                est.p_base, t_bc, info, self.cfg.trial_dy_m
            )
            recommended = lat
            if lat == "none":
                mode = CenteringMode.OBSERVE_ONLY
            elif not lidar_allows_lateral:
                return self._hold("lidar_blocks_lateral", du, dv, [])
            elif abs(du) < abs(dv) * 0.5 and waist_preview_only:
                mode = CenteringMode.CENTER_BY_WAIST_PREVIEW
                reasons.append("waist_unavailable_without_trusted_joints_urdf_fk_direction_limits_preview_only")
            else:
                mode = CenteringMode.CENTER_BY_BODY_LATERAL
            if self._last_lateral not in ("none", "") and lat not in ("none", self._last_lateral):
                if abs(du) >= (self._last_abs_du or 0):
                    return self._hold("direction_reversal_no_gain", du, dv, ["wrong_direction"])
            self._last_lateral = lat
        else:
            reasons.append("no_valid_3d_for_bearing")

        self._last_abs_du = abs(du)
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
            step_index=self._observe_frames,
            observe_frames=self._observe_frames,
            motion_steps=self._motion_steps,
            locked_target_id=self._locked_target_id,
        )

    def _oscillating(self) -> bool:
        if len(self._bearing_history) < 4:
            return False
        signs = [1 if b > 0 else -1 for b in self._bearing_history[-4:]]
        return len(set(signs)) > 1 and all(abs(b) > self.cfg.bearing_deadzone_rad for b in self._bearing_history[-4:])

    def _hold(self, reason: str, du: float, dv: float, reasons: List[str]) -> CenteringStepResult:
        self._halt_reason = reason
        self._confirm = 0
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
            step_index=self._observe_frames,
            observe_frames=self._observe_frames,
            motion_steps=self._motion_steps,
            locked_target_id=self._locked_target_id,
        )
