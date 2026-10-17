from __future__ import annotations

import ast
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.adapters.readonly.dds_readonly import (
    DEX3_EXPECTED_JOINTS,
    parse_hand_state,
    parse_lowstate_motors,
    subscribe_dds_once,
)
from gdps_qi.adapters.readonly.image_decode import decode_sensor_image
from gdps_qi.perception.p1_tablet_localize import PositionTier, localize_tablet_01
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.transforms.calibration_trust import CalibrationTrust
from gdps_qi.transforms.transform_manager import TransformManager
from gdps_qi.kinematics.kinematics_backend import SimplifiedTestKinematics

ROOT = Path(__file__).resolve().parents[2]


def _motor(q=0.1, dq=0.0, tau=0.0):
    return SimpleNamespace(q=q, dq=dq, tau_est=tau)


class Phase41FieldReadinessTests(unittest.TestCase):
    def test_hand_state_missing_q_not_zero_filled(self) -> None:
        motors = [_motor(0.1), SimpleNamespace(q=None, dq=0.0, tau_est=0.0)] + [_motor() for _ in range(5)]
        msg = SimpleNamespace(motor_state=motors)
        out = parse_hand_state(msg, "left")
        self.assertTrue(out.get("reject"))
        self.assertIsNone(out.get("joint_positions"))

    def test_hand_state_dq_not_reported_as_current(self) -> None:
        msg = SimpleNamespace(motor_state=[_motor(0.2, 1.5, 0.3) for _ in range(DEX3_EXPECTED_JOINTS)])
        out = parse_hand_state(msg, "left")
        self.assertNotIn("current", out)
        self.assertEqual(out["joint_velocities"][0], 1.5)
        self.assertEqual(out["estimated_torque_nm"][0], 0.3)

    def test_hand_state_wrong_count_rejected(self) -> None:
        msg = SimpleNamespace(motor_state=[_motor() for _ in range(3)])
        out = parse_hand_state(msg, "left")
        self.assertTrue(out.get("reject"))

    def test_lowstate_short_array_rejected(self) -> None:
        motors = [_motor(float(i)) for i in range(5)]
        msg = SimpleNamespace(motor_state=motors)
        out = parse_lowstate_motors(msg, {0: "j0", 28: "j28"}, expected_dof=29)
        self.assertTrue(out.get("reject"))

    def test_image_row_padding_decode(self) -> None:
        w, h, pad = 4, 2, 2
        row = bytes(range(12)) + (b"\xff" * pad)
        data = row * h
        msg = SimpleNamespace(
            height=h,
            width=w,
            step=12 + pad,
            encoding="rgb8",
            is_bigendian=False,
            data=data,
            header=SimpleNamespace(frame_id="cam", stamp=SimpleNamespace(sec=1, nanosec=0)),
        )
        res = decode_sensor_image(msg)
        self.assertTrue(res.ok)
        self.assertEqual(res.rgb.shape, (h, w, 3))
        self.assertEqual(int(res.rgb[0, 0, 0]), 0)

    def test_16uc1_requires_depth_scale(self) -> None:
        raw = np.zeros((2, 2), dtype=np.uint16).tobytes()
        msg = SimpleNamespace(
            height=2,
            width=2,
            step=4,
            encoding="16UC1",
            is_bigendian=False,
            data=raw,
            header=SimpleNamespace(frame_id="d", stamp=SimpleNamespace(sec=1, nanosec=0)),
        )
        res = decode_sensor_image(msg, allow_16uc1_depth=True, depth_scale_m=None)
        self.assertFalse(res.ok)
        self.assertEqual(res.message, "depth_scale_unknown")

    def test_mono16_not_depth_by_default(self) -> None:
        raw = np.zeros((2, 2), dtype=np.uint16).tobytes()
        msg = SimpleNamespace(
            height=2,
            width=2,
            step=4,
            encoding="mono16",
            is_bigendian=False,
            data=raw,
            header=SimpleNamespace(frame_id="d", stamp=SimpleNamespace(sec=1, nanosec=0)),
        )
        res = decode_sensor_image(msg)
        self.assertEqual(res.message, "mono16_not_depth_without_config")

    def test_depth_deprojection_rejects_unaligned(self) -> None:
        reg = ObjectRegistry.default_six_sample_layout()
        tf = TransformManager()
        est = PoseEstimator(tf=tf, registry=reg)
        frame = CameraFrame(
            rgb=np.zeros((10, 10, 3), dtype=np.uint8),
            depth_m=np.ones((10, 10), dtype=np.float32),
            stamp=1.0,
            info=CameraInfo(10, 10, 500, 500, 5, 5, verified=False),
            intrinsics_trusted=True,
            depth_scale_confirmed=False,
            depth_aligned_to_rgb=False,
        )
        ok, _, msg = est.pixel_to_table_point(5.0, 5.0, frame, 0.5)
        self.assertFalse(ok)
        self.assertIn("depth", msg)

    def test_calibrated_world_blocked_without_trusted_camera(self) -> None:
        reg = ObjectRegistry.default_six_sample_layout()
        tf = TransformManager(max_age_s=5.0)
        est = PoseEstimator(tf=tf, registry=reg)
        planner = GraspPlanner(registry=reg, kinematics=SimplifiedTestKinematics())
        frame = CameraFrame(
            rgb=np.zeros((480, 640, 3), dtype=np.uint8),
            depth_m=None,
            stamp=1.0,
            info=None,
            intrinsics_trusted=False,
        )
        trust = CalibrationTrust(table_calibrated=True, camera_info_fresh=True, robot_joints_valid=True)
        res = localize_tablet_01(
            "01",
            frame,
            est,
            planner,
            g1_tf=None,
            trust=trust,
            require_calibrated_table=True,
            detections_override=[],
        )
        self.assertNotEqual(res.tier, PositionTier.CALIBRATED_WORLD)

    def test_diagnostics_script_no_publisher_imports(self) -> None:
        script = ROOT / "scripts/g1/qi_hardware_diagnostics.py"
        tree = ast.parse(script.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for n in n.names}
        self.assertNotIn("ChannelPublisher", names)

    def test_subscribe_dds_empty_topic(self) -> None:
        out = subscribe_dds_once("", object, 0.01, lambda m: {})
        self.assertFalse(out["ok"])

    def test_big_endian_16uc1_depth(self) -> None:
        arr = np.array([[1000]], dtype=np.uint16)
        arr_be = arr.astype(">u2")
        msg = SimpleNamespace(
            height=1,
            width=1,
            step=2,
            encoding="16UC1",
            is_bigendian=True,
            data=arr_be.tobytes(),
            header=SimpleNamespace(frame_id="d", stamp=SimpleNamespace(sec=1, nanosec=0)),
        )
        res = decode_sensor_image(msg, depth_scale_m=0.001, allow_16uc1_depth=True)
        self.assertTrue(res.ok)
        self.assertAlmostEqual(float(res.depth_m[0, 0]), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
