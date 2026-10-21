"""P1 dialogue knowledge base tests (facts, FAQ, refusal, scene injection)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide.scene import (  # noqa: E402
    DialogueKnowledge,
    build_route_scene,
    build_station_scene,
)
from gdps_tourism.guide.stations import StationBook  # noqa: E402
from scripts.tourism.check_tourism_config import P1_CATEGORIES, check  # noqa: E402

CONFIGS = TRACK_ROOT / "configs"
DIALOGUE = CONFIGS / "knowledge_dialogue.json"
STATIONS = CONFIGS / "stations.example.yaml"


class DialogueKnowledgeStructureTest(unittest.TestCase):
    def test_real_knowledge_is_complete(self) -> None:
        knowledge = DialogueKnowledge.load(DIALOGUE)
        self.assertEqual(knowledge.verified, "partial")
        self.assertEqual(set(knowledge.venue_facts.keys()), set(P1_CATEGORIES))
        self.assertGreaterEqual(len(knowledge.faq), 12)
        self.assertTrue(knowledge.refusal_text)
        self.assertGreaterEqual(len(knowledge.refusal_rules), 3)
        self.assertGreaterEqual(len(knowledge.sources), 4)
        self.assertGreaterEqual(len(knowledge.hotwords), 10)
        self.assertIn("汇丰铜狮", knowledge.hotwords)

    def test_missing_file_returns_empty_knowledge(self) -> None:
        knowledge = DialogueKnowledge.load(CONFIGS / "does_not_exist.json")
        self.assertEqual(knowledge.venue_facts, {})
        self.assertEqual(knowledge.faq, [])


class SceneInjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.knowledge = DialogueKnowledge.load(DIALOGUE)
        self.book = StationBook.load(STATIONS)

    def test_route_scene_contains_p1_faq_and_refusal(self) -> None:
        scene = build_route_scene(next_station=self.book.get("S02"), knowledge=self.knowledge)
        self.assertIn("几点开门", scene.instructions)
        self.assertIn("021-23299999", scene.instructions)
        self.assertIn("拒答", scene.instructions)
        self.assertIn("开放时间", scene.instructions)
        self.assertLessEqual(len(scene.instructions), 4000)

    def test_station_scene_keeps_narration_and_faq(self) -> None:
        scene = build_station_scene(
            self.book.get("S02"),
            exhibit_title="《豫园仰山堂宴会图》",
            narration="这是预置讲解词。",
            knowledge=self.knowledge,
        )
        self.assertIn("这是预置讲解词。", scene.instructions)
        self.assertIn("必看", scene.instructions)
        self.assertIn("拒答", scene.instructions)
        self.assertLessEqual(len(scene.instructions), 6000)
        self.assertGreaterEqual(len(scene.tools), 3)

    def test_greeting_scene_limits_p1_intake(self) -> None:
        from gdps_tourism.guide.scene import build_greeting_scene

        scene = build_greeting_scene(knowledge=self.knowledge)
        self.assertIn("几点开门", scene.instructions)
        self.assertIn("主动打招呼", scene.instructions)


class CheckerIntegrationTest(unittest.TestCase):
    def test_real_dialogue_passes_checker(self) -> None:
        report = check(STATIONS, dialogue_path=DIALOGUE)
        self.assertTrue(report.ok, report.errors)
        dialogue_warnings = [
            item for item in report.warnings if "dialogue" in item or item.startswith("P1 ") or item.startswith("P5 ")
        ]
        self.assertEqual(dialogue_warnings, [])


if __name__ == "__main__":
    unittest.main()
