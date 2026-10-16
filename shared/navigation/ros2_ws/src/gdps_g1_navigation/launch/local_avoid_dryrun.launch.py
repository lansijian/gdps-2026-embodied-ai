"""Local avoidance dry-run. Does not start Nav2 or live LocoClient."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            Node(
                package="gdps_g1_navigation",
                executable="scan_restamper",
                name="gdps_scan_restamper",
                output="screen",
            ),
            Node(
                package="gdps_g1_navigation",
                executable="local_navigator",
                name="gdps_local_navigator",
                output="screen",
            ),
        ]
    )
