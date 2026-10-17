from __future__ import annotations

import time
from typing import Any, Callable, Optional, Type


def ros2_spin_once_subscribe(
    topic: str,
    msg_type: Type[Any],
    on_message: Callable[[Any], None],
    timeout_s: float,
) -> tuple:
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
    except ImportError as exc:
        return False, f"rclpy_unavailable:{exc}"

    node: Optional[Node] = None
    initialized = False
    received = False

    def _cb(msg: Any) -> None:
        nonlocal received
        if received:
            return
        on_message(msg)
        received = True

    try:
        if not rclpy.ok():
            rclpy.init(args=None)
            initialized = True

        class _Sub(Node):
            def __init__(self) -> None:
                super().__init__("gdps_qi_readonly_sub")
                self.create_subscription(msg_type, topic, _cb, qos_profile_sensor_data)

        node = _Sub()
        t0 = time.time()
        while not received and (time.time() - t0) < timeout_s:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not received:
            return False, "timeout"
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        if node is not None:
            node.destroy_node()
        if initialized:
            try:
                import rclpy

                rclpy.shutdown()
            except Exception:
                pass
