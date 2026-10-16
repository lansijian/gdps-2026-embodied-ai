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


@dataclass
class PCLScanParams:
    angle_min: float = -math.pi
    angle_max: float = math.pi
    angle_increment: float = math.pi / 180.0  # 1 degree
    range_min: float = 0.10
    range_max: float = 10.0
    min_height: float = 0.05   # ignore points below this (ground)
    max_height: float = 1.00   # ignore points above this (over-head)
    robot_radius: float = 0.30  # ignore points inside robot footprint


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

    points: iterable of (x, y, z) floats (sensor frame, x forward).
    Returns ScanResult with ranges list (length = ceil((angle_max-angle_min)/increment)).
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
        # Self-occlusion: points inside robot footprint
        if rho_sq < r2:
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
