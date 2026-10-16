"""Local avoidance dry-run on real G1 EDU sensors. Does not start Nav2 or live motion.

Pipeline:
  /utlidar/cloud_livox_mid360 (PointCloud2)
    -> gdps_pointcloud_to_laserscan -> /scan (LaserScan)
    -> gdps_local_navigator (SharedNavigator, dry-run + mock backend)
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
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
            Node(
                package="gdps_g1_navigation",
                executable="local_navigator",
                name="gdps_local_navigator",
                output="screen",
            ),
        ]
    )

