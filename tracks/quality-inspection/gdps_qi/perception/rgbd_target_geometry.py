from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.math_se3 import deproject_pixel, transform_point


@dataclass
class RgbdSyncEvidence:
    rgb_stamp_sec: Optional[float]
    depth_stamp_sec: Optional[float]
    camera_info_stamp_sec: Optional[float]
    delta_rgb_depth_s: Optional[float]
    delta_rgb_info_s: Optional[float]
    same_resolution: bool
    depth_scale_confirmed: bool
    depth_aligned: bool
    intrinsics_trusted: bool
    ok: bool
    reasons: List[str] = field(default_factory=list)
    backend: str = "numpy_offline"


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
    rgb_stamp = frame.rgb_stamp_sec
    if rgb_stamp is None or not np.isfinite(rgb_stamp):
        reasons.append("rgb_header_stamp_missing_or_invalid")
    depth_stamp = frame.depth_stamp_sec
    info_stamp = frame.camera_info_stamp_sec
    delta_rd = None
    delta_ri = None
    if depth_stamp is not None and rgb_stamp is not None:
        delta_rd = abs(float(rgb_stamp) - float(depth_stamp))
        if not np.isfinite(delta_rd) or delta_rd > max_delta_s:
            reasons.append("rgb_depth_stamp_delta_exceeded")
    elif frame.depth_m is not None:
        reasons.append("depth_present_but_no_depth_stamp")
    if info_stamp is not None and rgb_stamp is not None:
        delta_ri = abs(float(rgb_stamp) - float(info_stamp))
        if not np.isfinite(delta_ri) or delta_ri > max_delta_s:
            reasons.append("rgb_camera_info_stamp_delta_exceeded")
    elif frame.info is not None:
        reasons.append("camera_info_without_stamp")
    if frame.depth_m is None:
        reasons.append("no_depth")
    same_res = False
    if frame.rgb is not None and frame.depth_m is not None:
        same_res = frame.rgb.shape[:2] == frame.depth_m.shape[:2]
        if not same_res:
            reasons.append("rgb_depth_resolution_mismatch")
        if same_res and not frame.depth_aligned_to_rgb:
            reasons.append("resolution_match_but_not_aligned")
    if frame.info is not None and frame.rgb is not None:
        if (frame.info.height, frame.info.width) != frame.rgb.shape[:2]:
            reasons.append("camera_info_rgb_resolution_mismatch")
    ok = (
        frame.intrinsics_trusted
        and frame.info is not None
        and rgb_stamp is not None
        and info_stamp is not None
        and same_res
        and depth_stamp is not None
        and frame.depth_m is not None
        and frame.depth_scale_confirmed
        and frame.depth_aligned_to_rgb
        and not reasons
    )
    return RgbdSyncEvidence(
        rgb_stamp_sec=rgb_stamp,
        depth_stamp_sec=depth_stamp,
        camera_info_stamp_sec=info_stamp,
        delta_rgb_depth_s=delta_rd,
        delta_rgb_info_s=delta_ri,
        same_resolution=same_res,
        depth_scale_confirmed=frame.depth_scale_confirmed,
        depth_aligned=frame.depth_aligned_to_rgb,
        intrinsics_trusted=frame.intrinsics_trusted,
        ok=ok,
        reasons=reasons,
    )


def try_message_filters_sync_note() -> str:
    """On-robot: use message_filters.ApproximateTimeSynchronizer (Foxy)."""
    try:
        import message_filters  # type: ignore

        return f"message_filters_available:{message_filters.__file__}"
    except ImportError:
        return "message_filters_not_installed_use_header_stamps_offline"


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
    camera_ray: Optional[Tuple[float, float, float]] = None,
) -> TargetRangeEstimate:
    reasons: List[str] = []
    if frame.info is None or not frame.intrinsics_trusted:
        return TargetRangeEstimate(
            u, v, None, None, None, None, None, None, "unknown", False, ["camera_info_untrusted"]
        )
    sync = assess_rgbd_sync(frame)
    if frame.depth_m is not None and not sync.ok:
        reasons.extend(sync.reasons or ["rgbd_sync_failed"])
    info: CameraInfo = frame.info
    if (not np.isfinite([u, v, info.fx, info.fy, info.cx, info.cy]).all()
            or info.fx <= 0 or info.fy <= 0 or not (0 <= u < info.width and 0 <= v < info.height)
            or any(abs(x) > 1e-12 for x in info.distortion)):
        return TargetRangeEstimate(u, v, None, None, None, None, None, None, "unknown", False, ["invalid_pixel_or_unrectified_intrinsics"])
    ui, vi = int(round(u)), int(round(v))
    depth_axis = None
    depth_med = None
    depth_std = None
    if frame.depth_m is not None and sync.ok:
        depth_med, depth_std, n = depth_roi_stats(frame.depth_m, ui, vi)
        if depth_med is None:
            reasons.append("depth_roi_invalid")
        else:
            depth_axis = depth_med
    elif frame.depth_m is not None:
        reasons.append("depth_unavailable_or_unaligned")

    p_cam = None
    p_base = None
    horiz = None
    if depth_axis is not None:
        if camera_ray is not None:
            ray = np.asarray(camera_ray, dtype=float)
            if ray.shape != (3,) or not np.isfinite(ray).all() or ray[2] <= 0:
                return TargetRangeEstimate(u, v, None, None, None, None, None, None, "unknown", False, ["invalid_camera_ray"])
            p = ray * (depth_axis / ray[2])  # Foxy returns unit ray; depth is axial Z.
        else:
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
