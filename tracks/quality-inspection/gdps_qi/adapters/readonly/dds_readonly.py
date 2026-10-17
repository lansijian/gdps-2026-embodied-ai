from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional


def subscribe_dds_once(
    topic: str,
    message_type: Any,
    timeout_s: float,
    parser: Callable[[Any], Dict[str, object]],
) -> Dict[str, object]:
    """One-shot DDS read via unitree_sdk2py. No publishers."""
    if not topic:
        return {"ok": False, "error": "empty_topic"}
    try:
        from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize  # type: ignore
    except ImportError as exc:
        return {"ok": False, "error": f"unitree_sdk2py_unavailable:{exc}"}

    payload: Dict[str, object] = {}
    got = False

    def handler(msg: Any) -> None:
        nonlocal got
        if got:
            return
        payload.update(parser(msg))
        payload["host_received_at"] = time.time()
        got = True

    try:
        ChannelFactoryInitialize(0)
        sub = ChannelSubscriber(topic, message_type)
        sub.Init(handler, 1)
        t0 = time.time()
        while not got and (time.time() - t0) < timeout_s:
            time.sleep(0.02)
        sub.Close()
        if not got:
            return {"ok": False, "error": "timeout", "topic": topic}
        return {"ok": True, "topic": topic, **payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "topic": topic}


def parse_lowstate_motors(msg: Any, index_map: Dict[int, str]) -> Dict[str, object]:
    motors = getattr(msg, "motor_state", None) or getattr(msg, "motorState", None)
    if motors is None:
        return {"motor_count": 0, "positions": {}, "validity": "UNKNOWN"}
    positions: Dict[str, float] = {}
    for idx, name in index_map.items():
        if idx >= len(motors):
            continue
        m = motors[idx]
        q = getattr(m, "q", None)
        if q is None:
            continue
        positions[name] = float(q)
    return {
        "motor_count": len(motors),
        "positions": positions,
        "validity": "PARTIAL" if positions else "UNKNOWN",
    }


def parse_hand_state(msg: Any, side: str) -> Dict[str, object]:
    motors = getattr(msg, "motor_state", None) or getattr(msg, "motorState", None)
    if motors is None:
        return {"side": side, "validity": "UNKNOWN", "joint_positions": []}
    joints: List[float] = []
    for m in motors[:7]:
        joints.append(float(getattr(m, "q", 0.0)))
    return {
        "side": side,
        "joint_positions": joints,
        "validity": "VALID" if joints else "UNKNOWN",
        "current": [float(getattr(m, "dq", 0.0)) for m in motors[:7]],
    }
