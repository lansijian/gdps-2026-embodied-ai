"""Local avoidance dry-run on real G1 EDU sensors. Does not start Nav2 or live motion.

Pipeline:
  /dog_odom (Odometry, 1000Hz, frame_id=odom, child=robot_center)
    -> gdps_odom_tf -> broadcasts odom -> robot_center TF (data-derived, not faked)
  /utlidar/cloud_livox_mid360 (PointCloud2, ~10Hz)
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
                executable="odom_tf",
                name="gdps_odom_tf",
                output="screen",
                parameters=[{"odom_topic": "/dog_odom"}],
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
            Node(
                package="gdps_g1_navigation",
                executable="local_navigator",
                name="gdps_local_navigator",
                output="screen",
                parameters=[{"odom_topic": "/dog_odom", "cmd_vel_topic": "/gdps/cmd_vel_local"}],
            ),
        ]
    )

