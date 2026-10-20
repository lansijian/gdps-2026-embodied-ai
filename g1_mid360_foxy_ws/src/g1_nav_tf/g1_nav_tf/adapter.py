"""Direct factory odometry -> projected, corrected 100Hz TF. No static odometry."""
import copy
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster
from g1_nav_perception.pipeline import load_site
from g1_nav_perception.core import OffsetCalibrator, ReceiptClock, assign_stamp, quaternion, finite, stamp_seconds, Blocked


class Adapter(Node):
    def __init__(self):
        super().__init__('g1_nav_tf_adapter')
        self.site = load_site(self)
        self.declare_parameter('time_strategy', self.site['timing']['strategy'])
        self.declare_parameter('keep_z', False)
        self.strategy = self.get_parameter('time_strategy').value
        self.offset = OffsetCalibrator(time.monotonic())
        self.clock = ReceiptClock(.2)
        self.last_publish = 0.
        self.offset_logged = False
        self.dynamic = TransformBroadcaster(self)
        self.static = StaticTransformBroadcaster(self)
        transforms = []
        c = self.site['calibration']
        try:
            quaternion(c['quaternion_xyzw'])
            if not finite(c['translation_xyz']) or len(c['translation_xyz']) != 3:
                raise Blocked('unknown translation')
            t = TransformStamped();t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id, t.child_frame_id = 'robot_center', 'livox_frame'
            t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = c['translation_xyz']
            q = t.transform.rotation;q.x, q.y, q.z, q.w = c['quaternion_xyzw']
            transforms.append(t)
        except (Blocked, TypeError):
            self.get_logger().warning('SENSOR_EXTRINSICS_UNUSABLE: odom TF still starts, sensor TF omitted')
        for child in ('base_link', 'base_footprint'):
            t = TransformStamped();t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id, t.child_frame_id = 'robot_center', child
            t.transform.rotation.w = 1.
            transforms.append(t)
        self.static.sendTransform(transforms)
        self.create_subscription(Odometry, '/dog_odom', self.odom,
                                 QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_timer(1., self.check_timeout)

    def check_timeout(self):
        if self.strategy == 'offset' and self.offset.expired(time.monotonic()):
            self.get_logger().error('OFFSET_CALIBRATION_TIMEOUT: /dog_odom fewer than 10 frames in 30s')
            raise RuntimeError('ODOM_OFFSET_CALIBRATION_TIMEOUT')

    def odom(self, original):
        msg = copy.deepcopy(original)
        now, mono = time.time(), time.monotonic()
        if msg.header.frame_id != 'odom' or msg.child_frame_id != 'robot_center':
            self.get_logger().warning('WRONG_ODOM_FRAME');return
        stamp = stamp_seconds(msg.header.stamp)
        if self.strategy != 'preserve':
            if not self.clock.observe(now, mono):return
            if self.strategy == 'offset':
                stamp = self.offset.observe(stamp, now, mono)
                if self.offset.offset is not None and not self.offset_logged:
                    self.get_logger().info('ODOM_OFFSET_CALIBRATED offset_s='+str(self.offset.offset));self.offset_logged=True
                if stamp is None:return
            elif self.strategy == 'receive_time':stamp = now
            else:return
        if not -.03 <= now-stamp <= .3 or mono-self.last_publish < .01:return
        p,q = msg.pose.pose.position,msg.pose.pose.orientation
        try:quaternion((q.x,q.y,q.z,q.w))
        except Blocked:return
        if not finite((p.x,p.y,p.z)):return
        t=TransformStamped();t.header=msg.header;assign_stamp(t,stamp);t.child_frame_id='robot_center'
        t.transform.translation.x,t.transform.translation.y=p.x,p.y
        t.transform.translation.z=p.z if self.get_parameter('keep_z').value else 0.
        t.transform.rotation=q
        self.dynamic.sendTransform(t);self.last_publish=mono


def main(args=None):
    rclpy.init(args=args);node=Adapter()
    from g1_nav_perception.runtime import spin
    spin(node)
