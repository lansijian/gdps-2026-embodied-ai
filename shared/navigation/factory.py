from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.navigation.api.navigator import NavCapability, SharedNavigator
from shared.navigation.perception.obstacle_monitor import ObstacleMonitor
from shared.navigation.safety.supervisor import SafetySupervisor
from shared.robot_control.g1.adapter import AdapterLimits, G1MotionAdapter, MotionMode
from shared.robot_control.g1.mock_backend import MockLocoBackend
from shared.utils.config_loader import load_mapping, repo_root


def default_config_path() -> Path:
    return repo_root() / "configs" / "g1" / "navigation" / "safety.json"


def load_nav_config(path: str | Path | None = None) -> dict[str, Any]:
    return load_mapping(path or default_config_path())


def build_navigator(config: dict[str, Any] | None = None) -> SharedNavigator:
    cfg = config or load_nav_config()
    backend_name = str(cfg.get("backend", "mock"))
    if backend_name == "mock":
        backend = MockLocoBackend()
    elif backend_name == "unitree_loco":
        from shared.robot_control.g1.loco_backend import UnitreeLocoBackend

        iface = str(cfg.get("network_interface") or "")
        backend = UnitreeLocoBackend(network_interface=iface)
    else:
        raise ValueError(
            f"backend {backend_name!r} cannot be constructed without a ROS node; "
            "use mock or unitree_loco from this factory"
        )
    live_max_vy = float(cfg.get("max_vy", 0.00))
    dry_vy = float(cfg.get("lateral_dryrun_max_vy", 0.0))
    mode_str = str(cfg.get("mode", "dry-run"))
    effective_vy = dry_vy if mode_str == "dry-run" else live_max_vy
    limits = AdapterLimits(
        max_vx=float(cfg.get("max_vx", 0.10)),
        max_vy=effective_vy,
        max_wz=float(cfg.get("max_wz", 0.15)),
        command_timeout_s=float(cfg.get("command_timeout_s", 0.25)),
        command_duration_s=float(cfg.get("command_duration_s", 1.0)),
    )
    lock_path = cfg.get("motion_lock_path")
    adapter = G1MotionAdapter(
        backend=backend,
        owner=str(cfg.get("lock_owner", "gdps_g1_navigation")),
        limits=limits,
        mode=MotionMode.DRY_RUN,
        live_token=str(cfg.get("live_token", "")),
        lock_path=str(lock_path) if lock_path else None,
    )
    adapter._live_max_vy = live_max_vy  # type: ignore[attr-defined]
    adapter.connect()
    safety = SafetySupervisor(
        sensor_timeout_s=float(cfg.get("sensor_timeout_s", 0.5)),
        odom_timeout_s=float(cfg.get("odom_timeout_s", 0.5)),
        tf_timeout_s=float(cfg.get("tf_timeout_s", 0.5)),
        heartbeat_timeout_s=float(cfg.get("heartbeat_timeout_s", 1.0)),
        require_sensor=bool(cfg.get("require_sensor", True)),
        require_odom=bool(cfg.get("require_odom", False)),
        require_tf=bool(cfg.get("require_tf", False)),
        require_heartbeat=bool(cfg.get("require_heartbeat", False)),
    )
    obstacles = ObstacleMonitor(
        stop_distance_m=float(cfg.get("stop_distance_m", 0.60)),
        slow_distance_m=float(cfg.get("slow_distance_m", 1.20)),
        forward_half_angle_rad=float(cfg.get("forward_half_angle_rad", 0.60)),
        forward_angle_offset_rad=float(cfg.get("lidar_forward_angle_offset_rad", 0.0)),
        frame_extrinsic_verified=bool(cfg.get("lidar_frame_extrinsic_verified", False)),
    )
    if bool(cfg.get("field_require_heartbeat", False)):
        safety.require_heartbeat = True
    if bool(cfg.get("field_require_odom", False)):
        safety.require_odom = True
    if bool(cfg.get("field_require_tf", False)):
        safety.require_tf = True
    return SharedNavigator(
        adapter=adapter,
        safety=safety,
        obstacles=obstacles,
        capability=NavCapability.LOCAL_AVOID,
        cruise_vx=float(cfg.get("cruise_vx", 0.08)),
        detour_wz=float(cfg.get("detour_wz", 0.12)),
        allow_auto_forward=bool(cfg.get("allow_auto_forward", False)),
    )
