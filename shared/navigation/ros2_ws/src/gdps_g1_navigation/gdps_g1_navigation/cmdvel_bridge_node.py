"""Relay /gdps/cmd_vel_local (and optional /cmd_vel) through G1MotionAdapter (dry-run default).

Only one bridge + one navigator with motion lock should run on the robot.
"""

from __future__ import annotations

from .repo_path import ensure_repo_on_path


def main() -> None:
    ensure_repo_on_path()
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from std_msgs.msg import String

    from shared.navigation.factory import build_navigator, load_nav_config
    from shared.robot_control.g1.command import VelocityCommand

    class CmdVelBridge(Node):
        def __init__(self) -> None:
            super().__init__("gdps_cmdvel_bridge")
            cfg = load_nav_config()
            self.nav = build_navigator(cfg)
            self.declare_parameter("input_topic", "/gdps/cmd_vel_local")
            self.declare_parameter("also_listen_cmd_vel", True)
            in_topic = str(self.get_parameter("input_topic").value)
            self.create_subscription(Twist, in_topic, self._on_cmd, 10)
            if bool(self.get_parameter("also_listen_cmd_vel").value):
                self.create_subscription(Twist, "/cmd_vel", self._on_cmd, 10)
            self.create_subscription(String, "/gdps/manual_stop", self._on_stop, 10)
            self.pub = self.create_publisher(Twist, "/gdps/cmd_vel_filtered", 10)
            self.create_timer(0.05, self._watchdog)
            self.get_logger().warn(
                f"cmd_vel bridge in={in_topic} mode={self.nav.adapter.mode.value} "
                "(dry-run: no hardware SetVelocity)"
            )

        def _on_cmd(self, msg: Twist) -> None:
            cmd = VelocityCommand(
                vx=msg.linear.x,
                vy=msg.linear.y,
                wz=msg.angular.z,
                source="ros_cmd_vel",
            )
            self.nav.adapter.send_velocity(cmd)
            out = Twist()
            last = self.nav.adapter.last_command
            if last is not None:
                out.linear.x = last.vx
                out.linear.y = last.vy
                out.angular.z = last.wz
            self.pub.publish(out)

        def _on_stop(self, _msg: String) -> None:
            self.nav.stop("ros_manual_stop")

        def _watchdog(self) -> None:
            self.nav.adapter.watchdog_tick()

        def destroy_node(self) -> bool:
            self.nav.adapter.close()
            return super().destroy_node()

    rclpy.init()
    node = CmdVelBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
