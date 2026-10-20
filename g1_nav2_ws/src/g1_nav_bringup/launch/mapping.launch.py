# Reference: slam_toolbox online_sync_launch.py (Foxy); ROS 2 IncludeLaunchDescription.
import os
import sys
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


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
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'sensing.launch.py'))),
        ExecuteProcess(cmd=[sys.executable, os.path.join(share, 'launch', 'odom_bridge.py'), '--ros-args',
                            '-p', ['base_frame:=', LaunchConfiguration('base_frame')],
                            '-p', ['odom_topic:=', LaunchConfiguration('odom_topic')],
                            '-p', ['use_native_odom:=', LaunchConfiguration('use_native_odom')],
                            '-p', ['interface:=', LaunchConfiguration('interface')]], output='screen'),
        Node(package='slam_toolbox', executable='sync_slam_toolbox_node', name='slam_toolbox',
             output='screen', parameters=[config, {'use_sim_time': False}])])
