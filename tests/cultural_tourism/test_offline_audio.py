"""Offline narration fallback tests (no audio device, fake player)."""

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

from gdps_tourism.guide.offline_audio import (  # noqa: E402
    FallbackDialogue,
    OfflineAudioDialogue,
    text_key,
)
from gdps_tourism.guide.scene import SceneText  # noqa: E402


class FakePlayer:
    def __init__(self) -> None:
        self.played = []
        self.stopped = 0

    def play(self, path):
        self.played.append(str(path))
        return object()

    def stop(self) -> None:
        self.stopped += 1


class FakePrimary:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.narrated = []
        self.cancelled = 0

    async def update_scene(self, scene) -> None:
        if self.fail:
            raise RuntimeError("cloud down")

    async def narrate(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("cloud down")
        self.narrated.append(text)

    async def speak_brief(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("cloud down")
        self.narrated.append(text)

    async def cancel_speech(self) -> None:
        self.cancelled += 1

    async def listen(self) -> None:
        if self.fail:
            raise RuntimeError("cloud down")


def _make_offline_dir(tmp: str, text: str, duration: float = 0.01):
    base = Path(tmp)
    key = text_key(text)
    (base / ("%s.wav" % key)).write_bytes(b"RIFF")
    manifest = {
        key: {"file": "%s.wav" % key, "duration_s": duration, "kind": "narration", "id": "EXH_001"}
    }
    (base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return OfflineAudioDialogue.from_dir(base, player=FakePlayer())


class OfflineAudioTest(unittest.TestCase):
    def test_text_key_is_stable(self) -> None:
        self.assertEqual(text_key(" 你好 "), text_key("你好"))
        self.assertNotEqual(text_key("a"), text_key("b"))

    def test_narrate_plays_and_reports_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            offline = _make_offline_dir(tmp, "这是讲解词。")
            finished = []

            async def on_finished():
                finished.append(True)

            offline.on_finished = on_finished
            asyncio.run(offline.narrate("这是讲解词。"))
            self.assertEqual(len(offline.player.played), 1)
            self.assertEqual(len(finished), 1)

    def test_missing_text_is_reported_not_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            offline = _make_offline_dir(tmp, "有音频的句子")
            missing = []
            offline.on_missing = missing.append
            asyncio.run(offline.narrate("没有音频的句子"))
            self.assertEqual(missing, ["没有音频的句子"])

    def test_fallback_switches_to_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            offline = _make_offline_dir(tmp, "备用讲解。")
            primary = FakePrimary(fail=True)
            fallback = FallbackDialogue(primary, offline)
            asyncio.run(fallback.narrate("备用讲解。"))
            self.assertTrue(fallback.degraded)
            self.assertEqual(len(offline.player.played), 1)

    def test_primary_used_while_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            offline = _make_offline_dir(tmp, "在线讲解。")
            primary = FakePrimary()
            fallback = FallbackDialogue(primary, offline)
            asyncio.run(fallback.narrate("在线讲解。"))
            self.assertFalse(fallback.degraded)
            self.assertEqual(primary.narrated, ["在线讲解。"])
            self.assertEqual(offline.player.played, [])


if __name__ == "__main__":
    unittest.main()
