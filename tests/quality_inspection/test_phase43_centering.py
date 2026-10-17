from __future__ import annotations

import unittest

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.centering.lateral_closed_loop import LateralClosedLoopSimulator
from gdps_qi.centering.manipulation_ready import ManipulationReadyGate
from gdps_qi.centering.target_centering_controller import (
    CenteringMode,
    TargetCenteringController,
)
from gdps_qi.perception.detection_types import Detection
from gdps_qi.perception.rgbd_target_geometry import estimate_target_range
from gdps_qi.transforms.tf_chain_report import build_frame_graph_report
from gdps_qi.transforms.transform_manager import TransformManager
from shared.navigation.factory import build_navigator


class Phase43CenteringTests(unittest.TestCase):
    def _tf_with_camera(self) -> TransformManager:
        tf = TransformManager(max_age_s=10.0)
        stamp = 1.0
        tf.set_transform(
            "robot_center",
            "camera_color_optical_frame",
            np.eye(4),
            stamp,
            "test_calib",
            static=True,
        )
        return tf

    def test_centering_uses_cx_cy_not_image_center(self) -> None:
        tf = self._tf_with_camera()
        ctrl = TargetCenteringController(tf=tf)
        info = CameraInfo(640, 480, 500, 500, 400, 300, verified=False)
        frame = CameraFrame(
            rgb=np.zeros((480, 640, 3), dtype=np.uint8),
            depth_m=np.ones((480, 640), dtype=np.float32) * 0.8,
            stamp=1.0,
            info=info,
            intrinsics_trusted=True,
            depth_scale_confirmed=True,
            depth_aligned_to_rgb=True,
            rgb_stamp_sec=1.0, depth_stamp_sec=1.01, camera_info_stamp_sec=1.0,
        )
        det = Detection("t", "01", 0.9, (0, 0, 10, 10), (410.0, 300.0))
        res = ctrl.step(frame, det)
        self.assertAlmostEqual(res.pixel_du, 10.0)
        self.assertNotEqual(res.mode, CenteringMode.SAFE_HOLD)

    def test_tf_report_no_identity_fill(self) -> None:
        tf = TransformManager()
        rep = build_frame_graph_report(tf)
        self.assertIsNone(rep.T_base_camera)
        self.assertTrue(any("missing" in e for e in rep.errors))

    def test_lateral_closed_loop_decreases_pixel_error(self) -> None:
        nav = build_navigator()
        nav.safety.require_heartbeat = False
        info = CameraInfo(640, 480, 500, 500, 320, 240, verified=False)
        from gdps_qi.perception.camera_geometry import make_t_base_camera
        t_cam = make_t_base_camera()
        sim = LateralClosedLoopSimulator(
            nav=nav,
            world_target=(1.0, 0.25, 0.5),
            t_base_camera=t_cam,
            camera_info=info,
        )
        ok, hist = sim.run(initial_pose_y=0.0)
        self.assertGreaterEqual(len(hist), 2)
        self.assertGreater(abs(hist[0].pixel_du), 50)
        self.assertLess(abs(hist[-1].pixel_du_after), abs(hist[0].pixel_du) - 20)
        for item in hist:
            self.assertLess(abs(item.pixel_du_after), abs(item.pixel_du))
        nav.adapter.close()

    def test_manipulation_ready_requires_more_than_centered(self) -> None:
        from gdps_qi.centering.target_centering_controller import CenteringStepResult
        from gdps_qi.perception.rgbd_target_geometry import TargetRangeEstimate

        gate = ManipulationReadyGate()
        c = CenteringStepResult(
            CenteringMode.DOCK_FOR_MANIPULATION,
            True,
            5,
            5,
            0.0,
            (0.5, 0, 0.8),
            (0.5, 0.05, 0.8),
            "none",
            True,
            [],
            3,
        )
        r = TargetRangeEstimate(320, 240, 0.8, 0.8, 0.01, (0.5, 0, 0.8), (0.5, 0.05, 0.8), 0.51, "rgbd", True, [])
        rep = build_frame_graph_report(TransformManager())
        out = gate.evaluate(c, r, rep, body_stable=False, workspace_ok=True, uncertainty_ok=True)
        self.assertEqual(out.status, "CENTERED")
        self.assertFalse(out.manipulation_ready)


if __name__ == "__main__":
    unittest.main()
