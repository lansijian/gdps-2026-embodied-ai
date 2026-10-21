"""reflow/agent.py 的离线测试（不联网）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[1]
AGENT_PATH = REPO_ROOT / "reflow" / "agent.py"
BOOTSTRAP_PATH = REPO_ROOT / "tools" / "reflow_bootstrap.py"
SPEC_PATH = REPO_ROOT / "reflow" / "s22_spec.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


agent = _load("reflow_agent", AGENT_PATH)
bootstrap = _load("reflow_bootstrap_test", BOOTSTRAP_PATH)
SPEC = bootstrap.load_spec(SPEC_PATH)


def ev(seq, ts, etype, **fields):
    record = {"schema_version": "1.0", "seq": seq, "ts": ts, "type": etype}
    record.update(fields)
    return record


def full_events():
    return [
        ev(1, "2026-10-23T10:00:00.000+08:00", "run_start", source="camera"),
        ev(2, "2026-10-23T10:00:00.000+08:00", "control_mode_changed", mode="autonomous"),
        ev(3, "2026-10-23T10:00:05.000+08:00", "exhibit_stable", template_id="001", exhibit_id="EXH_001", exhibit_name="A"),
        ev(4, "2026-10-23T10:00:05.100+08:00", "narration_start", template_id="001", exhibit_id="EXH_001", exhibit_name="A"),
        ev(5, "2026-10-23T10:00:40.000+08:00", "narration_end", template_id="001", exhibit_id="EXH_001", exhibit_name="A", duration_s=34.9),
        ev(6, "2026-10-23T10:01:00.000+08:00", "qa_answered", details={"question": "这是什么"}),
        ev(7, "2026-10-23T10:02:00.000+08:00", "language_switch_attempt", details={"language": "en"}),
        ev(8, "2026-10-23T10:03:00.000+08:00", "tracking_started"),
        ev(9, "2026-10-23T10:04:00.000+08:00", "tracking_finished"),
        ev(10, "2026-10-23T10:05:00.000+08:00", "interaction_finished"),
        ev(11, "2026-10-23T10:06:00.000+08:00", "recommendation_provided", details={"items": ["外滩"]}),
        ev(12, "2026-10-23T10:07:00.000+08:00", "run_end", interrupted=False, frames=120, matches=60),
    ]


def make_args(**overrides):
    args = agent.parse_args([
        "--events", "unused.jsonl",
        "--evaluation-id", "00000000-0000-4000-8000-000000000000",
        "--session-id", "session-test-001",
        "--out-dir", str(TEST_DIR / "_tmp_agent"),
    ])
    # 模拟 main() 的预设解析：默认按 S22 补齐 profile/spec
    if not getattr(args, "profile", ""):
        args.profile = "S22-v1"
    if not getattr(args, "spec", ""):
        args.spec = str(SPEC_PATH)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class AgentBuilderTest(unittest.TestCase):
    def build(self, events, **overrides):
        args = make_args(**overrides)
        builder = agent.Builder(events, args, spec=SPEC)
        payload = builder.build()
        problems = []
        for name in ("start", "final"):
            problems += bootstrap.validate_payload("report", payload[name], spec=SPEC)
        for kind, batch in payload["batches"]:
            problems += bootstrap.validate_payload(kind, batch, spec=SPEC)
        self.assertEqual(problems, [], "payload 校验失败：%s" % problems)
        return payload

    def test_full_run_all_checkpoints_completed(self):
        payload = self.build(full_events())
        final = payload["final"]
        self.assertEqual(final["task_status"], "completed")
        results = [r for r in final["checkpoints"] if r["record_kind"] == "checkpoint_result"]
        self.assertEqual([r["checkpoint_id"] for r in results], agent.CHECKPOINT_ORDER)
        self.assertTrue(all(r["status"] == "completed" for r in results), results)
        self.assertEqual(final["control_records"][0]["mode"], "autonomous")
        process_records = [r for r in final["checkpoints"] if r["record_kind"] in ("attempt", "observation")]
        self.assertEqual(len(results), 6)
        self.assertGreaterEqual(len(process_records), 6)  # P1 attempt + P2/P3 过程记录

    def test_p1_only_is_partial_and_others_skipped(self):
        events = [
            ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"),
            ev(2, "2026-10-23T10:00:05.000+08:00", "exhibit_stable", template_id="001", exhibit_id="EXH_001"),
            ev(3, "2026-10-23T10:00:05.000+08:00", "narration_start", template_id="001", exhibit_id="EXH_001"),
            ev(4, "2026-10-23T10:00:20.000+08:00", "narration_end", template_id="001", exhibit_id="EXH_001", duration_s=15.0),
            ev(5, "2026-10-23T10:00:30.000+08:00", "run_end", interrupted=False),
        ]
        payload = self.build(events)
        final = payload["final"]
        self.assertEqual(final["task_status"], "partial")
        results = {r["checkpoint_id"]: r["status"] for r in final["checkpoints"] if r["record_kind"] == "checkpoint_result"}
        self.assertEqual(results["S22-P1"], "completed")
        for cp in ["S22-P2", "S22-P3", "S22-P4", "S22-P5", "S22-P6"]:
            self.assertEqual(results[cp], "skipped")

    def test_interrupted_run_is_aborted_and_p1_partial(self):
        events = [
            ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"),
            ev(2, "2026-10-23T10:00:05.000+08:00", "exhibit_stable", template_id="001", exhibit_id="EXH_001"),
            ev(3, "2026-10-23T10:00:05.000+08:00", "narration_start", template_id="001", exhibit_id="EXH_001"),
            ev(4, "2026-10-23T10:00:10.000+08:00", "run_end", interrupted=True),
        ]
        payload = self.build(events)
        final = payload["final"]
        self.assertEqual(final["task_status"], "aborted")
        p1 = [r for r in final["checkpoints"] if r["checkpoint_id"] == "S22-P1" and r["record_kind"] == "checkpoint_result"][0]
        self.assertEqual(p1["status"], "partial")

    def test_no_events_produces_failed_run_with_skips(self):
        events = [ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"), ev(2, "2026-10-23T10:00:01.000+08:00", "run_end")]
        payload = self.build(events)
        self.assertEqual(payload["final"]["task_status"], "failed")
        self.assertEqual(payload["final"]["control_records"], [])

    def test_embodied_and_trajectory_batches(self):
        events = full_events() + [
            ev(13, "2026-10-23T10:00:06.000+08:00", "embodied_sample", sample_seq=0, timestamp="2026-10-23T10:00:06.000+08:00",
               mode="autonomous", joint_names=["j1", "j2"], joint_positions=[0.1, 0.2], battery_pct=88.0),
            ev(14, "2026-10-23T10:00:06.500+08:00", "trajectory_point", point_seq=0, timestamp="2026-10-23T10:00:06.500+08:00",
               x_m=0.0, y_m=0.0, z_m=0.0),
        ]
        payload = self.build(events)
        kinds = [kind for kind, _ in payload["batches"]]
        self.assertEqual(kinds, ["embodied", "trajectory"])
        embodied = payload["batches"][0][1]
        self.assertEqual(embodied["samples"][0]["sample_seq"], 0)
        self.assertNotIn("type", embodied["samples"][0])
        # joint_names 必须在批次级，样本内不能出现（否则平台 422 未定义字段）
        self.assertEqual(embodied["joint_names"], ["j1", "j2"])
        self.assertNotIn("joint_names", embodied["samples"][0])


class GenericModeTest(unittest.TestCase):
    """通用模式：事件显式携带 checkpoint_record，适配 S05 质检检测等非导览赛道。"""

    def build(self, events):
        spec = bootstrap.load_spec(REPO_ROOT / "reflow" / "s05_spec.json")
        self.assertIsNotNone(spec)
        args = make_args()
        args.mode = "generic"
        args.track = "s05"
        args.profile = "S05-v1"
        payload = agent.Builder(events, args, spec=spec).build()
        problems = bootstrap.validate_payload("report", payload["final"], spec=spec)
        self.assertEqual(problems, [], problems)
        return payload

    def test_s05_records_and_fill_missing(self):
        events = [
            ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"),
            ev(2, "2026-10-23T10:00:01.000+08:00", "control_mode_changed", mode="autonomous"),
            ev(3, "2026-10-23T10:00:20.000+08:00", "checkpoint_record",
               checkpoint_id="S05-P1", record_kind="checkpoint_result", status="completed",
               details={"quality_passed": True}),
            ev(4, "2026-10-23T10:01:00.000+08:00", "checkpoint_record",
               checkpoint_id="S05-P2", record_kind="observation", status="step_completed"),
            ev(5, "2026-10-23T10:05:00.000+08:00", "run_end", interrupted=False),
        ]
        payload = self.build(events)
        final = payload["final"]
        self.assertEqual(final["reporting_profile_version"], "S05-v1")
        self.assertEqual(final["control_records"][0]["mode"], "autonomous")
        results = {r["checkpoint_id"]: r["status"] for r in final["checkpoints"] if r["record_kind"] == "checkpoint_result"}
        self.assertEqual(results["S05-P1"], "completed")
        for cp in ["S05-P2", "S05-P3", "S05-P4", "S05-P5", "S05-P6"]:
            self.assertEqual(results[cp], "skipped")
        obs = [r for r in final["checkpoints"] if r["record_kind"] == "observation"]
        self.assertEqual(obs[0]["checkpoint_id"], "S05-P2")
        self.assertEqual(obs[0]["status"], "step_completed")
        self.assertEqual(final["task_status"], "partial")

    def test_generic_invalid_checkpoint_rejected_by_validator(self):
        events = [
            ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"),
            ev(2, "2026-10-23T10:00:10.000+08:00", "checkpoint_record",
               checkpoint_id="S05-P9", record_kind="checkpoint_result", status="completed"),
            ev(3, "2026-10-23T10:00:20.000+08:00", "run_end"),
        ]
        spec = bootstrap.load_spec(REPO_ROOT / "reflow" / "s05_spec.json")
        args = make_args()
        args.mode = "generic"
        args.profile = "S05-v1"
        payload = agent.Builder(events, args, spec=spec).build()
        problems = bootstrap.validate_payload("report", payload["final"], spec=spec)
        self.assertTrue(any("S05-P9" in p for p in problems), problems)


class MergeSourcesTest(unittest.TestCase):
    def test_camera_and_qa_events_merge_by_ts(self):
        camera = [
            ev(1, "2026-10-23T10:00:00.000+08:00", "run_start"),
            ev(2, "2026-10-23T10:00:05.000+08:00", "exhibit_stable", template_id="001", exhibit_id="EXH_001"),
            ev(3, "2026-10-23T10:00:05.100+08:00", "narration_start", template_id="001", exhibit_id="EXH_001"),
            ev(4, "2026-10-23T10:00:20.000+08:00", "narration_end", template_id="001", exhibit_id="EXH_001", duration_s=14.9),
            ev(5, "2026-10-23T10:01:00.000+08:00", "run_end", interrupted=False),
        ]
        qa = [
            ev(1, "2026-10-23T10:00:30.000+08:00", "qa_answered", details={"question": "徐光启是谁"}),
            ev(2, "2026-10-23T10:00:40.000+08:00", "qa_unanswered", details={"question": "天气"}),
        ]
        merged = agent.merge_events([camera, qa])
        self.assertEqual(len(merged), 7)
        self.assertEqual([e["type"] for e in merged][:3], ["run_start", "exhibit_stable", "narration_start"])
        self.assertTrue(merged[-1]["type"] == "run_end")

        args = make_args()
        payload = agent.Builder(merged, args).build()
        results = {r["checkpoint_id"]: r["status"] for r in payload["final"]["checkpoints"] if r["record_kind"] == "checkpoint_result"}
        self.assertEqual(results["S22-P1"], "completed")
        self.assertEqual(results["S22-P2"], "completed")
        self.assertEqual(payload["final"]["task_status"], "partial")


@unittest.skipUnless((REPO_ROOT / "guide_cli.py").is_file(), "guide_cli.py 未移植到当前仓库")
class GuideCliEventsTest(unittest.TestCase):
    def test_guide_cli_writes_qa_events(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "qa.events.jsonl"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "guide_cli.py"),
                    "--ask", "徐光启是谁",
                    "--ask", "今天天气怎么样",
                    "--events-jsonl", str(events_path),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["type"], "qa_answered")
            self.assertEqual(rows[1]["type"], "qa_unanswered")
            self.assertEqual(rows[0]["details"]["exhibit_id"], "EXH_002")
            self.assertEqual(rows[1]["details"]["reason"], "below_threshold")
            self.assertRegex(rows[0]["ts"], r"\+08:00$")


if __name__ == "__main__":
    unittest.main()
