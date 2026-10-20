# Reference: nav2_bringup bringup_launch.py / navigation_launch.py (Foxy).
# Mapping and navigation share a single SLAM map authority; optional saved-map mode uses AMCL instead.
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
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
    nav = get_package_share_directory('nav2_bringup')
    params = RewrittenYaml(source_file=LaunchConfiguration('params_file'), root_key='', convert_types=True,
                           param_rewrites={'robot_base_frame': LaunchConfiguration('base_frame'),
                                           'base_frame_id': LaunchConfiguration('base_frame'),
                                           'scan_topic': LaunchConfiguration('scan_topic'),
                                           'topic': LaunchConfiguration('scan_topic')})
    sensing = {key: LaunchConfiguration(key) for key in SENSING_KEYS}
    odom_parameters = {'base_frame': LaunchConfiguration('base_frame'),
                       'odom_topic': LaunchConfiguration('odom_topic'),
                       'use_native_odom': ParameterValue(LaunchConfiguration('use_native_odom'), value_type=bool),
                       'interface': LaunchConfiguration('interface')}
    saved = GroupAction(condition=UnlessCondition(LaunchConfiguration('slam')), actions=[
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'sensing.launch.py')),
                                 launch_arguments=sensing.items()),
        Node(package='g1_nav_bringup', executable='odom_bridge', output='screen', parameters=[odom_parameters]),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(nav, 'launch', 'localization_launch.py')),
                                 launch_arguments={'map': LaunchConfiguration('map'), 'params_file': params,
                                                   'use_sim_time': 'false',
                                                   'autostart': LaunchConfiguration('autostart')}.items())])
    return LaunchDescription([
        DeclareLaunchArgument('slam', default_value='true'),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        DeclareLaunchArgument('odom_topic', default_value='/dog_odom'),
        DeclareLaunchArgument('use_native_odom', default_value='true'),
        DeclareLaunchArgument('interface', default_value='eth0'),
        DeclareLaunchArgument('dry_run', default_value='true'),
        DeclareLaunchArgument('autostart', default_value='true'),
        DeclareLaunchArgument('params_file', default_value=os.path.join(share, 'config', 'nav2_params.yaml')),
        DeclareLaunchArgument('bridge_params_file', default_value=os.path.join(share, 'config', 'bridge.yaml')),
        DeclareLaunchArgument('slam_params_file', default_value=os.path.join(share, 'config', 'slam_toolbox.yaml')),
        DeclareLaunchArgument('mid360_config', default_value=os.path.join(share, 'config', 'mid360_config.json')),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('scan_min_height', default_value='-0.05'),
        DeclareLaunchArgument('scan_max_height', default_value='0.35'),
        DeclareLaunchArgument('lidar_x', default_value='0'),
        DeclareLaunchArgument('lidar_y', default_value='0'),
        DeclareLaunchArgument('lidar_z', default_value='0.4'),
        DeclareLaunchArgument('lidar_qx', default_value='0'),
        DeclareLaunchArgument('lidar_qy', default_value='1'),
        DeclareLaunchArgument('lidar_qz', default_value='0'),
        DeclareLaunchArgument('lidar_qw', default_value='0'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'mapping.launch.py')),
                                 condition=IfCondition(LaunchConfiguration('slam')),
                                 launch_arguments=dict(
                                     sensing,
                                     slam_params_file=LaunchConfiguration('slam_params_file'),
                                     odom_topic=LaunchConfiguration('odom_topic'),
                                     use_native_odom=LaunchConfiguration('use_native_odom'),
                                     interface=LaunchConfiguration('interface')).items()),
        saved,
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(nav, 'launch', 'navigation_launch.py')),
                                 launch_arguments={'params_file': params, 'use_sim_time': 'false',
                                                   'autostart': LaunchConfiguration('autostart')}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('cmd_vel_bridge'), 'launch', 'bridge.launch.py')),
            launch_arguments={'bridge_params_file': LaunchConfiguration('bridge_params_file'),
                              'dry_run': LaunchConfiguration('dry_run'),
                              'interface': LaunchConfiguration('interface')}.items())])
