"""SYNTHETIC_TEST ONLY. Wall-time geometric room; never imports a G1 SDK."""
import json
import math
import struct
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, PointField, Imu
from nav_msgs.msg import Odometry


class Fixture(Node):
    def __init__(self, fault_path):
        super().__init__('SYNTHETIC_TEST_sensor_fixture')
        self.fault_path = Path(fault_path)
        self.cloud = self.create_publisher(PointCloud2, '/utlidar/cloud_livox_mid360', qos_profile_sensor_data)
        self.odom = self.create_publisher(Odometry, '/dog_odom', qos_profile_sensor_data)
        self.imu = self.create_publisher(Imu, '/utlidar/imu_livox_mid360', qos_profile_sensor_data)
        self.create_timer(.1, self.points)
        self.create_timer(.02, self.pose)
        self.create_timer(.01, self.inertial)

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
        pts = []
        for i in range(720):
            a = -math.pi+2*math.pi*i/720
            c, s = math.cos(a), math.sin(a)
            distance = 3/max(abs(c), abs(s))
            pts.append((distance*c, distance*s, .3))
            pts.append((distance*.5*c, distance*.5*s, -.5))
        if fault == 'dynamic_obstacle':
            pts.extend((.45, -.2+i*.01, .3) for i in range(41))
        m=PointCloud2();m.header.frame_id='wrong_sensor' if fault=='wrong_frame' else 'livox_frame'
        m.header.stamp=self.stamp();m.height=1;m.width=len(pts);m.point_step=12;m.row_step=len(pts)*12
        m.fields=[PointField(name=n,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,n in enumerate('xyz')]
        m.is_dense=True;m.data=b''.join(struct.pack('<fff',*p) for p in pts)
        self.cloud.publish(m)

    def pose(self):
        if self.fault()=='odom_loss':return
        m=Odometry();m.header.stamp=self.stamp();m.header.frame_id='odom';m.child_frame_id='robot_center'
        m.pose.pose.orientation.w=1.;self.odom.publish(m)

    def inertial(self):
        m=Imu();m.header.stamp=self.stamp();m.header.frame_id='livox_frame';m.orientation.w=1.
        self.imu.publish(m)


if __name__=='__main__':
    import sys
    rclpy.init();node=Fixture(sys.argv[1])
    try:rclpy.spin(node)
    finally:node.destroy_node();rclpy.shutdown()
