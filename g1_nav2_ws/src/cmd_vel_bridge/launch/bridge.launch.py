# Reference: ROS 2 Foxy launch tutorial; Unitree LocoClient parameters.
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('bridge_params_file', default_value=os.path.join(
            get_package_share_directory('cmd_vel_bridge'), 'config', 'bridge.yaml')),
        DeclareLaunchArgument('dry_run', default_value='true'),
        DeclareLaunchArgument('interface', default_value='eth0'),
        Node(package='cmd_vel_bridge', executable='bridge_node', output='screen',
             parameters=[LaunchConfiguration('bridge_params_file'),
                         {'dry_run': ParameterValue(LaunchConfiguration('dry_run'), value_type=bool),
                          'interface': LaunchConfiguration('interface')}])])
