from __future__ import annotations

import time
import unittest

import numpy as np

from gdps_qi.adapters.camera import CameraAdapter
from gdps_qi.math_se3 import deproject_pixel, solve_pnp_planar
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.transforms.transform_manager import TransformManager


class VisionDepthTests(unittest.TestCase):
    def test_deproject_pixel(self) -> None:
        p = deproject_pixel(320, 240, 1.0, 600, 600, 320, 240)
        self.assertAlmostEqual(p[2], 1.0)
        self.assertAlmostEqual(p[0], 0.0, places=4)

    def test_pnp_planar(self) -> None:
        pts = [(0, 0, 0), (0.1, 0, 0), (0.1, 0.1, 0)]
        uv = [(300, 300), (330, 300), (330, 330)]
        t = solve_pnp_planar(pts, uv, 600, 600, 320, 240)
        self.assertEqual(t.shape, (4, 4))

    def test_depth_and_plane_paths(self) -> None:
        tf = TransformManager(max_age_s=5.0)
        now = time.time()
        tf.set_transform("head_camera_optical", "table_frame", np.eye(4), now, "mock")
        tf.set_transform("robot_center", "table_frame", np.eye(4), now, "mock")
        reg = ObjectRegistry.default_six_sample_layout()
        est = PoseEstimator(tf=tf, registry=reg)
        cam = CameraAdapter()
        cam.connect()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        depth = np.ones((480, 640), dtype=np.float32) * 0.6
        cam.set_mock_frame(rgb, depth)
        frame = cam.grab()
        assert frame is not None
        ok, p, mode = est.pixel_to_table_point(320, 240, frame, 0.6)
        self.assertTrue(ok)
        self.assertEqual(mode, "depth")


if __name__ == "__main__":
    unittest.main()
