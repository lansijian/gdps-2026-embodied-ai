#!/usr/bin/env python3
"""Foxy-compatible single-message ROS2 probe (replaces `ros2 topic echo --once`)."""
from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("msg_type", help="e.g. sensor_msgs/msg/LaserScan")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    import importlib

    pkg, cls = args.msg_type.split("/msg/")
    mod = importlib.import_module(f"{pkg}.msg")
    cls_type = getattr(mod, cls)
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

    qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )

    class Once(Node):
        def __init__(self) -> None:
            super().__init__("gdps_ros2_one_shot")
            self.got = False
            self.payload = None
            self.create_subscription(cls_type, args.topic, self.cb, qos)
            self.deadline = time.time() + args.timeout

        def cb(self, msg) -> None:
            if self.got:
                return
            self.got = True
            self.payload = msg

    rclpy.init()
    node = Once()
    while rclpy.ok() and not node.got and time.time() < node.deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if not node.got:
        print("TIMEOUT", file=sys.stderr)
        node.destroy_node()
        rclpy.shutdown()
        return 2
    print(node.payload)
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
