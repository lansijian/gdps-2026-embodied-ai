"""PointCloud2 (Livox MID-360) -> LaserScan conversion node for G1 EDU.

Subscribes to /utlidar/cloud_livox_mid360 (BEST_EFFORT), applies height band,
robot self-occlusion, and angular binning, publishes /scan (LaserScan).

The pure conversion logic lives in shared.navigation.perception.pointcloud_to_laserscan
and is unit-tested on Windows without rclpy.
"""

from __future__ import annotations

from .repo_path import ensure_repo_on_path


def main() -> None:
    ensure_repo_on_path()
    import math

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan, PointCloud2

    from shared.navigation.perception.pointcloud_to_laserscan import (
        PCLScanParams,
        convert_points_raw,
    )

    sensor_qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )

    class PointCloudToLaserScan(Node):
        def __init__(self) -> None:
            super().__init__("gdps_pointcloud_to_laserscan")
            self.declare_parameter("input_topic", "/utlidar/cloud_livox_mid360")
            self.declare_parameter("output_topic", "/scan")
            self.declare_parameter("angle_min", -math.pi)
            self.declare_parameter("angle_max", math.pi)
            self.declare_parameter("angle_increment", math.pi / 180.0)
            self.declare_parameter("range_min", 0.10)
            self.declare_parameter("range_max", 10.0)
            self.declare_parameter("min_height", 0.05)
            self.declare_parameter("max_height", 1.00)
            self.declare_parameter("robot_radius", 0.35)

            in_topic = str(self.get_parameter("input_topic").value)
            out_topic = str(self.get_parameter("output_topic").value)
            self.params = PCLScanParams(
                angle_min=float(self.get_parameter("angle_min").value),
                angle_max=float(self.get_parameter("angle_max").value),
                angle_increment=float(self.get_parameter("angle_increment").value),
                range_min=float(self.get_parameter("range_min").value),
                range_max=float(self.get_parameter("range_max").value),
                min_height=float(self.get_parameter("min_height").value),
                max_height=float(self.get_parameter("max_height").value),
                robot_radius=float(self.get_parameter("robot_radius").value),
            )
            self.pub = self.create_publisher(LaserScan, out_topic, 10)
            self.create_subscription(PointCloud2, in_topic, self._cb, sensor_qos)
            self.get_logger().info(
                f"pc2->scan {in_topic} -> {out_topic} "
                f"height=[{self.params.min_height:.2f},{self.params.max_height:.2f}] "
                f"robot_r={self.params.robot_radius:.2f}"
            )

        def _cb(self, msg: PointCloud2) -> None:
            n_points = msg.height * msg.width
            result = convert_points_raw(
                bytes(msg.data),
                msg.point_step,
                n_points,
                self.params,
            )
            scan = LaserScan()
            # Use the original point cloud timestamp, not node clock.
            scan.header.stamp = msg.header.stamp
            scan.header.frame_id = msg.header.frame_id
            scan.angle_min = result.angle_min
            scan.angle_max = result.angle_max
            scan.angle_increment = result.angle_increment
            # MID-360 spins at ~10 Hz; time between scans ~0.1s.
            scan.time_increment = 0.0
            scan.scan_time = 0.1
            scan.range_min = result.range_min
            scan.range_max = result.range_max
            scan.ranges = result.ranges
            scan.intensities = []
            self.pub.publish(scan)

    rclpy.init()
    node = PointCloudToLaserScan()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
