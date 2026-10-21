"""Low-texture fast reject: skip the full scan for floor/wall frames."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.matching.feature_matcher import ExhibitMatcher, TemplateLibrary  # noqa: E402


def _pattern(seed: int, width: int = 480, height: int = 360) -> np.ndarray:
    import cv2

    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 128, np.uint8)
    for _ in range(60):
        colour = tuple(int(v) for v in rng.integers(0, 255, size=3))
        cv2.line(
            image,
            (int(rng.integers(0, width)), int(rng.integers(0, height))),
            (int(rng.integers(0, width)), int(rng.integers(0, height))),
            colour,
            int(rng.integers(1, 5)),
        )
    return image


def _library(root: Path) -> TemplateLibrary:
    import cv2

    for index in range(4):
        ok, payload = cv2.imencode(".png", _pattern(index + 1))
        (root / ("t%02d.png" % index)).write_bytes(payload.tobytes())
    return TemplateLibrary.from_directory(root, method="orb", max_side=320, max_features=250)


class FastRejectTest(unittest.TestCase):
    def test_low_feature_uncertain_frame_is_rejected_without_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = _library(Path(tmp))
            matcher = ExhibitMatcher(
                library,
                prefilter="orb",
                prefilter_min_score=1.0,      # force the uncertain path
                fast_reject_features=100000,  # every frame counts as "low feature"
            )
            result = matcher.match(_pattern(9))
            self.assertFalse(result.accepted)
            self.assertEqual(result.unknown_reason, "too_few_features")
            self.assertEqual(result.diagnostics["scanned_templates"], 0)
            self.assertFalse(result.diagnostics["full_scan_used"])

    def test_disabled_fast_reject_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = _library(Path(tmp))
            matcher = ExhibitMatcher(
                library,
                prefilter="orb",
                prefilter_min_score=1.0,
                fast_reject_features=0,
            )
            result = matcher.match(_pattern(9))
            self.assertGreater(result.diagnostics["scanned_templates"], 0)


if __name__ == "__main__":
    unittest.main()
