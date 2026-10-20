"""SYNTHETIC_TEST: actual Foxy nodes; no hardware or SDK control imports.

Reference: ROS 2 sensor_msgs_py point_cloud2 and rclpy ActionClient tutorials.
"""
import math
import os
import signal
import subprocess
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid, Odometry
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header
from tf2_ros import Buffer, TransformListener


def main():
    # Actual Livox executable is separately exercised with the empty deployment template.
    command = ['ros2', 'launch', 'g1_nav_bringup', 'nav_bringup.launch.py',
               'start_driver:=false', 'dry_run:=true']
    os.makedirs('evidence', exist_ok=True)
    output = open('evidence/launch.log', 'w')
    process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    rclpy.init()
    node = rclpy.create_node('synthetic_input')
    cloud = node.create_publisher(type(point_cloud2.create_cloud_xyz32(Header(), [])), '/livox/lidar', qos_profile_sensor_data)
    odom = node.create_publisher(Odometry, '/dog_odom', qos_profile_sensor_data)
    seen = {'scan': 0, 'map': 0}
    scans = []
    def on_scan(msg):
        seen['scan'] += 1
        scans.append(msg)
    node.create_subscription(LaserScan, '/scan', on_scan, qos_profile_sensor_data)
    node.create_subscription(OccupancyGrid, '/map', lambda msg: seen.update(map=seen['map'] + 1), 10)
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    action = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    tick = [0]
    def publish():
        msg = Odometry()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id, msg.child_frame_id = 'odom', 'base_link'
        msg.pose.pose.orientation.w = 1.0
        odom.publish(msg)
        if tick[0] % 5 == 0:
            header = Header(stamp=msg.header.stamp, frame_id='livox_frame')
            # Coarse Y-180 transform maps source z=0.2 to base z=0.2.
            points = [(5 * math.cos(a * math.pi / 360), 5 * math.sin(a * math.pi / 360), 0.2) for a in range(720)]
            cloud.publish(point_cloud2.create_cloud_xyz32(header, points))
        tick[0] += 1
    node.create_timer(0.02, publish)
    try:
        start = time.monotonic()
        while time.monotonic() - start < 75:
            rclpy.spin_once(node, timeout_sec=0.05)
            if process.poll() is not None:
                raise AssertionError('Launch exited early; inspect launch.log')
            if seen['scan'] >= 30 and seen['map'] >= 1 and action.server_is_ready():
                required = {'slam_toolbox', 'odom_bridge', 'pointcloud_to_laserscan', 'cmd_vel_bridge',
                            'controller_server', 'planner_server', 'bt_navigator'}
                assert required <= set(node.get_node_names()), node.get_node_names()
                assert all(scan.header.frame_id == 'base_link' for scan in scans)
                assert any(any(math.isfinite(v) for v in scan.ranges) for scan in scans)
                for parent, child in [('map', 'odom'), ('odom', 'base_link'), ('base_link', 'livox_frame')]:
                    assert buffer.can_transform(parent, child, rclpy.time.Time()), (parent, child)
                print('PASS synthetic cloud -> scan -> SLAM map -> Nav2 action; counts={}'.format(seen))
                return
        raise AssertionError('No complete synthetic flow after 75s: {}'.format(seen))
    finally:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        node.destroy_node()
        rclpy.shutdown()
        output.close()


if __name__ == '__main__':
    main()
