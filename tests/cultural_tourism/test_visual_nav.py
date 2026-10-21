"""Vision-triggered navigation tests (no ROS / no camera / no cloud)."""

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
from gdps_tourism.guide.dryrun import MockCamera, MockDialogue, MockNavigator  # noqa: E402
from gdps_tourism.guide.flow import ActionKind, FlowConfig, GuideState, TourFlow  # noqa: E402
from gdps_tourism.guide.orchestrator import GuideOrchestrator, JsonlEventSink  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"


class _Best:
    template_id = "t02"
    confidence = 0.91


class _Result:
    accepted = True
    best = _Best()
    diagnostics = {"match_ms": 1.2}


class _FakeMatcher:
    def match(self, frame):
        return _Result()


class _FakeSource:
    def start(self) -> None:
        pass

    def read(self):
        return object()

    def release(self):
        pass


class _FakeImageRos:
    def __init__(self) -> None:
        self.topic = ""

    def make_image_source(self, topic):
        self.topic = topic
        return _FakeSource()


def _camera() -> ExhibitCamera:
    camera = ExhibitCamera(CameraConfig(templates_dir="."))
    camera._matcher = _FakeMatcher()
    camera._source = _FakeSource()
    camera._template_exhibit = {"t02": "EXH_002"}
    return camera


class StationLookupTest(unittest.TestCase):
    def test_exhibit_to_station(self) -> None:
        book = StationBook.load(STATIONS)
        self.assertEqual(book.station_for_exhibit("EXH_001").station_id, "S02")
        self.assertEqual(book.station_for_exhibit("EXH_003").station_id, "S04")
        self.assertIsNone(book.station_for_exhibit("EXH_UNKNOWN"))


class VisualTargetFlowTest(unittest.TestCase):
    def _flow(self) -> TourFlow:
        return TourFlow(StationBook.load(STATIONS), FlowConfig())

    def test_listening_at_station_redirects_to_target_station(self) -> None:
        flow = self._flow()
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        flow.on_speech_finished()
        self.assertEqual(flow.state, GuideState.LISTENING)

        actions = flow.on_visual_target("EXH_001", confidence=0.88, source="vision_loop")
        kinds = [action.kind for action in actions]
        self.assertIn(ActionKind.NAVIGATE, kinds)
        self.assertIn(ActionKind.CANCEL_SPEECH, kinds)
        self.assertIn(ActionKind.END_SIGNAL, kinds)
        end = [action for action in actions if action.kind is ActionKind.END_SIGNAL][0]
        self.assertEqual(end.payload["reason"], "visual_target")
        self.assertEqual(end.payload["next_station_id"], "S02")
        navigate = [action for action in actions if action.kind is ActionKind.NAVIGATE][0]
        self.assertEqual(navigate.payload["station_id"], "S02")
        self.assertEqual(flow.pending_exhibit_id, "EXH_001")

        flow.on_nav_arrived("S02")
        narrate = flow.on_observation(None, confidence=0.0)
        payload = [action for action in narrate if action.kind is ActionKind.NARRATE][0].payload
        self.assertEqual(payload["exhibit_id"], "EXH_001")
        self.assertEqual(flow.state, GuideState.NARRATING)

    def test_already_at_station_listening_narrates_immediately(self) -> None:
        flow = self._flow()
        flow.start()
        flow.on_nav_arrived("S02")
        flow.on_observation(None)
        flow.on_speech_finished()
        actions = flow.on_visual_target("EXH_001", 0.9, "external")
        kinds = [action.kind for action in actions]
        self.assertIn(ActionKind.NARRATE, kinds)
        self.assertNotIn(ActionKind.NAVIGATE, kinds)
        self.assertEqual(flow.state, GuideState.NARRATING)

    def test_unmapped_exhibit_only_logs(self) -> None:
        flow = self._flow()
        flow.start()
        actions = flow.on_visual_target("EXH_UNKNOWN", 0.99, "external")
        kinds = [action.kind for action in actions]
        self.assertEqual(kinds, [ActionKind.LOG])

    def test_redirect_while_navigating(self) -> None:
        flow = self._flow()
        flow.start()
        self.assertEqual(flow.state, GuideState.NAVIGATING)
        actions = flow.on_visual_target("EXH_003", 0.95)
        navigate = [action for action in actions if action.kind is ActionKind.NAVIGATE][0]
        self.assertEqual(navigate.payload["station_id"], "S04")
        self.assertEqual(flow.current_station_id, "S04")


class CameraScanExhibitTest(unittest.TestCase):
    def test_scan_exhibit_is_unfiltered(self) -> None:
        camera = _camera()
        exhibit_id, confidence = asyncio.run(camera.scan_exhibit())
        self.assertEqual(exhibit_id, "EXH_002")
        self.assertAlmostEqual(confidence, 0.91)

    def test_image_topic_is_used_when_configured(self) -> None:
        camera = ExhibitCamera(CameraConfig(templates_dir=".", image_topic="/camera/color/image_raw"))
        ros = _FakeImageRos()
        camera._open_source(ros)
        self.assertEqual(ros.topic, "/camera/color/image_raw")
        self.assertIsNotNone(camera._source)


class VisualTargetOrchestratorTest(unittest.TestCase):
    def test_visual_target_sends_navigation_goal(self) -> None:
        book = StationBook.load(STATIONS)
        flow = TourFlow(book)
        dialogue = MockDialogue()
        navigator = MockNavigator()
        orchestrator = GuideOrchestrator(
            flow=flow,
            dialogue=dialogue,
            navigator=navigator,
            camera=MockCamera(),
            sink=JsonlEventSink(),
        )

        async def run():
            await orchestrator.execute(flow.start())
            await orchestrator.on_navigation_arrived("S01")
            await orchestrator.on_speech_finished()
            await orchestrator.on_visual_target("EXH_001", 0.9, "external")

        asyncio.run(run())
        self.assertIn("S02", [goal.get("station_id") for goal in navigator.goals])
        self.assertEqual(flow.current_station_id, "S02")


if __name__ == "__main__":
    unittest.main()
