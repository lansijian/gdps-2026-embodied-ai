from __future__ import annotations

import time
import unittest

import numpy as np

from gdps_qi.math_se3 import identity_error, invert_transform
from gdps_qi.transforms.transform_manager import TransformManager


class TfBidirectionalTests(unittest.TestCase):
    def test_lookup_inverse_roundtrip(self) -> None:
        tf = TransformManager(max_age_s=5.0)
        now = time.time()
        t = np.eye(4)
        t[0, 3] = 0.5
        t[1, 3] = -0.2
        tf.set_transform("base", "cam", t, now, "cal")
        t_fwd = tf.lookup("base", "cam", now)
        t_inv = tf.lookup_inverse("cam", "base", now)
        err = identity_error(t_fwd @ t_inv)
        self.assertLess(err, 1e-8)

    def test_dynamic_stamp_interpolation(self) -> None:
        tf = TransformManager(max_age_s=10.0)
        t0 = time.time()
        a = np.eye(4)
        b = np.eye(4)
        b[0, 3] = 1.0
        tf.set_transform("base", "obj", a, t0, "c", static=False)
        tf.set_transform("base", "obj", b, t0 + 1.0, "c", static=False, allow_conflict=True)
        mid = tf.lookup("base", "obj", t0 + 0.5)
        self.assertGreater(float(mid[0, 3]), 0.0)


if __name__ == "__main__":
    unittest.main()
