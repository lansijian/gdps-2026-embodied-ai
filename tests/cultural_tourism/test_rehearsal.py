"""Mission rehearsal estimator tests (synthetic station config)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide.stations import StationBook  # noqa: E402
from scripts.tourism.guide_rehearsal import build_timeline  # noqa: E402

YAML = """
schema_version: 1
frame_id: map
tour_order: [A, B]
stations:
  - id: A
    name: 站点A
    kind: exhibit
    exhibit_ids: [EXH_001]
    eta_s: 10
  - id: B
    name: 站点B
    kind: landmark
    eta_s: 40
    route_brief: "这是B的简讲。"
"""


class RehearsalTest(unittest.TestCase):
    def test_timeline_sums_walk_and_narration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stations.yaml"
            path.write_text(YAML, encoding="utf-8")
            timeline = build_timeline(path, observe_s=3.0, settle_s=2.0, listen_s=5.0)
        rows = timeline["rows"]
        self.assertEqual([row["station_id"] for row in rows], ["A", "B"])
        self.assertEqual(rows[0]["walk_s"], 10)
        self.assertEqual(rows[1]["walk_s"], 30)
        self.assertEqual(rows[0]["narration_s"], 0.0)  # no narration and no brief for A
        self.assertGreater(rows[1]["narration_s"], 0.0)  # B has a route brief
        self.assertGreater(timeline["total_s"], 0)
        self.assertEqual(timeline["stations"], 2)


if __name__ == "__main__":
    unittest.main()
