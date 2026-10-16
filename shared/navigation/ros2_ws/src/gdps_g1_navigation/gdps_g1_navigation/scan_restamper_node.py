"""Republish LaserScan with ROS clock stamps.

Idea adapted from guruadp/unitree-g1-slam-nav scan_restamper.py
(Apache-2.0, commit b9a1fbd): Livox hardware clocks can disagree with ROS time.
"""

from __future__ import annotations


def main() -> None:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan

    sensor_qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )

    class ScanRestamper(Node):
        def __init__(self) -> None:
            super().__init__("gdps_scan_restamper")
            self.declare_parameter("input_topic", "/scan_raw")
            self.declare_parameter("output_topic", "/scan")
            in_topic = self.get_parameter("input_topic").value
            out_topic = self.get_parameter("output_topic").value
            self.pub = self.create_publisher(LaserScan, out_topic, 10)
            self.create_subscription(LaserScan, in_topic, self._cb, sensor_qos)
            self.get_logger().info(f"restamp {in_topic} -> {out_topic}")

        def _cb(self, msg: LaserScan) -> None:
            msg.header.stamp = self.get_clock().now().to_msg()
            self.pub.publish(msg)

    rclpy.init()
    node = ScanRestamper()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
