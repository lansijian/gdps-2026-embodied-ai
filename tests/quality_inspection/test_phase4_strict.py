from __future__ import annotations

import json
import unittest

from gdps_qi.adapters.readonly.joint_snapshot import JointSnapshot, JointValidity
from gdps_qi.adapters.readonly.robot_state import RobotStateReadOnly
from gdps_qi.adapters.readonly.ros2_probe import joint_state_from_summary, summarize_ros_message
from gdps_qi.hardware.g1_joint_map import DEFAULT_LEFT_PINCH_TCP
from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel
from gdps_qi.perception.p1_tablet_localize import PositionTier, localize_tablet_01
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.transforms.calibration_trust import CalibrationTrust
from gdps_qi.transforms.g1_tf_chain import G1TfChain
from gdps_qi.transforms.transform_manager import TransformManager
from gdps_qi.kinematics.kinematics_backend import SimplifiedTestKinematics
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.adapters.camera import CameraFrame, CameraInfo
import numpy as np
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Phase4StrictTests(unittest.TestCase):
    def test_joint_summary_keeps_real_positions(self) -> None:
        summary = {
            "joint_names": ["j1", "j2"],
            "joint_positions": [0.12, -0.34],
            "stamp_sec": 1.0,
        }
        snap = joint_state_from_summary(summary, "test")
        self.assertEqual(snap.validity, JointValidity.VALID)
        self.assertAlmostEqual(snap.positions["j1"], 0.12)
        self.assertNotIn("j3", snap.positions)

    def test_robot_state_dry_run_no_fake_positions(self) -> None:
        rs = RobotStateReadOnly()
        rep = rs.probe(False)
        self.assertIsNone(rs.get_joint_snapshot())

    def test_camera_info_k_full(self) -> None:
        class H:
            frame_id = "cam"
            stamp = type("S", (), {"sec": 1, "nanosec": 0})()

        class M:
            header = H()
            height = 480
            width = 640
            distortion_model = "plumb_bob"
            k = [1, 0, 2, 0, 3, 0, 4, 0, 5]
            d = [0.1, 0.2]
            r = [1, 0, 0, 0, 1, 0, 0, 0, 1]
            p = [1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0]

        s = summarize_ros_message(M())
        self.assertEqual(len(s["k"]), 9)
        self.assertEqual(len(s["d"]), 2)

    def test_g1_tf_rejects_without_base_pelvis(self) -> None:
        try:
            import pinocchio  # noqa: F401
        except ImportError:
            self.skipTest("pinocchio not installed")
        tf = TransformManager()
        urdf_path = ROOT / "tests/fixtures/minimal_2link.urdf"
        urdf = G1UrdfModel(str(urdf_path), base_frame="pelvis")
        self.assertTrue(urdf.load())
        chain = G1TfChain(tf=tf, urdf=urdf)
        ok, msg = chain.update_robot_chain_from_joints({"waist_yaw_joint": 0.0}, 0.0, "x")
        self.assertFalse(ok)
        self.assertIn("base_pelvis", msg)

    def test_tcp_unverified_not_executable(self) -> None:
        self.assertFalse(DEFAULT_LEFT_PINCH_TCP.verified)
        planner = GraspPlanner(registry=ObjectRegistry.default_six_sample_layout(), kinematics=SimplifiedTestKinematics())
        from gdps_qi.types import PoseRecord, Uncertainty

        pose = PoseRecord(
            frame_id="robot_center",
            stamp=0.0,
            position=(0.3, 0.0, 0.4),
            orientation_xyzw=(0, 0, 0, 1),
            uncertainty=Uncertainty(0.001, 0.01),
            confidence=0.9,
        )
        plan = planner.plan_tablet_grasp(pose, allow_executable=False)
        self.assertFalse(plan.executable_plan)

    def test_calibrated_world_not_elevated_without_trust(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        reg = ObjectRegistry.default_six_sample_layout()
        tf = TransformManager(max_age_s=5.0)
        est = PoseEstimator(tf=tf, registry=reg)
        planner = GraspPlanner(registry=reg, kinematics=SimplifiedTestKinematics())
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[100:380, 120:520] = 200
        frame = CameraFrame(
            rgb=rgb,
            depth_m=None,
            stamp=1.0,
            info=CameraInfo(640, 480, 600, 600, 320, 240),
            intrinsics_trusted=False,
        )
        tf.set_transform("head_camera_optical", "table_frame", np.eye(4), 1.0, "sim", static=False)
        tf.set_transform("robot_center", "table_frame", np.eye(4), 1.0, "sim", static=False)
        res = localize_tablet_01(
            "01",
            frame,
            est,
            planner,
            g1_tf=None,
            trust=None,
            require_calibrated_table=True,
        )
        self.assertNotEqual(res.tier, PositionTier.CALIBRATED_WORLD)

    def test_urdf_missing_joints_rejected(self) -> None:
        try:
            import pinocchio  # noqa: F401
        except ImportError:
            self.skipTest("pinocchio not installed - not counted as G1 IK verified")
        urdf = ROOT / "tests/fixtures/minimal_2link.urdf"
        m = G1UrdfModel(str(urdf))
        self.assertTrue(m.load())
        cfg = m.configure_required_joints({}, ("waist_yaw_joint",))
        self.assertFalse(cfg.ok)

    def test_dds_timeout_schema(self) -> None:
        from gdps_qi.adapters.readonly.dds_readonly import subscribe_dds_once

        out = subscribe_dds_once("", object, 0.1, lambda m: {})
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
