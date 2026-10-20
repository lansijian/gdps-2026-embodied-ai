#!/usr/bin/env python3
"""Reference: supplied unitree_g1_ros2-main.zip g1_ros2_bridge/odom_bridge.py.

Native ROS odometry by default; optional SDK measured SportModeState adapter.
LowState contains IMU/motors, not measured base position or velocity.
"""
import math

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from tf2_ros import TransformBroadcaster


class OdomBridge(Node):
    def __init__(self):
        super().__init__('odom_bridge')
        self.base = self.declare_parameter('base_frame', 'base_link').value
        self.pub = self.create_publisher(Odometry, '/odom', 10)
        self.tf = TransformBroadcaster(self)
        if self.declare_parameter('use_native_odom', True).value:
            topic = self.declare_parameter('odom_topic', '/dog_odom').value
            self.sub = self.create_subscription(Odometry, topic, self.forward, qos_profile_sensor_data)
            self.get_logger().info('Forwarding {} to /odom and odom -> {}'.format(topic, self.base))
        else:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
            from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
            ChannelFactoryInitialize(0, self.declare_parameter('interface', 'eth0').value)
            self.sub = ChannelSubscriber('rt/sportmodestate', SportModeState_)
            self.sub.Init(self.from_sdk, 10)
            self.get_logger().info('Using measured rt/sportmodestate; availability depends on firmware')

    def from_sdk(self, state):
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x, msg.pose.pose.position.y = map(float, state.position[:2])
        q = state.imu_state.quaternion
        yaw = math.atan2(2.0 * (q[0] * q[3] + q[1] * q[2]),
                         1.0 - 2.0 * (q[2] ** 2 + q[3] ** 2))
        msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        # Upstream velocity is expressed in the world; Odometry twist is in the child frame.
        vx, vy = state.velocity[:2]
        msg.twist.twist.linear.x = math.cos(yaw) * vx + math.sin(yaw) * vy
        msg.twist.twist.linear.y = -math.sin(yaw) * vx + math.cos(yaw) * vy
        msg.twist.twist.angular.z = float(state.yaw_speed)
        self.forward(msg)

    def forward(self, msg):
        msg.header.frame_id, msg.child_frame_id = 'odom', self.base
        self.pub.publish(msg)
        transform = TransformStamped()
        transform.header, transform.child_frame_id = msg.header, self.base
        transform.transform.translation.x = msg.pose.pose.position.x
        transform.transform.translation.y = msg.pose.pose.position.y
        transform.transform.translation.z = msg.pose.pose.position.z
        transform.transform.rotation = msg.pose.pose.orientation
        self.tf.sendTransform(transform)


def main(args=None):
    rclpy.init(args=args)
    node = OdomBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
