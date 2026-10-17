from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

_DDS_INIT_LOCK = threading.Lock()
_DDS_INITIALIZED = False
_DDS_INIT_KEY: Optional[Tuple[int, str]] = None

DEX3_EXPECTED_JOINTS = 7


@dataclass(frozen=True)
class DdsReadOnlyConfig:
    domain_id: int = 0
    network_interface: str = ""
    """e.g. eth0 on G1 PC2; empty = SDK default (must be set on robot)."""


def reset_dds_factory_state_for_tests() -> None:
    global _DDS_INITIALIZED, _DDS_INIT_KEY
    with _DDS_INIT_LOCK:
        _DDS_INITIALIZED = False
        _DDS_INIT_KEY = None


def init_dds_factory(cfg: DdsReadOnlyConfig) -> None:
    global _DDS_INITIALIZED, _DDS_INIT_KEY
    iface = (cfg.network_interface or "").strip()
    key = (cfg.domain_id, iface)
    with _DDS_INIT_LOCK:
        if _DDS_INITIALIZED and _DDS_INIT_KEY == key:
            return
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # type: ignore

        if iface:
            ChannelFactoryInitialize(cfg.domain_id, iface)
        else:
            ChannelFactoryInitialize(cfg.domain_id)
        _DDS_INITIALIZED = True
        _DDS_INIT_KEY = key


def _finite_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _message_stamp_sec(msg: Any) -> Optional[float]:
    for attr in ("tick", "crc"):
        pass
    imu = getattr(msg, "imu_state", None)
    if imu is not None:
        # LowState carries IMU; no universal hand message stamp in IDL — use host time as fallback only in meta
        pass
    return None


def _motor_q_dq_tau(m: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    q = _finite_float(getattr(m, "q", None))
    dq = _finite_float(getattr(m, "dq", None))
    tau = _finite_float(getattr(m, "tau_est", None))
    if tau is None:
        tau = _finite_float(getattr(m, "tau", None))
    return q, dq, tau


def subscribe_dds_once(
    topic: str,
    message_type: Any,
    timeout_s: float,
    parser: Callable[[Any], Dict[str, object]],
    dds_cfg: Optional[DdsReadOnlyConfig] = None,
) -> Dict[str, object]:
    """One-shot DDS read via unitree_sdk2py. No publishers."""
    if not topic:
        return {"ok": False, "error": "empty_topic"}
    try:
        from unitree_sdk2py.core.channel import ChannelSubscriber  # type: ignore
    except ImportError as exc:
        return {"ok": False, "error": f"unitree_sdk2py_unavailable:{exc}"}

    payload: Dict[str, object] = {}
    got = False
    sub: Any = None

    def handler(msg: Any) -> None:
        nonlocal got
        if got:
            return
        payload.update(parser(msg))
        payload["host_received_at"] = time.time()
        got = True

    try:
        init_dds_factory(dds_cfg or DdsReadOnlyConfig())
        sub = ChannelSubscriber(topic, message_type)
        sub.Init(handler, 1)
        t0 = time.time()
        while not got and (time.time() - t0) < timeout_s:
            time.sleep(0.02)
        if sub is not None:
            try:
                sub.Close()
            except Exception:
                pass
        if not got:
            return {"ok": False, "error": "timeout", "topic": topic}
        if payload.get("validity") == "INVALID" or payload.get("reject"):
            return {
                "ok": False,
                "error": str(payload.get("error", "invalid_message")),
                "topic": topic,
                **{k: v for k, v in payload.items() if k not in ("reject",)},
            }
        return {"ok": True, "topic": topic, **payload}
    except Exception as exc:
        if sub is not None:
            try:
                sub.Close()
            except Exception:
                pass
        return {"ok": False, "error": str(exc), "topic": topic}


def parse_lowstate_motors(
    msg: Any,
    index_map: Dict[int, str],
    expected_dof: Optional[int] = None,
) -> Dict[str, object]:
    motors = getattr(msg, "motor_state", None) or getattr(msg, "motorState", None)
    if motors is None:
        return {
            "motor_count": 0,
            "positions": {},
            "validity": "UNKNOWN",
            "reject": True,
            "error": "missing_motor_state",
        }
    motor_count = len(motors)
    min_needed = (max(index_map.keys()) + 1) if index_map else 0
    if motor_count < min_needed:
        return {
            "motor_count": motor_count,
            "positions": {},
            "validity": "INVALID",
            "reject": True,
            "error": "motor_array_too_short",
            "min_needed": min_needed,
        }
    if expected_dof is not None and motor_count < expected_dof:
        return {
            "motor_count": motor_count,
            "positions": {},
            "validity": "INVALID",
            "reject": True,
            "error": "dof_below_expected",
            "expected_dof": expected_dof,
        }
    positions: Dict[str, float] = {}
    missing_indices: List[int] = []
    invalid_indices: List[int] = []
    for idx, name in index_map.items():
        if idx >= motor_count:
            missing_indices.append(idx)
            continue
        q, dq, tau = _motor_q_dq_tau(motors[idx])
        if q is None:
            invalid_indices.append(idx)
            continue
        positions[name] = q
    validity = "UNKNOWN"
    if positions and (missing_indices or invalid_indices):
        validity = "PARTIAL"
    elif positions and not missing_indices and not invalid_indices:
        validity = "PARTIAL"
    if not positions:
        validity = "UNKNOWN"
    out: Dict[str, object] = {
        "motor_count": motor_count,
        "positions": positions,
        "validity": validity,
        "mapping_basis": "documented_index_map_unverified_on_robot",
        "missing_indices": missing_indices,
        "invalid_indices": invalid_indices,
    }
    if missing_indices or invalid_indices:
        out["reject"] = True
        out["error"] = "incomplete_lowstate_mapping"
    return out


def _parse_press_sensors(msg: Any) -> List[Dict[str, object]]:
    press = getattr(msg, "press_sensor_state", None) or getattr(msg, "pressSensorState", None)
    if not press:
        return []
    out: List[Dict[str, object]] = []
    for i, ps in enumerate(press[:DEX3_EXPECTED_JOINTS]):
        entry: Dict[str, object] = {"index": i}
        for field in ("pressure", "temperature"):
            if hasattr(ps, field):
                entry[field] = getattr(ps, field)
        out.append(entry)
    return out


def parse_hand_state(msg: Any, side: str) -> Dict[str, object]:
    """Unitree HG HandState_: motor_state[7] with q, dq, tau_est (N·m); tactile in press_sensor_state."""
    motors = getattr(msg, "motor_state", None) or getattr(msg, "motorState", None)
    if motors is None:
        return {
            "side": side,
            "validity": "UNKNOWN",
            "reject": True,
            "error": "missing_motor_state",
            "joint_positions": None,
        }
    if len(motors) != DEX3_EXPECTED_JOINTS:
        return {
            "side": side,
            "validity": "INVALID",
            "reject": True,
            "error": "motor_count_not_7",
            "motor_count": len(motors),
            "joint_positions": None,
        }
    positions: List[float] = []
    velocities: List[float] = []
    torques: List[Optional[float]] = []
    bad: List[int] = []
    for i, m in enumerate(motors):
        q, dq, tau = _motor_q_dq_tau(m)
        if q is None or dq is None:
            bad.append(i)
            continue
        positions.append(q)
        velocities.append(dq)
        torques.append(tau)
    if bad or len(positions) != DEX3_EXPECTED_JOINTS:
        return {
            "side": side,
            "validity": "UNKNOWN",
            "reject": True,
            "error": "incomplete_joint_q",
            "invalid_joint_indices": bad,
            "joint_positions": None,
            "joint_velocities": None,
        }
    tactile = _parse_press_sensors(msg)
    stamp = _message_stamp_sec(msg)
    return {
        "side": side,
        "validity": "DOCUMENTED_UNVERIFIED",
        "joint_positions": positions,
        "joint_velocities": velocities,
        "estimated_torque_nm": torques,
        "tactile_press_sensors": tactile if tactile else None,
        "message_stamp_sec": stamp,
        "idl_note": "HG MotorState has q,dq,tau_est; no motor current field in IDL",
    }
