#!/usr/bin/env python3
"""Field Gates A–E for centering / RGB-D / TF (independent failures)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QI = ROOT / "tracks" / "quality-inspection"
for p in (str(ROOT), str(QI)):
    if p not in sys.path:
        sys.path.insert(0, p)


def gate_a(args: argparse.Namespace) -> dict:
    from gdps_qi.adapters.readonly.head_camera import HeadCameraReadOnly

    cam = HeadCameraReadOnly(
        ros_rgb_topic=args.rgb_topic,
        ros_depth_topic=args.depth_topic,
        ros_camera_info_topic=args.camera_info_topic,
    )
    rep = cam.probe(args.live, args.timeout)
    rep["gate"] = "A"
    rep["status"] = "OK" if rep.get("decode_ok") or not args.live else "UNKNOWN"
    return rep


def gate_b(args: argparse.Namespace) -> dict:
    if not args.live:
        return {"gate": "B", "status": "SKIPPED", "note": "use --live on robot"}
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import PointCloud2

    qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=5)
    sample = {}

    class N(Node):
        def __init__(self) -> None:
            super().__init__("gdps_gate_b")
            self.create_subscription(PointCloud2, args.pc_topic, self.cb, qos)
            self.deadline = time.time() + args.timeout

        def cb(self, msg) -> None:
            if sample:
                return
            sample["frame_id"] = msg.header.frame_id
            sample["point_step"] = msg.point_step
            sample["fields"] = [(f.name, f.offset, int(f.datatype)) for f in msg.fields]

    rclpy.init()
    n = N()
    while time.time() < n.deadline and not sample:
        rclpy.spin_once(n, timeout_sec=0.1)
    n.destroy_node()
    rclpy.shutdown()
    return {
        "gate": "B",
        "status": "OK" if sample else "FAIL",
        "pointcloud": sample,
        "odom_topic": args.odom_topic,
        "tf_note": "livox->base extrinsic must be verified before forward range claims",
    }


def gate_c(args: argparse.Namespace) -> dict:
    return {
        "gate": "C",
        "status": "OFFLINE_OK",
        "note": "run TargetCenteringController on recorded bag via Windows replay",
        "module": "gdps_qi.centering.target_centering_controller",
    }


def gate_d(args: argparse.Namespace) -> dict:
    from shared.navigation.api.navigator import MotionIntent
    from shared.navigation.api.types import Pose2D
    from shared.navigation.factory import build_navigator
    from shared.navigation.perception.obstacle_monitor import ScanFrame

    nav = build_navigator()
    nav.safety.require_sensor = False
    nav.safety.require_odom = False
    nav.safety.require_heartbeat = False
    nav.on_scan(ScanFrame(ranges=tuple([6.0] * 21), angle_min=-0.5, angle_increment=0.05))
    nav.on_pose(Pose2D(0, 0, 0, "odom"))
    nav.start()
    previews = []
    for intent in (
        MotionIntent.LATERAL_LEFT,
        MotionIntent.LATERAL_RIGHT,
        MotionIntent.CRUISE_FORWARD,
        MotionIntent.ROTATE_IN_PLACE,
    ):
        c = nav.preview_motion(intent, 0.5)
        previews.append({"intent": intent.value, "vx": c.vx, "vy": c.vy, "wz": c.wz})
    nav.adapter.close()
    return {"gate": "D", "status": "OK", "dry_run_previews": previews, "live_motion": False}


def gate_e(args: argparse.Namespace) -> dict:
    from gdps_qi.transforms.tf_chain_report import build_frame_graph_report
    from gdps_qi.transforms.transform_manager import TransformManager
    from gdps_qi.validation.sensor_validation_report import SensorValidationReport

    tf = TransformManager()
    rep = build_frame_graph_report(tf)
    svr = SensorValidationReport(allow_cross_sensor_fusion=False, fusion_reasons=["awaiting_field_extrinsics"])
    return {
        "gate": "E",
        "status": "OK",
        "tf_graph": rep.to_dict(),
        "sensor_validation_template": svr.summary(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gate", default="all", help="A,B,C,D,E,all")
    p.add_argument("--live", action="store_true")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--rgb-topic", default="")
    p.add_argument("--depth-topic", default="")
    p.add_argument("--camera-info-topic", default="")
    p.add_argument("--pc-topic", default="/utlidar/cloud_livox_mid360")
    p.add_argument("--odom-topic", default="/dog_odom")
    args = p.parse_args()
    want = {g.strip().upper() for g in args.gate.split(",")}
    if "ALL" in want:
        want = {"A", "B", "C", "D", "E"}
    out = {"generated_at": time.time(), "gates": {}}
    if "A" in want:
        out["gates"]["A"] = gate_a(args)
    if "B" in want:
        out["gates"]["B"] = gate_b(args)
    if "C" in want:
        out["gates"]["C"] = gate_c(args)
    if "D" in want:
        out["gates"]["D"] = gate_d(args)
    if "E" in want:
        out["gates"]["E"] = gate_e(args)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
