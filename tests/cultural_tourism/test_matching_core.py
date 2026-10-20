"""Unit tests for the exhibit matcher coarse prefilter, grouping and dedupe.

Run from the repository root:

    .venv/bin/python -m unittest discover -s tests/cultural_tourism -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.matching.feature_matcher import ExhibitMatcher, TemplateLibrary  # noqa: E402
from gdps_tourism.matching.prefilter import CoarsePrefilter  # noqa: E402
from gdps_tourism.matching.types import MatchCandidate  # noqa: E402

_DIAGNOSTIC_KEYS = {
    "method",
    "query_features",
    "template_count",
    "scanned_templates",
    "prefilter_ms",
    "prefilter_reason",
    "margin",
    "match_ms",
}


def _pattern(seed: int, width: int = 480, height: int = 360) -> np.ndarray:
    """Deterministic high-contrast texture with plenty of stable ORB corners."""

    import cv2

    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 128, np.uint8)
    for _ in range(60):
        colour = tuple(int(v) for v in rng.integers(0, 255, size=3))
        x1, y1 = int(rng.integers(0, width)), int(rng.integers(0, height))
        x2, y2 = int(rng.integers(0, width)), int(rng.integers(0, height))
        cv2.line(image, (x1, y1), (x2, y2), colour, int(rng.integers(1, 5)))
        cv2.circle(
            image,
            (int(rng.integers(0, width)), int(rng.integers(0, height))),
            int(rng.integers(4, 30)),
            colour,
            -1,
        )
    return image


def _write_png(path: Path, image: np.ndarray) -> Path:
    import cv2

    ok, payload = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("cannot encode test image")
    path.write_bytes(payload.tobytes())
    return path


def _random_library(root: Path, seeds, duplicate_pair=None) -> TemplateLibrary:
    for index, seed in enumerate(seeds):
        image = _pattern(seed)
        _write_png(root / ("t%02d.png" % index), image)
    if duplicate_pair is not None:
        first, second = duplicate_pair
        payload = (root / ("t%02d.png" % first)).read_bytes()
        (root / ("t%02d.png" % second)).write_bytes(payload)
    return TemplateLibrary.from_directory(root, method="orb", max_side=320, max_features=250)


class TemplateLibraryExhibitTest(unittest.TestCase):
    def test_knowledge_base_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(3):
                _write_png(root / ("img%d.png" % index), _pattern(index + 1))
            payload = {
                "exhibits": [
                    {
                        "id": "EXH_900",
                        "name": "测试展品",
                        "primary_image": "img0.png",
                        "associated_images": ["img0.png", "img1.png"],
                    }
                ]
            }
            (root / "knowledge_base.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            library = TemplateLibrary.from_directory(
                root, method="orb", max_side=320, max_features=250
            )
            by_stem = {info.source_path.stem: info for info in library.templates}
            self.assertEqual(by_stem["img0"].exhibit_id, "EXH_900")
            self.assertEqual(by_stem["img1"].exhibit_id, "EXH_900")
            self.assertEqual(by_stem["img0"].exhibit_name, "测试展品")
            # 未出现在知识库中的模板回退到 template_id / display_name
            self.assertEqual(by_stem["img2"].exhibit_id, "img2")
            self.assertEqual(by_stem["img2"].exhibit_name, "img2")


class DedupeTest(unittest.TestCase):
    def test_identical_templates_are_scanned_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = _random_library(Path(tmp), range(4), duplicate_pair=(0, 1))
            self.assertEqual(len(library), 4)
            deduped = ExhibitMatcher(library, prefilter="off")
            self.assertEqual(len(deduped._scan_indices), 3)
            self.assertEqual(len(deduped._duplicate_of), 1)
            kept = next(iter(deduped._duplicate_of.values()))
            duplicate = next(iter(deduped._duplicate_of))
            self.assertEqual(deduped._duplicate_of[duplicate], kept)
            self.assertIn(kept, deduped._scan_indices)
            self.assertNotIn(duplicate, deduped._scan_indices)

            raw = ExhibitMatcher(library, prefilter="off", dedupe=False)
            self.assertEqual(len(raw._scan_indices), 4)
            self.assertEqual(raw._duplicate_of, {})


class GroupingTest(unittest.TestCase):
    def test_candidates_are_one_per_exhibit_and_margin_uses_other_group(self) -> None:
        library = TemplateLibrary.from_arrays(
            {
                "a": _pattern(21),
                "b": _pattern(22),
                "c": _pattern(23),
            },
            method="orb",
            max_side=320,
            max_features=250,
        )
        matcher = ExhibitMatcher(library, prefilter="off")
        info_a, info_b, info_c = library.templates
        info_a = replace(info_a, exhibit_id="EXH_A", exhibit_name="A")
        info_b = replace(info_b, exhibit_id="EXH_A", exhibit_name="A")
        info_c = replace(info_c, exhibit_id="EXH_B", exhibit_name="B")
        candidates = [
            MatchCandidate(info_a, 50, 60, 0.8, 0.70, None, True),
            MatchCandidate(info_b, 45, 55, 0.8, 0.65, None, True),
            MatchCandidate(info_c, 30, 40, 0.7, 0.50, None, True),
        ]
        grouped = matcher._group_candidates(candidates)
        self.assertEqual([candidate.info.exhibit_id for candidate in grouped], ["EXH_A", "EXH_B"])
        self.assertEqual(grouped[0].inliers, 50)
        self.assertEqual(matcher._group_key(info_a), "EXH_A")
        self.assertEqual(candidates[0].exhibit_id, "EXH_A")
        self.assertEqual(candidates[2].exhibit_name, "B")

        flat = ExhibitMatcher(library, prefilter="off", group_by_exhibit=False)
        self.assertEqual(flat._group_candidates(candidates), candidates)


class DiagnosticsTest(unittest.TestCase):
    def test_prefilter_off_reports_disabled_and_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = _random_library(Path(tmp), range(2))
            matcher = ExhibitMatcher(library, prefilter="off")
            result = matcher.match(_pattern(99))
            self.assertIsNotNone(result.diagnostics)
            self.assertTrue(_DIAGNOSTIC_KEYS.issubset(result.diagnostics.keys()))
            self.assertEqual(result.diagnostics["prefilter_reason"], "disabled")
            self.assertEqual(
                result.diagnostics["scanned_templates"], len(matcher._scan_indices)
            )
            json.dumps(result.diagnostics)

    def test_prefilter_shortlist_and_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = _random_library(Path(tmp), range(6))
            prefilter = CoarsePrefilter(library, size=320, max_features=200)
            shot = prefilter.shortlist(_pattern(5))
            self.assertFalse(shot.full_scan)
            self.assertIsNone(shot.reason)
            self.assertTrue(shot.indices)
            self.assertIn(5, shot.indices)  # query uses _pattern(5) -> t05
            self.assertEqual(shot.scores, sorted(shot.scores, reverse=True))

            # 纯黑画面没有可用特征 → 必须退回全量扫描
            blank = np.zeros((360, 480, 3), np.uint8)
            fallback = prefilter.shortlist(blank)
            self.assertTrue(fallback.full_scan)
            self.assertIn(fallback.reason, {None, "low_score", "too_few_templates"})
            self.assertNotEqual(fallback.reason, None)

    def test_disabled_result_contract(self) -> None:
        result = CoarsePrefilter.disabled()
        self.assertTrue(result.full_scan)
        self.assertEqual(result.reason, "disabled")
        self.assertEqual(result.indices, [])


class ShortlistSemanticsTest(unittest.TestCase):
    def test_small_library_always_full_scans(self) -> None:
        library = TemplateLibrary.from_arrays(
            {"a": _pattern(31), "b": _pattern(32)},
            method="orb",
            max_side=320,
            max_features=250,
        )
        prefilter = CoarsePrefilter(library, size=320, max_features=200, top_k=3)
        self.assertTrue(prefilter.degraded)
        result = prefilter.shortlist(_pattern(31))
        self.assertTrue(result.full_scan)
        self.assertEqual(result.reason, "too_few_templates")


if __name__ == "__main__":
    unittest.main()
