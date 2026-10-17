from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Type

from gdps_qi.adapters.readonly.ros2_session import ros2_spin_once_subscribe


def probe_ros2_topic_once(
    topic: str,
    msg_type: Type[Any],
    timeout_s: float = 3.0,
    store_payload: bool = False,
) -> Dict[str, object]:
    if not topic:
        return {"ok": False, "error": "empty_topic"}
    received: Dict[str, object] = {}

    def _cb(msg: Any) -> None:
        if received:
            return
        received["host_received_at"] = time.time()
        received["msg_summary"] = summarize_ros_message(msg)
        if store_payload:
            received["msg"] = msg

    ok, err = ros2_spin_once_subscribe(topic, msg_type, _cb, timeout_s)
    result: Dict[str, object] = {
        "ok": ok,
        "topic": topic,
        "msg_type": getattr(msg_type, "__name__", str(msg_type)),
    }
    if not ok:
        result["error"] = err or "timeout"
        return result
    result.update(received)
    return result


def summarize_ros_message(msg: Any) -> Dict[str, object]:
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
        out["is_bigendian"] = int(getattr(msg, "is_bigendian", 0))
        out["step"] = int(getattr(msg, "step", 0))
        data = getattr(msg, "data", None)
        out["data_length"] = len(data) if data is not None else 0
    if hasattr(msg, "name") and hasattr(msg, "position"):
        names = [str(n) for n in msg.name]
        pos = [float(p) for p in msg.position]
        out["joint_count"] = len(names)
        out["joint_names"] = names
        out["joint_positions"] = pos
        if hasattr(msg, "velocity"):
            out["joint_velocities"] = [float(v) for v in msg.velocity]
    if hasattr(msg, "k"):
        out["distortion_model"] = getattr(msg, "distortion_model", "")
        out["k"] = [float(x) for x in msg.k]
        out["d"] = [float(x) for x in getattr(msg, "d", [])]
        out["r"] = [float(x) for x in getattr(msg, "r", [])]
        out["p"] = [float(x) for x in getattr(msg, "p", [])]
        out["width"] = int(getattr(msg, "width", 0))
        out["height"] = int(getattr(msg, "height", 0))
    if hasattr(msg, "pose"):
        p = msg.pose.pose.position
        out["position"] = [float(p.x), float(p.y), float(p.z)]
    return out


def joint_state_from_summary(summary: Dict[str, object], mapping_basis: str) -> "JointSnapshot":
    from gdps_qi.adapters.readonly.joint_snapshot import JointSnapshot, JointValidity

    names = summary.get("joint_names")
    pos = summary.get("joint_positions")
    if not isinstance(names, list) or not isinstance(pos, list):
        return JointSnapshot({}, None, "ros_joint_state", JointValidity.UNKNOWN, mapping_basis)
    if len(names) != len(pos):
        return JointSnapshot({}, summary.get("stamp_sec"), "ros_joint_state", JointValidity.UNKNOWN, mapping_basis)
    positions = {str(n): float(p) for n, p in zip(names, pos)}
    stamp = summary.get("stamp_sec")
    stamp_f = float(stamp) if stamp is not None else None
    return JointSnapshot(
        positions=positions,
        stamp_sec=stamp_f,
        source="ros_joint_state",
        validity=JointValidity.VALID if positions else JointValidity.UNKNOWN,
        mapping_basis=mapping_basis,
        raw_joint_count=len(positions),
    )
