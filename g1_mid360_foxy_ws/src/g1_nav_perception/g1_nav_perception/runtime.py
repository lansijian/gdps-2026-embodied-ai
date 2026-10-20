"""Graceful Foxy shutdown; ignore repeated Ctrl-C only during cleanup."""
import signal
import rclpy


def spin(node):
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
