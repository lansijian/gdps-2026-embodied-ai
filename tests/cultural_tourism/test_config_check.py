"""Config validator tests."""

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

from scripts.tourism.check_tourism_config import P1_CATEGORIES, check  # noqa: E402

STATIONS = """
schema_version: 1
frame_id: map
tour_order: [A]
stations:
  - id: A
    name: 站点A
    kind: exhibit
    exhibit_ids: [EXH_100]
    pose: {x: 1.0, y: 2.0, yaw: 0.5}
    route_brief: "这是A的简讲。"
"""

KNOWLEDGE = {
    "exhibits": [
        {
            "id": "EXH_100",
            "name": "测试展品",
            "narration": "讲解词",
            "primary_image": "a.jpg",
            "associated_images": ["a.jpg"],
        }
    ],
    "composite_boards": [],
}

DIALOGUE = {
    "meta": {
        "verified": "partial",
        "sources": [{"title": "官方", "url": "https://example.org/a"}, {"title": "攻略", "url": "https://example.org/b"}],
        "pending_verification": [],
    },
    "venue_facts": {category: ["事实"] for category in P1_CATEGORIES},
    "faq": [{"q": "问%d" % i, "a": "答%d" % i, "category": "场馆基本信息"} for i in range(10)],
    "refusal_text": "这个我不确定，可以帮您问服务台。",
    "refusal_rules": ["资料没有的不猜", "敏感问题礼貌拒答"],
    "recommendations": ["推荐1", "推荐2", "推荐3"],
}


def _write(tmp: str, stations: str = STATIONS, knowledge=KNOWLEDGE, dialogue=DIALOGUE):
    base = Path(tmp)
    (base / "stations.yaml").write_text(stations, encoding="utf-8")
    (base / "knowledge_base.json").write_text(__import__("json").dumps(knowledge), encoding="utf-8")
    (base / "dialogue.json").write_text(__import__("json").dumps(dialogue), encoding="utf-8")
    templates = base / "templates"
    templates.mkdir()
    (templates / "a.jpg").write_bytes(b"x")
    return base


class ConfigCheckTest(unittest.TestCase):
    def test_good_config_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _write(tmp)
            report = check(
                base / "stations.yaml",
                knowledge_path=base / "knowledge_base.json",
                dialogue_path=base / "dialogue.json",
                templates_dir=base / "templates",
            )
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.warnings, [])

    def test_unknown_exhibit_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = STATIONS.replace("EXH_100", "EXH_MISSING")
            base = _write(tmp, stations=bad)
            report = check(
                base / "stations.yaml",
                knowledge_path=base / "knowledge_base.json",
                dialogue_path=base / "dialogue.json",
                templates_dir=base / "templates",
            )
        self.assertFalse(report.ok)
        self.assertTrue(any("EXH_MISSING" in item for item in report.errors))

    def test_placeholder_pose_and_brief_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stations = STATIONS.replace("{x: 1.0, y: 2.0, yaw: 0.5}", "{x: 0.0, y: 0.0, yaw: 0.0}")
            stations = stations.replace("这是A的简讲。", "这是一段特别特别长的沿途讲解词，应该被配置检查器提醒需要压缩长度。")
            base = _write(tmp, stations=stations)
            report = check(
                base / "stations.yaml",
                knowledge_path=base / "knowledge_base.json",
                dialogue_path=base / "dialogue.json",
                templates_dir=base / "templates",
            )
        self.assertTrue(report.ok)
        self.assertTrue(any("placeholder pose" in item for item in report.warnings))
        self.assertTrue(any("route_brief" in item for item in report.warnings))

    def test_missing_template_image_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = {
                "exhibits": [
                    {
                        "id": "EXH_100",
                        "name": "测试展品",
                        "narration": "讲解词",
                        "primary_image": "missing.jpg",
                        "associated_images": ["missing.jpg"],
                    }
                ],
                "composite_boards": [],
            }
            base = _write(tmp, knowledge=knowledge)
            report = check(
                base / "stations.yaml",
                knowledge_path=base / "knowledge_base.json",
                dialogue_path=base / "dialogue.json",
                templates_dir=base / "templates",
            )
        self.assertFalse(report.ok)
        self.assertTrue(any("missing.jpg" in item for item in report.errors))


if __name__ == "__main__":
    unittest.main()
