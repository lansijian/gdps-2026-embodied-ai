"""Only measured odometry and explicitly verified sensor extrinsics create TF."""
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster
from g1_nav_perception.pipeline import load_site
from g1_nav_perception.core import validate_site, Blocked, quaternion, finite, stamp_seconds
import time


class Adapter(Node):
    def __init__(self):
        super().__init__('g1_nav_tf_adapter')
        self.site = load_site(self)
        validate_site(self.site)
        self.dynamic = TransformBroadcaster(self)
        self.static = StaticTransformBroadcaster(self)
        if self.site['tf']['livox_owner'] == 'project':
            t = TransformStamped()
            t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id, t.child_frame_id = 'robot_center', 'livox_frame'
            c = self.site['calibration']
            t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = c['translation_xyz']
            q = t.transform.rotation
            q.x, q.y, q.z, q.w = c['quaternion_xyzw']
            self.static.sendTransform(t)
        if self.site['tf']['odom_owner'] == 'project':
            self.create_subscription(Odometry, '/g1_nav/odom', self.odom, qos_profile_sensor_data)

    def odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        age = time.time()-stamp_seconds(msg.header.stamp)
        if msg.header.frame_id != 'odom' or msg.child_frame_id != 'robot_center' or not (
                -self.site['timing']['max_future_s'] <= age <= self.site['timing']['max_age_s']):
            return
        try:
            quaternion((q.x, q.y, q.z, q.w))
        except Blocked:
            return
        if not finite((p.x, p.y, p.z)):
            return
        t = TransformStamped(); t.header = msg.header; t.child_frame_id = 'robot_center'
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = p.x, p.y, p.z
        t.transform.rotation = q
        self.dynamic.sendTransform(t)


def main(args=None):
    rclpy.init(args=args); node = Adapter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node(); rclpy.shutdown()
