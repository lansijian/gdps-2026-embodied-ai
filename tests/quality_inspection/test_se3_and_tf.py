from __future__ import annotations

import math
import time
import unittest

import numpy as np

from gdps_qi.math_se3 import (
    compose_transform,
    identity_error,
    invert_transform,
    make_transform,
    plane_ray_intersection,
    quat_to_rot,
    rot_to_quat,
    transform_from_pose,
)
from gdps_qi.transforms.transform_manager import TransformManager


class Se3Tests(unittest.TestCase):
    def test_inverse_identity(self) -> None:
        t = transform_from_pose((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0))
        err = identity_error(compose_transform(t, invert_transform(t)))
        self.assertLess(err, 1e-9)

    def test_chain_consistency(self) -> None:
        t_ab = transform_from_pose((1.0, 0.0, 0.0), rot_to_quat(quat_to_rot((0, 0, 0, 1))))
        t_bc = transform_from_pose((0.0, 2.0, 0.0), (0, 0, 0, 1))
        t_ac = compose_transform(t_ab, t_bc)
        p = np.array([0.5, 0.5, 0.0, 1.0])
        p_a = t_ac @ p
        p_b = t_bc @ p
        p_a2 = t_ab @ p_b
        self.assertTrue(np.allclose(p_a[:3], p_a2[:3], atol=1e-9))

    def test_plane_ray_hit(self) -> None:
        ok, hit = plane_ray_intersection(
            (0, 0, 1),
            (0, 0, -1),
            (0, 0, 0),
            (0, 0, 1),
        )
        self.assertTrue(ok)
        self.assertAlmostEqual(hit[2], 0.0, places=6)


class TransformManagerTests(unittest.TestCase):
    def test_stale_transform_rejected(self) -> None:
        tf = TransformManager(max_age_s=0.01)
        t = np.eye(4)
        tf.set_transform("a", "b", t, time.time() - 1.0, "c", static=False)
        with self.assertRaises(Exception):
            tf.lookup("a", "b")

    def test_lookup_chain(self) -> None:
        tf = TransformManager(max_age_s=5.0)
        now = time.time()
        tf.set_transform("base", "mid", make_transform(np.eye(3), (1, 0, 0)), now, "x")
        tf.set_transform("mid", "tip", make_transform(np.eye(3), (0, 2, 0)), now, "x")
        t = tf.lookup("base", "tip")
        self.assertAlmostEqual(float(t[0, 3]), 1.0)
        self.assertAlmostEqual(float(t[1, 3]), 2.0)


if __name__ == "__main__":
    unittest.main()
