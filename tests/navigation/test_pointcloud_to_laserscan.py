"""Unit tests for PointCloud2 -> LaserScan pure conversion logic.

Runs on Windows without rclpy (shared.navigation.perception.pointcloud_to_laserscan
has no ROS dependency).
"""

from __future__ import annotations

import math

import pytest

from shared.navigation.perception.pointcloud_to_laserscan import (
    PCLScanParams,
    convert_points,
)


@pytest.fixture
def params() -> PCLScanParams:
    return PCLScanParams(
        angle_min=-math.pi,
        angle_max=math.pi,
        angle_increment=math.pi / 180.0,
        range_min=0.10,
        range_max=10.0,
        min_height=0.05,
        max_height=1.00,
        robot_radius=0.30,
    )


def test_point_straight_ahead_landed_in_center_bin(params: PCLScanParams) -> None:
    # A point 2.0 m directly ahead (x=2, y=0) at z=0.5
    result = convert_points([(2.0, 0.0, 0.5)], params)
    center = len(result.ranges) // 2
    assert result.ranges[center] == pytest.approx(2.0, abs=0.05)
    # all other bins should be inf
    for i, r in enumerate(result.ranges):
        if i == center:
            continue
        assert math.isinf(r)


def test_height_band_filters_ground_and_overhead(params: PCLScanParams) -> None:
    # z below min_height (ground) and above max_height (overhead) -> ignored
    pts = [(2.0, 0.0, 0.01), (2.0, 0.0, 1.5)]
    result = convert_points(pts, params)
    assert result.n_valid_points == 0
    assert all(math.isinf(r) for r in result.ranges)


def test_robot_self_occlusion_filtered(params: PCLScanParams) -> None:
    # Point inside robot radius (0.25 m < 0.30) -> ignored
    pts = [(0.2, 0.0, 0.5)]
    result = convert_points(pts, params)
    assert result.n_valid_points == 0


def test_range_band_filtered(params: PCLScanParams) -> None:
    # Too close (0.05 < range_min 0.10) and too far (15 > range_max 10) -> ignored
    pts = [(0.05, 0.0, 0.5), (15.0, 0.0, 0.5)]
    result = convert_points(pts, params)
    assert result.n_valid_points == 0


def test_angular_binning_places_points_correctly(params: PCLScanParams) -> None:
    # Point at 90 deg (left): x=0, y=3 -> angle = pi/2
    pts = [(0.0, 3.0, 0.5)]
    result = convert_points(pts, params)
    expected_idx = int((math.pi / 2 - params.angle_min) / params.angle_increment)
    assert result.ranges[expected_idx] == pytest.approx(3.0, abs=0.05)


def test_closest_point_wins_per_bin(params: PCLScanParams) -> None:
    # Two points straight ahead: one at 3m, one at 1.5m -> bin holds 1.5
    pts = [(3.0, 0.0, 0.5), (1.5, 0.0, 0.5)]
    result = convert_points(pts, params)
    center = len(result.ranges) // 2
    assert result.ranges[center] == pytest.approx(1.5, abs=0.05)
    assert result.n_valid_points == 2


def test_nan_and_inf_points_skipped(params: PCLScanParams) -> None:
    pts = [(float("nan"), 0.0, 0.5), (float("inf"), 0.0, 0.5), (2.0, 0.0, 0.5)]
    result = convert_points(pts, params)
    assert result.n_valid_points == 1
    center = len(result.ranges) // 2
    assert result.ranges[center] == pytest.approx(2.0, abs=0.05)


def test_empty_cloud_all_inf(params: PCLScanParams) -> None:
    result = convert_points([], params)
    assert result.n_valid_points == 0
    assert all(math.isinf(r) for r in result.ranges)
    assert len(result.ranges) == int(
        math.ceil((params.angle_max - params.angle_min) / params.angle_increment)
    )


def test_scan_metadata_matches_params(params: PCLScanParams) -> None:
    result = convert_points([(1.0, 0.0, 0.5)], params)
    assert result.angle_min == params.angle_min
    assert result.angle_increment == params.angle_increment
    assert result.range_min == params.range_min
    assert result.range_max == params.range_max
    # angle_max should be angle_min + (n-1)*increment
    assert result.angle_max == pytest.approx(
        params.angle_min + (len(result.ranges) - 1) * params.angle_increment
    )
