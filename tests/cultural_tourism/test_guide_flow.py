"""Unit tests for the cultural-tourism guide workflow (no ROS / no camera)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide import protocol  # noqa: E402
from gdps_tourism.guide.dryrun import DryRunScript, run_dry_tour  # noqa: E402
from gdps_tourism.guide.flow import ActionKind, FlowConfig, GuideState, TourFlow  # noqa: E402
from gdps_tourism.guide.scene import TOOLS, DialogueKnowledge, build_station_scene  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"
KNOWLEDGE = TRACK_ROOT / "configs" / "knowledge_dialogue.example.json"


def _book() -> StationBook:
    return StationBook.load(STATIONS)


class StationBookTest(unittest.TestCase):
    def test_loading_and_target_resolution(self) -> None:
        book = _book()
        self.assertGreaterEqual(len(book.stations), 8)
        self.assertEqual(book.next_after(None).station_id, "S01")
        self.assertEqual(book.next_after("S01").station_id, "S02")
        self.assertIsNone(book.next_after("S08"))

        hit = book.resolve_target("汇丰铜狮")
        self.assertTrue(hit.ok)
        self.assertEqual(hit.station.station_id, "S07")

        sentence = book.resolve_target("带我去看汇丰铜狮")
        self.assertTrue(sentence.ok)
        self.assertEqual(sentence.station.station_id, "S07")

        unknown = book.resolve_target("火星基地")
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.note, "unknown_target")

    def test_landmark_not_in_tour_order(self) -> None:
        book = _book()
        self.assertIn("L01", [station.station_id for station in book.stations])
        self.assertNotIn("L01", book.tour_order)


class ProtocolTest(unittest.TestCase):
    def test_session_create_and_update(self) -> None:
        event = protocol.session_create("场景提示词", tools=TOOLS, hotwords=["汇丰铜狮"])
        self.assertEqual(event["type"], "session.create")
        session = event["session"]
        self.assertEqual(session["model"], protocol.MODEL)
        self.assertEqual(session["instructions"], "场景提示词")
        self.assertEqual(session["tools"], TOOLS)
        self.assertEqual(session["context"]["hotwords"], [{"word": "汇丰铜狮"}])

        update = protocol.session_update(instructions="新场景")
        self.assertEqual(update["type"], "session.update")
        self.assertEqual(update["session"], {"instructions": "新场景"})
        with self.assertRaises(ValueError):
            protocol.session_update()

    def test_cancel_tool_result_and_parse(self) -> None:
        self.assertEqual(protocol.response_cancel()["type"], "response.cancel")
        result = protocol.tool_result("call_1", "正在前往汇丰铜狮")
        item = result["items"][0]
        self.assertEqual(item["call_id"], "call_1")
        self.assertEqual(item["role"], "tool")
        self.assertEqual(item["content"][0]["type"], "input_text")

        fc_raw = json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "items": [
                    {
                        "call_id": "call_9",
                        "name": "request_next_station",
                        "arguments": json.dumps({"target_name": "汇丰铜狮"}),
                    }
                ],
            }
        )
        parsed = protocol.parse_event(fc_raw)
        self.assertEqual(parsed.kind, "fc.done")
        self.assertIsNotNone(parsed.tool)
        self.assertEqual(parsed.tool.name, "request_next_station")
        self.assertEqual(parsed.tool.arguments["target_name"], "汇丰铜狮")

        asr = protocol.parse_event(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "好的，感谢，请前往下一个目标点",
                }
            )
        )
        self.assertEqual(asr.kind, "asr.completed")
        self.assertIn("下一个目标点", asr.text)


class SceneTest(unittest.TestCase):
    def test_station_scene_contains_facts_and_tools(self) -> None:
        book = _book()
        station = book.get("S02")
        knowledge = DialogueKnowledge.load(KNOWLEDGE)
        scene = build_station_scene(
            station,
            exhibit_title="《豫园仰山堂宴会图》",
            narration="这是晚清海派纪实画作。",
            short_summary="晚清涉外外交图像档案。",
            knowledge=knowledge,
        )
        self.assertIn("《豫园仰山堂宴会图》", scene.instructions)
        self.assertIn("这是晚清海派纪实画作。", scene.instructions)
        self.assertIn("开放时间", scene.instructions)
        names = {tool["name"] for tool in scene.tools}
        self.assertIn("request_next_station", names)
        self.assertIn("stop_narration", names)
        self.assertEqual(scene.narration_text, "这是晚清海派纪实画作。")

        tiny = build_station_scene(station, narration="x" * 500, budget=120)
        self.assertLessEqual(len(tiny.instructions), 121)


class FlowTest(unittest.TestCase):
    def _flow(self) -> TourFlow:
        return TourFlow(_book(), FlowConfig(auto_advance=True))

    def test_happy_path(self) -> None:
        flow = self._flow()
        actions = flow.start()
        self.assertEqual(flow.state, GuideState.NAVIGATING)
        self.assertEqual(flow.current_station_id, "S01")
        self.assertEqual(actions[-1].kind, ActionKind.NAVIGATE)
        self.assertEqual(actions[-1].payload["station_id"], "S01")

        flow.on_nav_arrived("S01")
        self.assertEqual(flow.state, GuideState.ARRIVED)
        narrate = flow.on_observation(None)
        self.assertEqual(flow.state, GuideState.NARRATING)
        self.assertEqual(narrate[-1].kind, ActionKind.NARRATE)
        flow.on_speech_finished()
        self.assertEqual(flow.state, GuideState.LISTENING)

        advance = flow.on_tool_call("request_next_station", {})
        kinds = [action.kind for action in advance]
        self.assertIn(ActionKind.END_SIGNAL, kinds)
        self.assertIn(ActionKind.CANCEL_SPEECH, kinds)
        self.assertIn(ActionKind.NAVIGATE, kinds)
        end = [action for action in advance if action.kind is ActionKind.END_SIGNAL][0]
        self.assertEqual(end.payload["type"], "END_NARRATION")
        self.assertEqual(end.payload["station_id"], "S01")
        self.assertEqual(end.payload["next_station_id"], "S02")
        self.assertEqual(flow.state, GuideState.NAVIGATING)
        self.assertEqual(flow.current_station_id, "S02")

    def test_stop_narration_does_not_navigate(self) -> None:
        flow = self._flow()
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        actions = flow.on_tool_call("stop_narration", {"reason": "安静一会"})
        kinds = [action.kind for action in actions]
        self.assertIn(ActionKind.CANCEL_SPEECH, kinds)
        self.assertNotIn(ActionKind.NAVIGATE, kinds)
        end = [action for action in actions if action.kind is ActionKind.END_SIGNAL][0]
        self.assertEqual(end.payload["reason"], "narration_stopped")
        self.assertIsNone(end.payload["next_station_id"])
        self.assertEqual(flow.state, GuideState.LISTENING)

    def test_p2_target_redirect(self) -> None:
        flow = self._flow()
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        actions = flow.on_tool_call(
            "request_next_station", {"target_name": "汇丰铜狮", "reason": "游客点名"}
        )
        navigate = [action for action in actions if action.kind is ActionKind.NAVIGATE][0]
        self.assertEqual(navigate.payload["station_id"], "S07")
        end = [action for action in actions if action.kind is ActionKind.END_SIGNAL][0]
        self.assertEqual(end.payload["next_station_id"], "S07")

    def test_unknown_target_does_not_navigate(self) -> None:
        flow = self._flow()
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        actions = flow.on_tool_call("request_next_station", {"target_name": "火星基地"})
        kinds = [action.kind for action in actions]
        self.assertNotIn(ActionKind.NAVIGATE, kinds)
        self.assertIn(ActionKind.RECOMMEND, kinds)

    def test_landmark_brief_gating(self) -> None:
        flow = self._flow()
        flow.start()
        first = flow.on_landmark("L01", now=100.0)
        self.assertIsNotNone(first)
        self.assertEqual(first.kind, ActionKind.SPEAK_BRIEF)
        self.assertIn("钟楼", first.payload["text"])
        second = flow.on_landmark("L01", now=100.0)
        self.assertIsNone(second)
        flow.on_nav_arrived("S01")
        while_listening = flow.on_landmark("L01", now=200.0)
        self.assertIsNone(while_listening)


class DryRunTest(unittest.TestCase):
    def test_full_tour_with_mocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "timeline.json"
            summary = asyncio.run(
                run_dry_tour(
                    STATIONS,
                    knowledge_path=KNOWLEDGE,
                    narrations={"EXH_001": "豫园宴会图讲解", "EXH_002": "徐光启讲解"},
                    out_json=out,
                )
            )
            self.assertEqual(summary["final_state"], "finished")
            self.assertEqual(
                summary["stations_visited"],
                ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"],
            )
            self.assertEqual(len(summary["end_signals"]), 9)
            self.assertTrue(any("钟楼" in brief for brief in summary["briefs"]))
            self.assertGreaterEqual(summary["cancelled"], 2)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("events", payload)
            self.assertTrue(payload["events"])

    def test_dry_tour_p2_redirect(self) -> None:
        script = DryRunScript(
            per_station={
                "S02": [
                    {
                        "name": "request_next_station",
                        "arguments": {"target_name": "汇丰铜狮", "reason": "游客点名"},
                    }
                ]
            }
        )
        summary = asyncio.run(run_dry_tour(STATIONS, knowledge_path=KNOWLEDGE, script=script))
        self.assertEqual(summary["final_state"], "finished")
        self.assertEqual(
            summary["stations_visited"],
            ["S01", "S02", "S07", "S08"],
        )


if __name__ == "__main__":
    unittest.main()
