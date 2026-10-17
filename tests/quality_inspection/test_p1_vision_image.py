from __future__ import annotations

import unittest

import numpy as np

from gdps_qi.perception.tablet_vision import detect_tablets_in_rgb


class P1VisionImageTests(unittest.TestCase):
    def test_blank_image_rejected(self) -> None:
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        dets, msg = detect_tablets_in_rgb(rgb)
        self.assertEqual(msg, "low_variance_reject_blank_frame")
        self.assertEqual(len(dets), 0)

    def test_bright_blob_produces_candidate(self) -> None:
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[100:380, 120:520] = 220
        dets, msg = detect_tablets_in_rgb(rgb)
        self.assertNotEqual(msg, "low_variance_reject_blank_frame")
        self.assertGreaterEqual(len(dets), 1)


if __name__ == "__main__":
    unittest.main()
