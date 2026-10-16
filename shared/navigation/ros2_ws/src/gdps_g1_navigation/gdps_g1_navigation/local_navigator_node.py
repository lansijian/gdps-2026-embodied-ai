"""Local obstacle gating + SharedNavigator. Not full Nav2."""

from __future__ import annotations

from .repo_path import ensure_repo_on_path


def main() -> None:
    ensure_repo_on_path()
    import math

    import rclpy
    from geometry_msgs.msg import PoseStamped, Twist
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String

    from shared.navigation.api.types import Pose2D
    from shared.navigation.factory import build_navigator
    from shared.navigation.perception.obstacle_monitor import ScanFrame

    sensor_qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )

    class LocalNavigator(Node):
        def __init__(self) -> None:
            super().__init__("gdps_local_navigator")
            self.nav = build_navigator()
            self.create_subscription(LaserScan, "/scan", self._on_scan, sensor_qos)
            self.create_subscription(PoseStamped, "/goal_pose", self._on_goal, 10)
            self.create_subscription(String, "/gdps/manual_stop", self._on_stop, 10)
            self.create_subscription(String, "/gdps/host_heartbeat", self._on_hb, 10)
            self.declare_parameter("cmd_vel_topic", "/gdps/cmd_vel_local")
            cmd_topic = str(self.get_parameter("cmd_vel_topic").value)
            self.cmd_pub = self.create_publisher(Twist, cmd_topic, 10)
            self.status_pub = self.create_publisher(String, "/gdps/nav_status", 10)
            self.create_timer(0.1, self._tick)
            self.get_logger().warn(
                "local_avoid only; full Nav2 is a separate launch and still dry-run by default"
            )

        def _on_scan(self, msg: LaserScan) -> None:
            self.nav.on_scan(
                ScanFrame(
                    ranges=tuple(float(x) for x in msg.ranges),
                    angle_min=float(msg.angle_min),
                    angle_increment=float(msg.angle_increment),
                    range_min=float(msg.range_min),
                    range_max=float(msg.range_max),
                    frame_id=msg.header.frame_id,
                )
            )

        def _on_goal(self, msg: PoseStamped) -> None:
            yaw = _yaw_from_quat(msg.pose.orientation)
            self.nav.set_goal(
                Pose2D(
                    x=msg.pose.position.x,
                    y=msg.pose.position.y,
                    yaw=yaw,
                    frame_id=msg.header.frame_id,
                )
            )
            self.nav.start()

        def _on_stop(self, _msg: String) -> None:
            self.nav.stop("ros_manual_stop")

        def _on_hb(self, _msg: String) -> None:
            self.nav.on_heartbeat()

        def _tick(self) -> None:
            cmd = self.nav.step()
            msg = Twist()
            msg.linear.x = cmd.vx
            msg.linear.y = cmd.vy
            msg.angular.z = cmd.wz
            self.cmd_pub.publish(msg)
            st = self.nav.get_status()
            self.status_pub.publish(
                String(
                    data=(
                        f"state={st.state.value} mode={st.mode} cap={st.capability.value} "
                        f"decision={st.last_decision} halt={st.halt} code={st.last_return_code}"
                    )
                )
            )

        def destroy_node(self) -> bool:
            self.nav.stop("node_shutdown")
            self.nav.adapter.close()
            return super().destroy_node()

    def _yaw_from_quat(q) -> float:
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny_cosp, cosy_cosp)

    rclpy.init()
    node = LocalNavigator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
