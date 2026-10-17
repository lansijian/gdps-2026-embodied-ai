from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Type


def probe_ros2_topic_once(
    topic: str,
    msg_type: Type[Any],
    timeout_s: float = 3.0,
) -> Dict[str, object]:
    """Subscribe once on Foxy. Safe to call off-robot (returns import errors)."""
    if not topic:
        return {"ok": False, "error": "empty_topic"}
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
    except ImportError as exc:
        return {"ok": False, "error": f"rclpy_unavailable:{exc}"}

    result: Dict[str, object] = {"ok": False, "topic": topic, "msg_type": str(msg_type)}
    received: Dict[str, object] = {}

    class _OnceSub(Node):
        def __init__(self) -> None:
            super().__init__("gdps_qi_readonly_probe")
            self._sub = self.create_subscription(
                msg_type, topic, self._cb, qos_profile_sensor_data
            )

        def _cb(self, msg: Any) -> None:
            if received:
                return
            received["stamp"] = time.time()
            received["msg_summary"] = _summarize_msg(msg)

    rclpy.init(args=None)
    node = _OnceSub()
    t0 = time.time()
    try:
        while not received and (time.time() - t0) < timeout_s:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if not received:
        result["error"] = "timeout"
        return result
    result["ok"] = True
    result.update(received)
    return result


def _summarize_msg(msg: Any) -> Dict[str, object]:
    out: Dict[str, object] = {"type": type(msg).__name__}
    if hasattr(msg, "header"):
        h = msg.header
        out["frame_id"] = getattr(h, "frame_id", "")
        stamp = getattr(h, "stamp", None)
        if stamp is not None:
            out["stamp_sec"] = float(stamp.sec) + float(stamp.nanosec) * 1e-9
    if hasattr(msg, "height") and hasattr(msg, "width"):
        out["height"] = int(msg.height)
        out["width"] = int(msg.width)
        out["encoding"] = getattr(msg, "encoding", "")
    if hasattr(msg, "name") and hasattr(msg, "position"):
        names = list(msg.name)
        out["joint_count"] = len(names)
        out["joint_names_sample"] = names[:12]
    if hasattr(msg, "k"):
        k = list(msg.k)
        out["camera_k"] = k[:4]
        out["distortion_model"] = getattr(msg, "distortion_model", "")
    if hasattr(msg, "pose"):
        p = msg.pose.pose.position
        out["position"] = [p.x, p.y, p.z]
    return out
