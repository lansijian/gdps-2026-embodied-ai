"""reflow/asr_qa.py 的离线测试（用 echo 假引擎，不联网、不装 ASR）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[1]
ASR_SCRIPT = REPO_ROOT / "reflow" / "asr_qa.py"


def make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)


def run_asr(args, env=None):
    clean_env = dict(os.environ)
    clean_env.pop("GDPS_ASR_CMD", None)
    if env:
        clean_env.update(env)
    return subprocess.run(
        [sys.executable, str(ASR_SCRIPT)] + args,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=clean_env,
    )


QA_AVAILABLE = (REPO_ROOT / "guide_cli.py").is_file() and (REPO_ROOT / "similarity_matcher.py").is_file()


class AsrQaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.audio = self.dir / "q.wav"
        self.events = self.dir / "qa.events.jsonl"
        make_wav(self.audio)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(QA_AVAILABLE, "guide_cli/similarity_matcher 未移植，跳过问答类断言")
    def test_hit_writes_transcript_and_qa_answered(self):
        proc = run_asr([
            "--audio", str(self.audio),
            "--asr-cmd", "echo 徐光启是谁",
            "--events-jsonl", str(self.events),
            "--quiet",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([r["type"] for r in rows], ["asr_transcript", "qa_answered"])
        self.assertEqual(rows[0]["text"], "徐光启是谁")
        self.assertEqual(rows[0]["backend"], "echo")
        details = rows[1]["details"]
        self.assertEqual(details["question"], "徐光启是谁")
        self.assertEqual(details["exhibit_id"], "EXH_002")
        self.assertEqual(details["question_source"], "asr")
        self.assertEqual(details["asr"]["backend"], "echo")

    @unittest.skipUnless(QA_AVAILABLE, "guide_cli/similarity_matcher 未移植，跳过问答类断言")
    def test_miss_writes_qa_unanswered(self):
        proc = run_asr([
            "--audio", str(self.audio),
            "--asr-cmd", "echo 今天天气怎么样",
            "--events-jsonl", str(self.events),
            "--quiet",
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(rows[-1]["type"], "qa_unanswered")
        self.assertEqual(rows[-1]["details"]["reason"], "below_threshold")

    def test_no_asr_cmd_prints_install_hint(self):
        proc = run_asr(["--audio", str(self.audio), "--events-jsonl", str(self.events)])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("whisper.cpp", proc.stderr)
        self.assertFalse(self.events.exists())

    def test_missing_audio_fails(self):
        proc = run_asr([
            "--audio", str(self.dir / "missing.wav"),
            "--asr-cmd", "echo x",
            "--events-jsonl", str(self.events),
        ])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("音频文件不存在", proc.stderr)


if __name__ == "__main__":
    unittest.main()
