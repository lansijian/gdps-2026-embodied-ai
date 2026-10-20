# Reference: slam_toolbox online_sync_launch.py (Foxy); ROS 2 IncludeLaunchDescription.
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from nav2_common.launch import RewrittenYaml

SENSING_KEYS = ('base_frame', 'scan_topic', 'start_driver', 'mid360_config',
                'scan_min_height', 'scan_max_height',
                'lidar_x', 'lidar_y', 'lidar_z', 'lidar_qx', 'lidar_qy', 'lidar_qz', 'lidar_qw')


def generate_launch_description():
    share = get_package_share_directory('g1_nav_bringup')
    config = RewrittenYaml(source_file=LaunchConfiguration('slam_params_file'), root_key='',
                           param_rewrites={'base_frame': LaunchConfiguration('base_frame'),
                                           'scan_topic': LaunchConfiguration('scan_topic')}, convert_types=True)
    return LaunchDescription([
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        DeclareLaunchArgument('odom_topic', default_value='/dog_odom'),
        DeclareLaunchArgument('use_native_odom', default_value='true'),
        DeclareLaunchArgument('interface', default_value='eth0'),
        DeclareLaunchArgument('slam_params_file', default_value=os.path.join(share, 'config', 'slam_toolbox.yaml')),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('mid360_config', default_value=os.path.join(share, 'config', 'mid360_config.json')),
        DeclareLaunchArgument('scan_min_height', default_value='-0.05'),
        DeclareLaunchArgument('scan_max_height', default_value='0.35'),
        DeclareLaunchArgument('lidar_x', default_value='0'),
        DeclareLaunchArgument('lidar_y', default_value='0'),
        DeclareLaunchArgument('lidar_z', default_value='0.4'),
        DeclareLaunchArgument('lidar_qx', default_value='0'),
        DeclareLaunchArgument('lidar_qy', default_value='1'),
        DeclareLaunchArgument('lidar_qz', default_value='0'),
        DeclareLaunchArgument('lidar_qw', default_value='0'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'sensing.launch.py')),
                                 launch_arguments={key: LaunchConfiguration(key)
                                                   for key in SENSING_KEYS}.items()),
        Node(package='g1_nav_bringup', executable='odom_bridge', output='screen',
             parameters=[{'base_frame': LaunchConfiguration('base_frame'),
                          'odom_topic': LaunchConfiguration('odom_topic'),
                          'use_native_odom': ParameterValue(LaunchConfiguration('use_native_odom'), value_type=bool),
                          'interface': LaunchConfiguration('interface')}]),
        Node(package='slam_toolbox', executable='sync_slam_toolbox_node', name='slam_toolbox',
             output='screen', parameters=[config, {'use_sim_time': False}])])
