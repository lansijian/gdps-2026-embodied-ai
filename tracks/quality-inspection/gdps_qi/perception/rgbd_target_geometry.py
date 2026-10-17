from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.math_se3 import deproject_pixel, transform_point


@dataclass
class RgbdSyncEvidence:
    rgb_stamp: float
    depth_stamp: Optional[float]
    delta_s: Optional[float]
    same_resolution: bool
    depth_scale_confirmed: bool
    depth_aligned: bool
    intrinsics_trusted: bool
    ok: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class TargetRangeEstimate:
    u: float
    v: float
    depth_axis_m: Optional[float]
    depth_median_m: Optional[float]
    depth_std_m: Optional[float]
    p_camera: Optional[Tuple[float, float, float]]
    p_base: Optional[Tuple[float, float, float]]
    horizontal_range_base_m: Optional[float]
    source: str
    valid: bool
    reasons: List[str] = field(default_factory=list)


def assess_rgbd_sync(frame: CameraFrame, max_delta_s: float = 0.05) -> RgbdSyncEvidence:
    reasons: List[str] = []
    depth_stamp = frame.stamp if frame.depth_m is not None else None
    delta = None
    if frame.rgb is not None and frame.depth_m is not None:
        delta = 0.0
        if delta > max_delta_s:
            reasons.append("stamp_delta_exceeded")
    elif frame.depth_m is None:
        reasons.append("no_depth")
    same_res = False
    if frame.rgb is not None and frame.depth_m is not None:
        same_res = frame.rgb.shape[:2] == frame.depth_m.shape[:2]
        if same_res and not frame.depth_aligned_to_rgb:
            reasons.append("resolution_match_but_not_aligned")
    ok = (
        frame.intrinsics_trusted
        and frame.info is not None
        and (frame.depth_m is None or (frame.depth_scale_confirmed and frame.depth_aligned_to_rgb))
        and not reasons
    )
    return RgbdSyncEvidence(
        rgb_stamp=frame.stamp,
        depth_stamp=depth_stamp,
        delta_s=delta,
        same_resolution=same_res,
        depth_scale_confirmed=frame.depth_scale_confirmed,
        depth_aligned=frame.depth_aligned_to_rgb,
        intrinsics_trusted=frame.intrinsics_trusted,
        ok=ok,
        reasons=reasons,
    )


def depth_roi_stats(
    depth_m: np.ndarray,
    u: int,
    v: int,
    half_size: int = 3,
    valid_min: float = 0.05,
    valid_max: float = 4.0,
) -> Tuple[Optional[float], Optional[float], int]:
    h, w = depth_m.shape
    u0 = max(0, u - half_size)
    u1 = min(w, u + half_size + 1)
    v0 = max(0, v - half_size)
    v1 = min(h, v + half_size + 1)
    patch = depth_m[v0:v1, u0:u1].astype(np.float64)
    valid = patch[(patch > valid_min) & (patch < valid_max) & np.isfinite(patch)]
    if valid.size < 3:
        return None, None, int(valid.size)
    return float(np.median(valid)), float(np.std(valid)), int(valid.size)


def estimate_target_range(
    frame: CameraFrame,
    u: float,
    v: float,
    t_base_camera: Optional[np.ndarray] = None,
    base_frame: str = "robot_center",
) -> TargetRangeEstimate:
    reasons: List[str] = []
    if frame.info is None or not frame.intrinsics_trusted:
        return TargetRangeEstimate(
            u, v, None, None, None, None, None, None, "unknown", False, ["camera_info_untrusted"]
        )
    info: CameraInfo = frame.info
    ui, vi = int(round(u)), int(round(v))
    depth_axis = None
    depth_med = None
    depth_std = None
    if frame.depth_m is not None and frame.depth_scale_confirmed and frame.depth_aligned_to_rgb:
        depth_med, depth_std, n = depth_roi_stats(frame.depth_m, ui, vi)
        if depth_med is None:
            reasons.append("depth_roi_invalid")
        else:
            depth_axis = depth_med
    else:
        reasons.append("depth_unavailable_or_unaligned")

    p_cam = None
    p_base = None
    horiz = None
    if depth_axis is not None:
        p = deproject_pixel(u, v, depth_axis, info.fx, info.fy, info.cx, info.cy)
        p_cam = (float(p[0]), float(p[1]), float(p[2]))
        if t_base_camera is not None:
            pb = transform_point(t_base_camera, p)
            p_base = (float(pb[0]), float(pb[1]), float(pb[2]))
            horiz = float(np.hypot(pb[0], pb[1]))
    source = "rgbd_deproject" if p_cam else "unknown"
    valid = p_cam is not None and not reasons
    return TargetRangeEstimate(
        u=u,
        v=v,
        depth_axis_m=depth_axis,
        depth_median_m=depth_med,
        depth_std_m=depth_std,
        p_camera=p_cam,
        p_base=p_base,
        horizontal_range_base_m=horiz,
        source=source,
        valid=valid,
        reasons=reasons,
    )


def pixel_error_vs_principal_point(u: float, v: float, info: CameraInfo) -> Tuple[float, float]:
    return float(u - info.cx), float(v - info.cy)
