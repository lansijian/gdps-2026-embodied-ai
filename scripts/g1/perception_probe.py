#!/usr/bin/env python3
"""Foxy-compatible pure-perception probe.

Subscribes to the raw PointCloud2 and the converted LaserScan, prints
frame_id, fields, coordinate ranges, scan rate, valid point count,
angle range, and front-sector distance computed from angle_min/angle_increment.

Read-only: publishes nothing, sends no motion commands.

Usage:
  python3 perception_probe.py [pc_topic] [scan_topic] [duration_s]
"""
from __future__ import annotations

import math
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan, PointCloud2

SENSOR_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)

FRONT_HALF_ANGLE_RAD = math.radians(30.0)
SAMPLE_LIMIT = 4000


class PerceptionProbe(Node):
    def __init__(self, pc_topic: str, scan_topic: str, duration: float) -> None:
        super().__init__("gdps_perception_probe")
        self.duration = duration

        # PointCloud2 state
        self.pc_frame: str | None = None
        self.pc_fields = None
        self.pc_height: int | None = None
        self.pc_width: int | None = None
        self.pc_count = 0
        self.pc_x_min = math.inf
        self.pc_x_max = -math.inf
        self.pc_y_min = math.inf
        self.pc_y_max = -math.inf
        self.pc_z_min = math.inf
        self.pc_z_max = -math.inf
        self.pc_dist_min = math.inf
        self.pc_dist_max = -math.inf

        # LaserScan state
        self.scan_frame: str | None = None
        self.scan_count = 0
        self.scan_first_t: float | None = None
        self.scan_last_t: float | None = None
        self.angle_min: float | None = None
        self.angle_max: float | None = None
        self.angle_increment: float | None = None
        self.range_min: float | None = None
        self.range_max: float | None = None
        self.ranges_count = 0
        self.valid_count = 0
        self.global_min: float | None = None
        self.global_max: float | None = None
        self.front_min: float | None = None
        self.front_valid = 0
        self.left_min: float | None = None
        self.right_min: float | None = None

        self.create_subscription(PointCloud2, pc_topic, self._on_pc, SENSOR_QOS)
        self.create_subscription(LaserScan, scan_topic, self._on_scan, SENSOR_QOS)
        self._t0 = time.time()
        self.create_timer(1.0, self._tick)
        self.get_logger().info(
            f"probing pc={pc_topic} scan={scan_topic} duration={duration}s"
        )

    # ---- PointCloud2 -------------------------------------------------------
    def _on_pc(self, msg: PointCloud2) -> None:
        self.pc_count += 1
        if self.pc_frame is None:
            self.pc_frame = msg.header.frame_id
            self.pc_fields = [(f.name, f.offset, f.datatype) for f in msg.fields]
            self.pc_height = msg.height
            self.pc_width = msg.width
        # Sample first bunch of points to characterize coordinate ranges.
        try:
            from sensor_msgs_py import point_cloud2

            gen = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
            for i, p in enumerate(gen):
                x, y, z = float(p[0]), float(p[1]), float(p[2])
                if i < SAMPLE_LIMIT:
                    self.pc_x_min = min(self.pc_x_min, x)
                    self.pc_x_max = max(self.pc_x_max, x)
                    self.pc_y_min = min(self.pc_y_min, y)
                    self.pc_y_max = max(self.pc_y_max, y)
                    self.pc_z_min = min(self.pc_z_min, z)
                    self.pc_z_max = max(self.pc_z_max, z)
                    d = math.hypot(x, y)
                    self.pc_dist_min = min(self.pc_dist_min, d)
                    self.pc_dist_max = max(self.pc_dist_max, d)
                else:
                    break
        except Exception as exc:
            self.get_logger().warn(f"pc decode failed: {exc}")

    # ---- LaserScan ---------------------------------------------------------
    def _on_scan(self, msg: LaserScan) -> None:
        self.scan_count += 1
        now = time.time()
        if self.scan_first_t is None:
            self.scan_first_t = now
        self.scan_last_t = now
        self.scan_frame = msg.header.frame_id
        self.angle_min = msg.angle_min
        self.angle_max = msg.angle_max
        self.angle_increment = msg.angle_increment
        self.range_min = msg.range_min
        self.range_max = msg.range_max
        self.ranges_count = len(msg.ranges)

        valid: list[float] = []
        front: list[float] = []
        left: list[float] = []
        right: list[float] = []
        for i, raw in enumerate(msg.ranges):
            if raw is None or math.isnan(raw) or math.isinf(raw):
                continue
            if raw <= msg.range_min or raw >= msg.range_max:
                continue
            angle = math.atan2(
                math.sin(msg.angle_min + i * msg.angle_increment),
                math.cos(msg.angle_min + i * msg.angle_increment),
            )
            valid.append(raw)
            if abs(angle) <= FRONT_HALF_ANGLE_RAD:
                front.append(raw)
            elif 0.15 < angle <= 1.2:
                left.append(raw)
            elif -1.2 <= angle < -0.15:
                right.append(raw)

        self.valid_count = len(valid)
        if valid:
            self.global_min = min(valid)
            self.global_max = max(valid)
        if front:
            self.front_min = min(front)
            self.front_valid = len(front)
        else:
            self.front_valid = 0
        if left:
            self.left_min = min(left)
        if right:
            self.right_min = min(right)

    # ---- Timer -------------------------------------------------------------
    def _tick(self) -> None:
        if time.time() - self._t0 >= self.duration:
            self._report()
            rclpy.shutdown()

    def _report(self) -> None:
        elapsed = time.time() - self._t0
        print("=" * 64)
        print("GDPS G1 PERCEPTION PROBE REPORT")
        print("=" * 64)
        print(f"duration        : {elapsed:.1f} s")
        print()
        print("--- PointCloud2 (raw MID-360) ---")
        print(f"frame_id        : {self.pc_frame}")
        print(f"messages        : {self.pc_count}")
        if elapsed > 0:
            print(f"approx rate     : {self.pc_count / elapsed:.1f} Hz")
        print(f"height x width  : {self.pc_height} x {self.pc_width}")
        print(f"fields          : {self.pc_fields}")
        if self.pc_x_min != math.inf:
            print(f"x range (sample): [{self.pc_x_min:.3f}, {self.pc_x_max:.3f}]")
            print(f"y range (sample): [{self.pc_y_min:.3f}, {self.pc_y_max:.3f}]")
            print(f"z range (sample): [{self.pc_z_min:.3f}, {self.pc_z_max:.3f}]")
            print(f"xy dist (sample): [{self.pc_dist_min:.3f}, {self.pc_dist_max:.3f}] m")
        print()
        print("--- LaserScan (/scan from pointcloud_to_laserscan) ---")
        print(f"frame_id        : {self.scan_frame}")
        print(f"messages        : {self.scan_count}")
        if (
            self.scan_count > 1
            and self.scan_last_t is not None
            and self.scan_first_t is not None
            and self.scan_last_t > self.scan_first_t
        ):
            rate = (self.scan_count - 1) / (self.scan_last_t - self.scan_first_t)
            print(f"measured rate   : {rate:.1f} Hz")
        print(f"angle_min       : {self.angle_min}")
        print(f"angle_max       : {self.angle_max}")
        print(f"angle_increment : {self.angle_increment}")
        print(f"range_min       : {self.range_min}")
        print(f"range_max       : {self.range_max}")
        print(f"ranges_count    : {self.ranges_count}")
        print(f"valid_count     : {self.valid_count}")
        if self.global_min is not None:
            print(f"global_min      : {self.global_min:.3f} m")
            print(f"global_max      : {self.global_max:.3f} m")
        # Front sector computed from angle parameters, NOT array middle.
        if self.angle_min is not None and self.angle_increment:
            front_idx = int(round((0.0 - self.angle_min) / self.angle_increment))
            print(f"front(0rad) idx : {front_idx} / {self.ranges_count}")
        print(f"front sector    : +/- {math.degrees(FRONT_HALF_ANGLE_RAD):.0f} deg")
        print(f"front valid     : {self.front_valid}")
        if self.front_min is not None:
            print(f"FRONT_MIN       : {self.front_min:.3f} m")
        else:
            print("FRONT_MIN       : N/A (no returns in front sector)")
        if self.left_min is not None:
            print(f"left_min        : {self.left_min:.3f} m")
        if self.right_min is not None:
            print(f"right_min       : {self.right_min:.3f} m")
        print("=" * 64)


def main() -> None:
    rclpy.init()
    pc_topic = sys.argv[1] if len(sys.argv) > 1 else "/utlidar/cloud_livox_mid360"
    scan_topic = sys.argv[2] if len(sys.argv) > 2 else "/scan"
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    node = PerceptionProbe(pc_topic, scan_topic, duration)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node._report()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
