#!/usr/bin/env python3
"""Unified field gate checks (read-only / dry-run). JSON + human summary."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
QI = ROOT / "tracks" / "quality-inspection"
if str(QI) not in sys.path:
    sys.path.insert(0, str(QI))


def _summary(gates: Dict[str, Any]) -> str:
    lines = ["GDPS Field Gate Summary", "========================"]
    for name, rep in gates.items():
        st = rep.get("status", "UNKNOWN")
        lines.append(f"{name}: {st}")
        for err in rep.get("errors", [])[:5]:
            lines.append(f"  - {err}")
    return "\n".join(lines)


def gate0_preflight() -> Dict[str, Any]:
    rep: Dict[str, Any] = {"status": "OK", "errors": [], "reads": [], "writes": []}
    rep["reads"].extend(["python version", "optional: rclpy, unitree_sdk2py, pinocchio"])
    rep["writes"] = []
    rep["python"] = platform.python_version()
    rep["machine"] = platform.machine()
    for mod in ("rclpy", "numpy", "yaml", "unitree_sdk2py", "pinocchio", "cv2"):
        try:
            __import__(mod)
            rep[mod] = True
        except ImportError:
            rep[mod] = False
    nav_cfg = ROOT / "configs/g1/navigation/safety.json"
    rep["safety_config"] = str(nav_cfg)
    if nav_cfg.is_file():
        rep["safety_mode"] = json.loads(nav_cfg.read_text(encoding="utf-8")).get("mode")
    else:
        rep["status"] = "FAIL"
        rep["errors"].append("missing safety.json")
    if os.environ.get("GDPS_G1_LIVE") == "1":
        rep["status"] = "WARN"
        rep["errors"].append("GDPS_G1_LIVE=1 set; gates remain read-only but verify intent")
    return rep


def gate1_lidar(args: argparse.Namespace) -> Dict[str, Any]:
    rep: Dict[str, Any] = {
        "status": "SKIPPED",
        "errors": [],
        "reads": [args.pc_topic, args.scan_topic],
        "writes": [],
    }
    if not args.live:
        rep["note"] = "use --live on robot to probe topics"
        return rep
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import LaserScan, PointCloud2
    except ImportError as exc:
        rep["status"] = "FAIL"
        rep["errors"].append(f"ros2 deps: {exc}")
        return rep
    qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=5)
    got: Dict[str, Any] = {}

    class P(Node):
        def __init__(self) -> None:
            super().__init__("gdps_gate1")
            self.create_subscription(PointCloud2, args.pc_topic, lambda m: self._hit("pc", m), qos)
            self.create_subscription(LaserScan, args.scan_topic, lambda m: self._hit("scan", m), qos)
            self.deadline = time.time() + args.timeout

        def _hit(self, key: str, msg) -> None:
            if key in got:
                return
            if key == "pc":
                got[key] = {
                    "frame_id": msg.header.frame_id,
                    "width": msg.width,
                    "height": msg.height,
                    "point_step": msg.point_step,
                    "fields": [f.name for f in msg.fields],
                }
            else:
                got[key] = {
                    "frame_id": msg.header.frame_id,
                    "ranges": len(msg.ranges),
                    "angle_min": msg.angle_min,
                    "angle_max": msg.angle_max,
                }

    rclpy.init()
    node = P()
    while time.time() < node.deadline and len(got) < 2:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.shutdown()
    rep["samples"] = got
    rep["status"] = "OK" if got else "FAIL"
    if not got:
        rep["errors"].append("no lidar messages before timeout")
    rep["extrinsic_verified"] = False
    rep["note"] = "livox_frame->base forward distance NOT calibrated unless extrinsic verified"
    return rep


def gate2_obstacle(args: argparse.Namespace) -> Dict[str, Any]:
    from shared.navigation.perception.obstacle_monitor import AvoidDecision, ObstacleMonitor, ScanFrame

    rep: Dict[str, Any] = {"status": "OK", "errors": [], "reads": ["/scan synthetic"], "writes": []}
    mon = ObstacleMonitor()
    cases = [
        ("stop", 0.5, AvoidDecision.STOP),
        ("slow", 0.9, AvoidDecision.SLOW),
        ("clear", 5.0, AvoidDecision.CLEAR),
    ]
    n = 21
    results = []
    for label, dist, expected in cases:
        ranges = [10.0] * n
        ranges[n // 2] = dist
        scan = ScanFrame(
            ranges=tuple(ranges),
            angle_min=-0.5,
            angle_increment=1.0 / (n - 1),
        )
        got = mon.update(scan)
        ok = got == expected or (expected == AvoidDecision.SLOW and got in {AvoidDecision.SLOW, AvoidDecision.DETOUR_LEFT, AvoidDecision.DETOUR_RIGHT})
        results.append({"case": label, "expected": expected.value, "got": got.value, "ok": ok})
    rep["table"] = results
    if not all(r["ok"] for r in results):
        rep["status"] = "FAIL"
        rep["errors"].append("obstacle decision table mismatch")
    return rep


def gate3_camera(args: argparse.Namespace) -> Dict[str, Any]:
    from gdps_qi.adapters.readonly.head_camera import HeadCameraReadOnly

    rep: Dict[str, Any] = {"status": "DRY_RUN", "errors": [], "reads": [], "writes": []}
    cam = HeadCameraReadOnly(
        ros_rgb_topic=args.rgb_topic,
        ros_depth_topic=args.depth_topic,
        ros_camera_info_topic=args.camera_info_topic,
    )
    rep["probe"] = cam.probe(args.live, args.timeout)
    rep["reads"] = [t for t in (args.rgb_topic, args.depth_topic, args.camera_info_topic) if t]
    rep["status"] = "OK" if rep["probe"].get("decode_ok") or not args.live else "UNKNOWN"
    return rep


def gate4_motion_readonly(args: argparse.Namespace) -> Dict[str, Any]:
    from shared.navigation.factory import build_navigator, load_nav_config

    rep: Dict[str, Any] = {"status": "OK", "errors": [], "reads": ["safety.json", "motion lock"], "writes": []}
    cfg = load_nav_config()
    rep["backend"] = cfg.get("backend")
    rep["mode"] = cfg.get("mode")
    rep["max_vy_live"] = cfg.get("max_vy")
    rep["lateral_dryrun_max_vy"] = cfg.get("lateral_dryrun_max_vy")
    nav = build_navigator(cfg)
    rep["adapter_mode"] = nav.adapter.mode.value
    rep["connect_code"] = nav.adapter.last_return_code
    if nav.adapter.last_return_code not in (0, None):
        rep["status"] = "FAIL"
        rep["errors"].append(f"motion lock/connect: {nav.adapter.last_error}")
    nav.adapter.close()
    rep["note"] = "no SetVelocity; connect only validates lock/backend"
    return rep


def gate5_motion_dryrun_fixed(args: argparse.Namespace) -> Dict[str, Any]:
    from shared.navigation.api.navigator import MotionIntent
    from shared.navigation.api.types import Pose2D
    from shared.navigation.factory import build_navigator
    from shared.navigation.perception.obstacle_monitor import ScanFrame

    rep: Dict[str, Any] = {"status": "OK", "errors": [], "previews": [], "writes": ["adapter.dry_run_history"]}
    nav = build_navigator()
    nav.safety.require_sensor = False
    nav.safety.require_odom = False
    nav.on_scan(
        ScanFrame(
            ranges=tuple([8.0] * 21),
            angle_min=-0.5,
            angle_increment=0.05,
        )
    )
    nav.on_pose(Pose2D(0, 0, 0, "odom"))
    nav.start()
    for intent in (
        MotionIntent.CRUISE_FORWARD,
        MotionIntent.BACKWARD,
        MotionIntent.LATERAL_LEFT,
        MotionIntent.LATERAL_RIGHT,
        MotionIntent.ROTATE_IN_PLACE,
    ):
        cmd = nav.preview_motion(intent, speed_scale=0.5)
        rep["previews"].append(
            {"intent": intent.value, "vx": cmd.vx, "vy": cmd.vy, "wz": cmd.wz, "source": cmd.source}
        )
    rep["history_len"] = len(nav.adapter.dry_run_history)
    nav.adapter.close()
    if nav.adapter.mode.value != "dry-run":
        rep["status"] = "FAIL"
        rep["errors"].append("not dry-run")
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description="GDPS field gate checker")
    parser.add_argument("--gate", type=str, default="all", help="0,1,2,3,4,5,all")
    parser.add_argument("--live", action="store_true", help="ROS live probes (robot only)")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--pc-topic", default="/utlidar/cloud_livox_mid360")
    parser.add_argument("--scan-topic", default="/scan")
    parser.add_argument("--rgb-topic", default="")
    parser.add_argument("--depth-topic", default="")
    parser.add_argument("--camera-info-topic", default="")
    parser.add_argument("--config", default=str(ROOT / "tracks/quality-inspection/configs/g1/qi_topics_readonly.example.yaml"))
    args = parser.parse_args()

    gates: Dict[str, Any] = {}
    want = args.gate.split(",")
    run_all = "all" in want

    if run_all or "0" in want:
        gates["gate0_preflight"] = gate0_preflight()
    if run_all or "1" in want:
        gates["gate1_lidar"] = gate1_lidar(args)
    if run_all or "2" in want:
        gates["gate2_obstacle"] = gate2_obstacle(args)
    if run_all or "3" in want:
        gates["gate3_camera"] = gate3_camera(args)
    if run_all or "4" in want:
        gates["gate4_motion_readonly"] = gate4_motion_readonly(args)
    if run_all or "5" in want:
        gates["gate5_motion_dryrun"] = gate5_motion_dryrun_fixed(args)

    out = {"generated_at": time.time(), "live": args.live, "gates": gates}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print()
    print(_summary(gates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
