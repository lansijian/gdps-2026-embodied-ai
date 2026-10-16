"""Pure PointCloud2 -> LaserScan conversion logic (no ROS dependency).

Separated from the ROS 2 node so it can be unit-tested on Windows without rclpy.
The ROS node decodes PointCloud2 into (x, y, z) tuples and calls convert_points().

Design choices (G1 EDU on-site):
- Height band filters ground points and over-head points.
- robot_radius removes points that hit the robot body (self-occlusion).
- Each angular bin keeps the minimum range (closest obstacle).
- Empty bins are set to +inf (LaserScan convention: no return).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class PCLScanParams:
    angle_min: float = -math.pi
    angle_max: float = math.pi
    angle_increment: float = math.pi / 180.0  # 1 degree
    range_min: float = 0.10
    range_max: float = 10.0
    min_height: float = 0.05   # ignore points below this (ground)
    max_height: float = 1.00   # ignore points above this (over-head)
    robot_radius: float = 0.35  # ignore points inside robot footprint (+margin)


@dataclass
class ScanResult:
    ranges: list[float]
    angle_min: float
    angle_max: float
    angle_increment: float
    range_min: float
    range_max: float
    n_valid_points: int


def convert_points(points, params: PCLScanParams) -> ScanResult:
    """Convert an iterable of (x, y, z) points to a LaserScan ranges array.

    Pure-Python reference implementation (used by unit tests).
    points: iterable of (x, y, z) floats (sensor frame, x forward).
    Returns ScanResult with ranges list.
    """
    n = int(math.ceil((params.angle_max - params.angle_min) / params.angle_increment))
    if n <= 0:
        n = 1
    ranges = [math.inf] * n
    n_valid = 0

    r2 = params.robot_radius * params.robot_radius
    range_min_sq = params.range_min * params.range_min
    range_max_sq = params.range_max * params.range_max

    for p in points:
        x, y, z = float(p[0]), float(p[1]), float(p[2])
        if math.isnan(x) or math.isnan(y) or math.isnan(z):
            continue
        if math.isinf(x) or math.isinf(y) or math.isinf(z):
            continue
        # Height band
        if z < params.min_height or z > params.max_height:
            continue
        rho_sq = x * x + y * y
        # Self-occlusion: points inside robot footprint (use <= to catch boundary)
        if rho_sq <= r2:
            continue
        # Range band
        if rho_sq < range_min_sq or rho_sq > range_max_sq:
            continue
        angle = math.atan2(y, x)
        if angle < params.angle_min or angle > params.angle_max:
            continue
        idx = int((angle - params.angle_min) / params.angle_increment)
        if idx < 0 or idx >= n:
            continue
        rho = math.sqrt(rho_sq)
        if rho < ranges[idx]:
            ranges[idx] = rho
        n_valid += 1

    return ScanResult(
        ranges=ranges,
        angle_min=params.angle_min,
        angle_max=params.angle_min + (n - 1) * params.angle_increment,
        angle_increment=params.angle_increment,
        range_min=params.range_min,
        range_max=params.range_max,
        n_valid_points=n_valid,
    )


def convert_points_raw(
    data: bytes,
    point_step: int,
    n_points: int,
    params: PCLScanParams,
    x_offset: int = 0,
    y_offset: int = 4,
    z_offset: int = 8,
) -> ScanResult:
    """Numpy-vectorized PointCloud2 -> LaserScan conversion.

    Reads x/y/z float32 directly from the raw byte buffer at the given field
    offsets. This avoids the overhead of sensor_msgs_py.read_points generator
    and per-point Python loops, processing ~20k points in <2ms.

    Args:
        data: raw PointCloud2 data bytes.
        point_step: bytes per point (e.g. 22 for Livox MID-360).
        n_points: number of points (height * width).
        params: conversion parameters.
        x_offset, y_offset, z_offset: byte offsets of x/y/z float32 fields.
    """
    n = int(math.ceil((params.angle_max - params.angle_min) / params.angle_increment))
    if n <= 0:
        n = 1

    expected_bytes = n_points * point_step
    if len(data) < expected_bytes:
        n_points = len(data) // point_step
        if n_points <= 0:
            return ScanResult(
                ranges=[math.inf] * n,
                angle_min=params.angle_min,
                angle_max=params.angle_min + (n - 1) * params.angle_increment,
                angle_increment=params.angle_increment,
                range_min=params.range_min,
                range_max=params.range_max,
                n_valid_points=0,
            )

    raw = np.frombuffer(data, dtype=np.uint8)[:n_points * point_step]
    raw = raw.reshape(n_points, point_step)

    x = raw[:, x_offset:x_offset + 4].view(np.float32).reshape(n_points)
    y = raw[:, y_offset:y_offset + 4].view(np.float32).reshape(n_points)
    z = raw[:, z_offset:z_offset + 4].view(np.float32).reshape(n_points)

    # Drop NaN / Inf
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x = x[finite]
    y = y[finite]
    z = z[finite]

    # Height band
    in_h = (z >= params.min_height) & (z <= params.max_height)
    x = x[in_h]
    y = y[in_h]
    if x.size == 0:
        return _empty_result(n, params)

    # Self-occlusion (use <= so boundary points at robot_radius are excluded)
    rho_sq = x * x + y * y
    r2 = params.robot_radius * params.robot_radius
    not_self = rho_sq > r2
    x = x[not_self]
    y = y[not_self]
    rho_sq = rho_sq[not_self]
    if x.size == 0:
        return _empty_result(n, params)

    # Range band
    range_min_sq = params.range_min * params.range_min
    range_max_sq = params.range_max * params.range_max
    in_range = (rho_sq >= range_min_sq) & (rho_sq <= range_max_sq)
    x = x[in_range]
    y = y[in_range]
    rho_sq = rho_sq[in_range]
    if x.size == 0:
        return _empty_result(n, params)

    # Angle binning
    angles = np.arctan2(y, x)
    in_angle = (angles >= params.angle_min) & (angles <= params.angle_max)
    x = x[in_angle]
    y = y[in_angle]
    rho_sq = rho_sq[in_angle]
    angles = angles[in_angle]
    if x.size == 0:
        return _empty_result(n, params)

    idx = ((angles - params.angle_min) / params.angle_increment).astype(np.intp)
    np.clip(idx, 0, n - 1, out=idx)
    rho = np.sqrt(rho_sq)

    ranges = np.full(n, np.inf, dtype=np.float32)
    np.minimum.at(ranges, idx, rho)

    return ScanResult(
        ranges=ranges.tolist(),
        angle_min=params.angle_min,
        angle_max=params.angle_min + (n - 1) * params.angle_increment,
        angle_increment=params.angle_increment,
        range_min=params.range_min,
        range_max=params.range_max,
        n_valid_points=int(x.size),
    )


def _empty_result(n: int, params: PCLScanParams) -> ScanResult:
    return ScanResult(
        ranges=[math.inf] * n,
        angle_min=params.angle_min,
        angle_max=params.angle_min + (n - 1) * params.angle_increment,
        angle_increment=params.angle_increment,
        range_min=params.range_min,
        range_max=params.range_max,
        n_valid_points=0,
    )
