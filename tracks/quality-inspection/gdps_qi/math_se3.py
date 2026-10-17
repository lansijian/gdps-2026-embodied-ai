from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

import numpy as np

Vec3 = Tuple[float, float, float]
Mat4 = np.ndarray


def quat_normalize(q: Sequence[float]) -> np.ndarray:
    v = np.asarray(q, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("zero quaternion")
    return v / n


def quat_to_rot(q_xyzw: Sequence[float]) -> np.ndarray:
    x, y, z, w = quat_normalize(q_xyzw)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def rot_to_quat(r: np.ndarray) -> np.ndarray:
    m = np.asarray(r, dtype=float).reshape(3, 3)
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return quat_normalize((x, y, z, w))


def make_transform(
    rotation: np.ndarray, translation: Sequence[float]
) -> Mat4:
    t = np.eye(4, dtype=float)
    t[:3, :3] = rotation
    t[:3, 3] = np.asarray(translation, dtype=float).reshape(3)
    return t


def transform_from_pose(
    position: Sequence[float], orientation_xyzw: Sequence[float]
) -> Mat4:
    return make_transform(quat_to_rot(orientation_xyzw), position)


def invert_transform(t_ab: Mat4) -> Mat4:
    r = t_ab[:3, :3]
    p = t_ab[:3, 3]
    t_ba = np.eye(4, dtype=float)
    t_ba[:3, :3] = r.T
    t_ba[:3, 3] = -r.T @ p
    return t_ba


def compose_transform(t_a_b: Mat4, t_b_c: Mat4) -> Mat4:
    return t_a_b @ t_b_c


def transform_point(t_a_b: Mat4, p_b: Sequence[float]) -> np.ndarray:
    p = np.asarray(p_b, dtype=float).reshape(3)
    hom = np.array([p[0], p[1], p[2], 1.0])
    out = t_a_b @ hom
    return out[:3]


def identity_error(t: Mat4) -> float:
    i = np.eye(4)
    return float(np.linalg.norm(t - i))


def chain_transforms(transforms: Iterable[Mat4]) -> Mat4:
    out = np.eye(4, dtype=float)
    for t in transforms:
        out = compose_transform(out, t)
    return out


def plane_ray_intersection(
    ray_origin: Sequence[float],
    ray_dir: Sequence[float],
    plane_point: Sequence[float],
    plane_normal: Sequence[float],
) -> Tuple[bool, np.ndarray]:
    o = np.asarray(ray_origin, dtype=float)
    d = np.asarray(ray_dir, dtype=float)
    n = np.asarray(plane_normal, dtype=float)
    n_norm = np.linalg.norm(n)
    if n_norm < 1e-9:
        return False, o
    n = n / n_norm
    denom = float(np.dot(n, d))
    if abs(denom) < 1e-9:
        return False, o
    lam = -float(np.dot(n, o - np.asarray(plane_point, dtype=float))) / denom
    if lam < 0:
        return False, o
    return True, o + lam * d


def deproject_pixel(
    u: float,
    v: float,
    depth_m: float,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> np.ndarray:
    x = (u - cx) / fx * depth_m
    y = (v - cy) / fy * depth_m
    z = depth_m
    return np.array([x, y, z], dtype=float)


def undistort_normalized(u: float, v: float, fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.array([(u - cx) / fx, (v - cy) / fy, 1.0], dtype=float)


def solve_pnp_planar(
    object_points_table: Sequence[Sequence[float]],
    image_points_uv: Sequence[Sequence[float]],
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> Mat4:
    """Minimal PnP for >=3 coplanar points using DLT + SVD (no OpenCV dependency)."""
    if len(object_points_table) < 3 or len(image_points_uv) < 3:
        raise ValueError("need at least 3 point pairs")
    a_rows: List[List[float]] = []
    for (x, y, z), (u, v) in zip(object_points_table, image_points_uv):
        nx = (u - cx) / fx
        ny = (v - cy) / fy
        a_rows.append([x, y, z, 1, 0, 0, 0, 0, -nx * x, -nx * y, -nx * z, -nx])
        a_rows.append([0, 0, 0, 0, x, y, z, 1, -ny * x, -ny * y, -ny * z, -ny])
    a = np.asarray(a_rows, dtype=float)
    _, _, vt = np.linalg.svd(a)
    p = vt[-1].reshape(3, 4)
    r = p[:, :3]
    u, _, vt_r = np.linalg.svd(r)
    r_ortho = u @ vt_r
    if np.linalg.det(r_ortho) < 0:
        r_ortho[:, 2] *= -1
    t = p[:, 3]
    return make_transform(r_ortho, t)
