"""SYNTHETIC_TEST ONLY. Wall-time geometric room; never imports a G1 SDK."""
import json
import os
import math
import struct
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2, PointField, Imu
from nav_msgs.msg import Odometry


class Fixture(Node):
    def __init__(self, fault_path):
        if os.environ.get('G1_NAV_TEST_ONLY')!='1' or os.environ.get('ROS_DOMAIN_ID')!='87':
            raise RuntimeError('Synthetic source requires explicit test-only domain 87')
        super().__init__('SYNTHETIC_TEST_sensor_fixture')
        self.fault_path = Path(fault_path)
        self.load_test = os.environ.get('G1_NAV_LOAD_TEST') == '1'
        self.payloads = {}
        self.cloud = self.create_publisher(PointCloud2, '/utlidar/cloud_livox_mid360', QoSProfile(depth=5,reliability=ReliabilityPolicy.RELIABLE))
        self.odom = self.create_publisher(Odometry, '/dog_odom', QoSProfile(depth=5,reliability=ReliabilityPolicy.RELIABLE))
        self.imu = self.create_publisher(Imu, '/utlidar/imu_livox_mid360', qos_profile_sensor_data)
        self.create_timer(.1, self.points)
        self.create_timer(.00125 if self.load_test else .02, self.pose)
        self.create_timer(.005 if self.load_test else .01, self.inertial)

    def fault(self):
        try:
            return self.fault_path.read_text().strip()
        except OSError:
            return ''

    def stamp(self):
        now = self.get_clock().now().to_msg()
        if self.fault() == 'stale_time':
            now.sec -= 5
        if self.fault() == 'future_time':
            now.sec += 5
        return now

    def points(self):
        fault = self.fault()
        if fault == 'cloud_loss':
            return
        dynamic = fault == 'dynamic_obstacle'
        if dynamic not in self.payloads:
            self.payloads[dynamic] = self.build_cloud(dynamic)
        m = self.payloads[dynamic]
        for field in m.fields:
            field.datatype=PointField.FLOAT64 if fault=='unsupported_layout' else PointField.FLOAT32
        m.header.frame_id='wrong_sensor' if fault=='wrong_frame' else 'livox_frame'
        m.header.stamp=self.stamp()
        self.cloud.publish(m)

    def build_cloud(self, dynamic):
        # Cache immutable synthetic geometry so Python packing cannot throttle
        # the independent 800 Hz odom / 200 Hz IMU source timers every scan.
        pts = []
        for i in range(720):
            a = -math.pi+2*math.pi*i/720
            c, s = math.cos(a), math.sin(a)
            distance = 3/max(abs(c), abs(s))
            pts.append((distance*c, distance*s, .3))
            pts.append((distance*.5*c, distance*.5*s, -.5))
        if dynamic:
            pts.extend((.45, -.2+i*.01, .3) for i in range(41))
        if self.load_test:
            # Repeated SYNTHETIC geometry tests processing load, not real coverage.
            pts=[pts[i%len(pts)] for i in range(20064)]
        m=PointCloud2();m.height=1;m.width=len(pts);m.point_step=32 if self.load_test else 12;m.row_step=len(pts)*m.point_step
        m.fields=[PointField(name=n,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,n in enumerate('xyz')]
        m.is_dense=True;m.data=b''.join(struct.pack('<fff',*p)+(b'\0'*20 if self.load_test else b'') for p in pts)
        return m

    def pose(self):
        if self.fault()=='odom_loss':return
        m=Odometry();m.header.stamp=self.stamp();m.header.frame_id='odom';m.child_frame_id='robot_center'
        m.pose.pose.orientation.w=1.;self.odom.publish(m)

    def inertial(self):
        m=Imu();m.header.stamp=self.stamp();m.header.frame_id='livox_frame';m.orientation.w=1.
        self.imu.publish(m)


if __name__=='__main__':
    import sys
    if os.environ.get('G1_NAV_TEST_ONLY')!='1' or os.environ.get('ROS_DOMAIN_ID')!='87':
        raise SystemExit('Refusing synthetic factory-topic publication outside explicit test domain 87')
    rclpy.init();node=Fixture(sys.argv[1])
    try:rclpy.spin(node)
    finally:node.destroy_node();rclpy.shutdown()
