"""Broadcast odom->base TF from a configurable Odometry topic.

Default topic is empty / must be set. Do not assume /dog_odom exists on G1 EDU.
"""

from __future__ import annotations


def main() -> None:
    import rclpy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from tf2_ros import TransformBroadcaster

    class OdomTf(Node):
        def __init__(self) -> None:
            super().__init__("gdps_odom_tf")
            self.declare_parameter("odom_topic", "")
            topic = str(self.get_parameter("odom_topic").value)
            if not topic:
                raise RuntimeError(
                    "odom_topic is empty. Set it after ros2 topic list confirms odometry."
                )
            self._tf = TransformBroadcaster(self)
            self.create_subscription(Odometry, topic, self._cb, 10)
            self.get_logger().info(f"TF from odom topic {topic} (site-verified name required)")

        def _cb(self, msg: Odometry) -> None:
            t = TransformStamped()
            t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id = msg.header.frame_id
            t.child_frame_id = msg.child_frame_id
            t.transform.translation.x = msg.pose.pose.position.x
            t.transform.translation.y = msg.pose.pose.position.y
            t.transform.translation.z = msg.pose.pose.position.z
            t.transform.rotation = msg.pose.pose.orientation
            self._tf.sendTransform(t)

    rclpy.init()
    node = OdomTf()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
