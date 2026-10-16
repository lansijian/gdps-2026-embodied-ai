"""Optional Nav2 bringup. Requires Foxy + maps + verified frames.

This launch does not enable live motion. Pair with cmdvel_bridge in dry-run.
G1 EDU on-site baseline (2026-10-16): ROS 2 Foxy, Livox MID-360 PointCloud2.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg = get_package_share_directory("gdps_g1_navigation")
    default_params = os.path.join(pkg, "config", "nav2_params.yaml")
    nav2_launch = os.path.join(
        get_package_share_directory("nav2_bringup"),
        "launch",
        "bringup_launch.py",
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("map", default_value=""),
            DeclareLaunchArgument("params_file", default_value=default_params),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(nav2_launch),
                launch_arguments={
                    "map": LaunchConfiguration("map"),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                    "params_file": LaunchConfiguration("params_file"),
                }.items(),
            ),
            Node(
                package="gdps_g1_navigation",
                executable="pointcloud_to_laserscan",
                name="gdps_pointcloud_to_laserscan",
                output="screen",
                parameters=[
                    {"input_topic": "/utlidar/cloud_livox_mid360"},
                    {"output_topic": "/scan"},
                ],
            ),
        ]
    )

