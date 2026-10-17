#!/usr/bin/env python3
"""Read-only G1 hardware diagnostics -> JSON (dry-run by default)."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QI = ROOT / "tracks" / "quality-inspection"
if str(QI) not in sys.path:
    sys.path.insert(0, str(QI))

from gdps_qi.adapters.readonly.dds_readonly import DdsReadOnlyConfig
from gdps_qi.adapters.readonly.dex3_state import Dex3StateReadOnly
from gdps_qi.adapters.readonly.head_camera import CameraReadOnlyConfig, HeadCameraReadOnly
from gdps_qi.adapters.readonly.robot_state import RobotStateReadOnly
from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel
from gdps_qi.kinematics.kinematics_backend import G1UrdfKinematicsAdapter


def _load_topics_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {"_yaml_error": str(exc)}


def _compat_probe() -> dict:
    out = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "pinocchio": False,
        "opencv": False,
        "rclpy": False,
        "unitree_sdk2py": False,
    }
    try:
        import pinocchio  # noqa: F401

        out["pinocchio"] = True
    except ImportError:
        pass
    try:
        import cv2  # noqa: F401

        out["opencv"] = True
    except ImportError:
        pass
    try:
        import rclpy  # noqa: F401

        out["rclpy"] = True
    except ImportError:
        pass
    try:
        import unitree_sdk2py  # noqa: F401

        out["unitree_sdk2py"] = True
    except ImportError:
        pass
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="GDPS QI read-only hardware diagnostics")
    parser.add_argument("--live", action="store_true", help="Subscribe on robot (manual on-site only)")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument(
        "--config",
        type=str,
        default=str(ROOT / "tracks/quality-inspection/configs/g1/qi_topics_readonly.example.yaml"),
    )
    args = parser.parse_args()

    cfg = _load_topics_config(Path(args.config))
    ros = cfg.get("ros2", {})
    dds = cfg.get("unitree_dds", {})
    cam_cfg_yaml = cfg.get("camera", {}) or {}
    dds_cfg = DdsReadOnlyConfig(
        domain_id=int(dds.get("domain_id", 0)),
        network_interface=str(dds.get("network_interface", "")),
    )
    cam_cfg = CameraReadOnlyConfig(
        depth_scale_m=cam_cfg_yaml.get("depth_scale_m"),
        allow_16uc1_depth=bool(cam_cfg_yaml.get("allow_16uc1_depth", False)),
        treat_mono16_as_depth=bool(cam_cfg_yaml.get("treat_mono16_as_depth", False)),
        max_rgb_depth_stamp_delta_s=float(cam_cfg_yaml.get("max_rgb_depth_stamp_delta_s", 0.05)),
    )

    cam = HeadCameraReadOnly(
        ros_rgb_topic=str(ros.get("rgb_image", "")),
        ros_depth_topic=str(ros.get("depth_image", "")),
        ros_camera_info_topic=str(ros.get("camera_info", "")),
        camera_cfg=cam_cfg,
    )
    robot = RobotStateReadOnly(
        robot_variant=str(cfg.get("robot_variant", "G1_UNKNOWN")),
        joint_state_topic=str(ros.get("joint_states", "")),
        dog_odom_topic=str(ros.get("dog_odom", "/dog_odom")),
        lowstate_dds_topic=str(dds.get("lowstate", "")),
        expected_dof=int(cfg.get("expected_body_dof", 29)),
        dds_cfg=dds_cfg,
    )
    dex3 = Dex3StateReadOnly(
        hand_state_topic_left=str(dds.get("dex3_state_left", "rt/lf/dex3/state")),
        hand_state_topic_right=str(dds.get("dex3_state_right", "rt/rf/dex3/state")),
        dds_cfg=dds_cfg,
    )

    urdf_path = os.environ.get("GDPS_G1_URDF_PATH", "")
    urdf_report = {"path": urdf_path, "loaded": False, "error": ""}
    kin = G1UrdfKinematicsAdapter(urdf_path=urdf_path or None)
    urdf_report["kind"] = kin.kind.value
    if urdf_path:
        m = G1UrdfModel(urdf_path)
        urdf_report["loaded"] = m.load()
        urdf_report["error"] = m.load_error

    report = {
        "generated_at": time.time(),
        "mode": "live_readonly" if args.live else "dry_run_schema",
        "config_path": args.config,
        "compatibility": _compat_probe(),
        "urdf": urdf_report,
        "devices": {
            "head_camera": cam.probe(args.live, args.timeout),
            "robot_state": robot.probe(args.live, args.timeout),
            "dex3": dex3.probe(args.live, args.timeout),
        },
        "notes": [
            "Bare DDS apps may not appear in ros2 node list",
            "Do not infer motor services from node list alone",
            "All writes disabled in gdps_qi",
        ],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
