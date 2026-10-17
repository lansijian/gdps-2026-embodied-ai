from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraInfo


class ProjectionStatus(str, enum.Enum):
    OK = "OK"
    INVALID_TARGET_BEHIND_CAMERA = "INVALID_TARGET_BEHIND_CAMERA"
    INVALID_DEGENERATE = "INVALID_DEGENERATE"


@dataclass
class ProjectionResult:
    u: float
    v: float
    du: float
    dv: float
    p_camera: Tuple[float, float, float]
    status: ProjectionStatus


def optical_to_base_rotation() -> np.ndarray:
    """Map ROS optical coords (x right, y down, z forward) into base (x fwd, y left, z up).

    p_base = R @ p_optical
    optical +Z (view axis) -> base +X.
    """
    return np.array(
        [
            [0.0, 0.0, 1.0],
            [-1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
        ],
        dtype=float,
    )


def make_t_base_camera(
    translation_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation_base_from_optical: Optional[np.ndarray] = None,
) -> np.ndarray:
    t = np.eye(4, dtype=float)
    t[:3, :3] = rotation_base_from_optical if rotation_base_from_optical is not None else optical_to_base_rotation()
    t[:3, 3] = np.asarray(translation_xyz, dtype=float)
    return t


def project_base_point_to_pixel(
    p_base: Tuple[float, float, float],
    t_base_camera: np.ndarray,
    info: CameraInfo,
    min_z_m: float = 0.02,
) -> ProjectionResult:
    if (not np.isfinite(p_base).all() or not np.isfinite(t_base_camera).all()
            or not np.isfinite([info.fx, info.fy, info.cx, info.cy]).all()
            or info.fx <= 0 or info.fy <= 0):
        return ProjectionResult(*(float("nan"),) * 4, (float("nan"),) * 3, ProjectionStatus.INVALID_DEGENERATE)
    t_cam_base = np.linalg.inv(t_base_camera)
    p_h = np.array([p_base[0], p_base[1], p_base[2], 1.0], dtype=float)
    p_c = t_cam_base @ p_h
    if p_c[2] <= min_z_m:
        return ProjectionResult(
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            (float(p_c[0]), float(p_c[1]), float(p_c[2])),
            ProjectionStatus.INVALID_TARGET_BEHIND_CAMERA,
        )
    u = info.fx * (p_c[0] / p_c[2]) + info.cx
    v = info.fy * (p_c[1] / p_c[2]) + info.cy
    return ProjectionResult(
        float(u),
        float(v),
        float(u - info.cx),
        float(v - info.cy),
        (float(p_c[0]), float(p_c[1]), float(p_c[2])),
        ProjectionStatus.OK,
    )


def se2_apply_y(offset_y: float, t_base_camera: np.ndarray) -> np.ndarray:
    """Robot lateral +Y in base: camera origin shifts along base Y."""
    out = t_base_camera.copy()
    out[1, 3] = float(out[1, 3]) + offset_y
    return out


def choose_lateral_direction_by_reprojection(
    p_base: Tuple[float, float, float],
    t_base_camera: np.ndarray,
    info: CameraInfo,
    trial_dy: float = 0.05,
) -> Tuple[str, float, float]:
    """Return ('left'|'right'|'none', du_before, best_du_after_candidate)."""
    base_proj = project_base_point_to_pixel(p_base, t_base_camera, info)
    if base_proj.status is not ProjectionStatus.OK:
        return "none", base_proj.du, base_proj.du
    du0 = base_proj.du
    candidates = []
    for name, dy in (("left", trial_dy), ("right", -trial_dy)):
        t2 = se2_apply_y(dy, t_base_camera)
        pr = project_base_point_to_pixel(p_base, t2, info)
        if pr.status is not ProjectionStatus.OK:
            continue
        candidates.append((name, abs(pr.du), pr.du))
    if not candidates:
        return "none", du0, du0
    candidates.sort(key=lambda x: x[1])
    best_name, _, best_du = candidates[0]
    if abs(du0) <= abs(best_du):
        return "none", du0, du0
    return best_name, du0, best_du
