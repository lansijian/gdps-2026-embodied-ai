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
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from sensor_msgs.msg import LaserScan
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header
from tf2_ros import Buffer, TransformListener


def main():
    saved = '--saved-map' in sys.argv
    os.makedirs('evidence', exist_ok=True)
    # Actual Livox executable is separately exercised with the empty deployment template.
    command = ['ros2', 'launch', 'g1_nav_bringup', 'nav_bringup.launch.py',
               'start_driver:=false', 'dry_run:=true']
    if saved:
        # Synthetic circular room: same geometry as the point cloud below.
        size, resolution = 240, 0.05
        pixels = bytearray()
        for row in range(size):
            for column in range(size):
                radius = math.hypot(-6 + (column + 0.5) * resolution, 6 - (row + 0.5) * resolution)
                pixels.append(0 if abs(radius - 5) < 0.07 else (254 if radius < 5 else 205))
        with open('evidence/room.pgm', 'wb') as pgm:
            pgm.write(b'P5\n240 240\n255\n' + pixels)
        with open('evidence/room.yaml', 'w') as config:
            config.write('image: room.pgm\nresolution: 0.05\norigin: [-6.0, -6.0, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')
        command += ['slam:=false', 'map:=' + os.path.abspath('evidence/room.yaml')]
    output = open('evidence/launch-saved-map.log' if saved else 'evidence/launch.log', 'w')
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
    node.create_subscription(OccupancyGrid, '/map', lambda msg: seen.update(map=seen['map'] + 1),
                             QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    costmap = [None]
    node.create_subscription(OccupancyGrid, '/local_costmap/costmap', lambda msg: costmap.__setitem__(0, msg), 10)
    moving_commands = []
    node.create_subscription(Twist, '/cmd_vel', lambda msg: moving_commands.append(msg)
                             if abs(msg.linear.x) + abs(msg.angular.z) > 0 else None, 10)
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    action = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    initial_pose = node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
    obstacle = [False]
    tick = [0]
    def publish():
        msg = Odometry()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id, msg.child_frame_id = 'odom', 'base_link'
        msg.pose.pose.orientation.w = 1.0
        odom.publish(msg)
        if saved and tick[0] % 25 == 0 and not buffer.can_transform('map', 'odom', rclpy.time.Time()):
            pose = PoseWithCovarianceStamped()
            pose.header.frame_id, pose.header.stamp = 'map', msg.header.stamp
            pose.pose.pose.orientation.w = 1.0
            pose.pose.covariance[0] = pose.pose.covariance[7] = 0.25
            pose.pose.covariance[35] = 0.0685
            initial_pose.publish(pose)
        if tick[0] % 5 == 0:
            header = Header(stamp=msg.header.stamp, frame_id='livox_frame')
            # Coarse Y-180 transform maps source z=0.2 to base z=0.2.
            points = [(5 * math.cos(a * math.pi / 360), 5 * math.sin(a * math.pi / 360), 0.2) for a in range(720)]
            if obstacle[0]:
                points += [(-0.65, i * 0.01, 0.2) for i in range(-30, 31)]
            cloud.publish(point_cloud2.create_cloud_xyz32(header, points))
        tick[0] += 1
    node.create_timer(0.02, publish)
    try:
        start = time.monotonic()
        goal_future = None
        phase = None
        while time.monotonic() - start < 75:
            rclpy.spin_once(node, timeout_sec=0.05)
            if process.poll() is not None:
                raise AssertionError('Launch exited early; inspect launch.log')
            if seen['scan'] >= 30 and seen['map'] >= 1 and action.server_is_ready() and goal_future is None:
                goal = NavigateToPose.Goal()
                goal.pose.header.frame_id = 'map'
                goal.pose.header.stamp = node.get_clock().now().to_msg()
                goal.pose.pose.position.x = 1.0
                goal.pose.pose.orientation.w = 1.0
                goal_future = action.send_goal_async(goal)
            if moving_commands and goal_future is not None and goal_future.done() and goal_future.result().accepted:
                grid = costmap[0]
                if grid is None:
                    continue
                marked = False
                for y in (-0.2, 0.0, 0.2):
                    col = int((0.65 - grid.info.origin.position.x) / grid.info.resolution)
                    row = int((y - grid.info.origin.position.y) / grid.info.resolution)
                    for offset in (-1, 0, 1):
                        if 0 <= row < grid.info.height and 0 <= col + offset < grid.info.width:
                            marked |= grid.data[row * grid.info.width + col + offset] >= 99
                if phase is None:
                    assert not marked, 'Synthetic room has an unexpected initial local obstacle'
                    obstacle[0], phase = True, 'mark'
                    continue
                if phase == 'mark':
                    if marked:
                        obstacle[0], phase = False, 'clear'
                    continue
                if marked:
                    continue
                required = {'odom_bridge', 'pointcloud_to_laserscan', 'cmd_vel_bridge',
                            'controller_server', 'planner_server', 'bt_navigator'}
                required |= {'amcl', 'map_server'} if saved else {'slam_toolbox'}
                assert required <= set(node.get_node_names()), node.get_node_names()
                assert all(scan.header.frame_id == 'base_link' for scan in scans)
                assert any(any(math.isfinite(v) for v in scan.ranges) for scan in scans)
                for parent, child in [('map', 'odom'), ('odom', 'base_link'), ('base_link', 'livox_frame')]:
                    assert buffer.can_transform(parent, child, rclpy.time.Time()), (parent, child)
                print('PASS {} cloud -> scan -> map -> accepted Nav2 goal -> cmd_vel; dynamic obstacle marked/cleared; counts={}, commands={}'.format(
                    'AMCL' if saved else 'SLAM', seen, len(moving_commands)))
                return
        raise AssertionError('No complete synthetic flow after 75s: {}'.format(seen))
    finally:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
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
