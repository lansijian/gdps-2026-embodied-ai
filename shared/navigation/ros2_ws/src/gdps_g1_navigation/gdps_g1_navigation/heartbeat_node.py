"""Host heartbeat for SSH/network-loss detection on the robot.

Run this on the development PC. If it stops, the robot-side navigator treats
heartbeat as stale and commands StopMove. This is software stop, not E-stop.
"""

from __future__ import annotations


def main() -> None:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    class Heartbeat(Node):
        def __init__(self) -> None:
            super().__init__("gdps_host_heartbeat")
            self.pub = self.create_publisher(String, "/gdps/host_heartbeat", 10)
            self.create_timer(0.2, self._tick)

        def _tick(self) -> None:
            self.pub.publish(String(data="host-alive"))

    rclpy.init()
    node = Heartbeat()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
