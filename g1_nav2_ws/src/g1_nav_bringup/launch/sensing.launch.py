# Reference: Livox-SDK/livox_ros_driver2 launch_ROS2/msg_MID360_launch.py;
# ros-perception/pointcloud_to_laserscan launch/example.launch.py (Foxy).
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    share = get_package_share_directory('g1_nav_bringup')
    base = LaunchConfiguration('base_frame')
    scan = LaunchConfiguration('scan_topic')
    config = RewrittenYaml(source_file=os.path.join(share, 'config', 'pcl_to_scan.yaml'),
                           root_key='', param_rewrites={'target_frame': base}, convert_types=True)
    args = [DeclareLaunchArgument('base_frame', default_value='base_link'),
            DeclareLaunchArgument('scan_topic', default_value='/scan'),
            DeclareLaunchArgument('start_driver', default_value='true'),
            DeclareLaunchArgument('mid360_config', default_value=os.path.join(share, 'config', 'mid360_config.json'))]
    # Archive's coarse Y-axis half-turn, NOT a precision calibration or an X-axis roll.
    for key, value in [('lidar_x', '0'), ('lidar_y', '0'), ('lidar_z', '0.4'),
                       ('lidar_qx', '0'), ('lidar_qy', '1'), ('lidar_qz', '0'), ('lidar_qw', '0')]:
        args.append(DeclareLaunchArgument(key, default_value=value))
    return LaunchDescription(args + [
        Node(package='livox_ros_driver2', executable='livox_ros_driver2_node',
             name='livox_lidar_publisher', output='screen', condition=IfCondition(LaunchConfiguration('start_driver')),
             parameters=[{'xfer_format': 0, 'multi_topic': 0, 'data_src': 0, 'publish_freq': 10.0,
                          'output_data_type': 0, 'frame_id': 'livox_frame',
                          'user_config_path': LaunchConfiguration('mid360_config'),
                          'cmdline_input_bd_code': 'livox0000000001'}]),
        Node(package='tf2_ros', executable='static_transform_publisher', name='lidar_extrinsics', output='screen',
             arguments=[LaunchConfiguration(k) for k in
                        ('lidar_x', 'lidar_y', 'lidar_z', 'lidar_qx', 'lidar_qy', 'lidar_qz', 'lidar_qw')]
                       + [base, 'livox_frame']),
        Node(package='pointcloud_to_laserscan', executable='pointcloud_to_laserscan_node',
             name='pointcloud_to_laserscan', output='screen', parameters=[config],
             remappings=[('cloud_in', '/livox/lidar'), ('scan', scan)])])
