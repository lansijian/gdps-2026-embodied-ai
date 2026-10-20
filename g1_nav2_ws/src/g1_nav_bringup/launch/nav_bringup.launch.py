# Reference: nav2_bringup bringup_launch.py / navigation_launch.py (Foxy).
# Mapping and navigation share a single SLAM map authority; optional saved-map mode uses AMCL instead.
import os
import sys
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    share = get_package_share_directory('g1_nav_bringup')
    nav = get_package_share_directory('nav2_bringup')
    params = RewrittenYaml(source_file=LaunchConfiguration('params_file'), root_key='', convert_types=True,
                           param_rewrites={'robot_base_frame': LaunchConfiguration('base_frame'),
                                           'base_frame_id': LaunchConfiguration('base_frame'),
                                           'scan_topic': LaunchConfiguration('scan_topic'),
                                           'topic': LaunchConfiguration('scan_topic')})
    saved = GroupAction(condition=UnlessCondition(LaunchConfiguration('slam')), actions=[
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'sensing.launch.py'))),
        ExecuteProcess(cmd=[sys.executable, os.path.join(share, 'launch', 'odom_bridge.py'), '--ros-args',
                            '-p', ['base_frame:=', LaunchConfiguration('base_frame')],
                            '-p', ['odom_topic:=', LaunchConfiguration('odom_topic')],
                            '-p', ['use_native_odom:=', LaunchConfiguration('use_native_odom')],
                            '-p', ['interface:=', LaunchConfiguration('interface')]], output='screen'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(nav, 'launch', 'localization_launch.py')),
                                 launch_arguments={'map': LaunchConfiguration('map'), 'params_file': params,
                                                   'use_sim_time': 'false', 'autostart': 'true'}.items())])
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
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'mapping.launch.py')),
                                 condition=IfCondition(LaunchConfiguration('slam'))),
        saved,
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(nav, 'launch', 'navigation_launch.py')),
                                 launch_arguments={'params_file': params, 'use_sim_time': 'false',
                                                   'autostart': LaunchConfiguration('autostart')}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('cmd_vel_bridge'), 'launch', 'bridge.launch.py')),
            launch_arguments={'bridge_params_file': LaunchConfiguration('bridge_params_file'),
                              'dry_run': LaunchConfiguration('dry_run'),
                              'interface': LaunchConfiguration('interface')}.items())])
