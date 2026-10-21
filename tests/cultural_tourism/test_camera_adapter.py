"""Camera adapter mapping tests (fake matcher, no cv2 / no camera)."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide.camera import CameraConfig, ExhibitCamera  # noqa: E402
from gdps_tourism.guide.flow import ActionKind  # noqa: E402
from gdps_tourism.guide.flow import FlowConfig, TourFlow  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"


class _Best:
    template_id = "t01"
    confidence = 0.93


class _Result:
    accepted = True
    best = _Best()
    diagnostics = {"match_ms": 1.5}


class _FakeMatcher:
    def match(self, frame):
        return _Result()


class _FakeSource:
    def __init__(self) -> None:
        self.reads = 0

    def read(self):
        self.reads += 1
        return object()

    def release(self) -> None:
        pass


def _camera() -> ExhibitCamera:
    camera = ExhibitCamera(CameraConfig(templates_dir="."))
    camera._matcher = _FakeMatcher()
    camera._source = _FakeSource()
    camera._template_exhibit = {"t01": "EXH_001"}
    camera._template_station = {"EXH_001": "L01"}
    return camera


class CameraMappingTest(unittest.TestCase):
    def test_observe_filters_station_exhibits(self) -> None:
        book = StationBook.load(STATIONS)
        camera = _camera()
        matched = asyncio.run(camera.observe(book.get("S02")))
        self.assertEqual(matched, ("EXH_001", 0.93))
        other = asyncio.run(camera.observe(book.get("S03")))
        self.assertEqual(other[0], None)
        self.assertAlmostEqual(other[1], 0.93)

    def test_scan_route_maps_exhibit_to_landmark(self) -> None:
        camera = _camera()
        self.assertEqual(asyncio.run(camera.scan_route()), "L01")
        self.assertGreaterEqual(camera._source.reads, 1)


class RouteExhibitFlowTest(unittest.TestCase):
    def test_route_exhibit_triggers_brief_once(self) -> None:
        book = StationBook.load(STATIONS)
        flow = TourFlow(book, FlowConfig())
        flow.start()
        action = flow.on_route_exhibit("EXH_012", now=100.0)
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, ActionKind.SPEAK_BRIEF)
        self.assertEqual(action.payload["station_id"], "L01")
        self.assertIsNone(flow.on_route_exhibit("EXH_012", now=100.0))
        self.assertIsNone(flow.on_route_exhibit("EXH_UNKNOWN", now=100.0))


if __name__ == "__main__":
    unittest.main()