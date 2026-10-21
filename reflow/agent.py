#!/usr/bin/env python3
"""导览事件 → 平台回流上报（S22 文旅导览）。

读取 match_live.py 产出的 guide events（JSONL），按 reflow/checkpoint_map.yaml 的语义
组装成平台要求的三类上报：
  * report（running / 终态 + checkpoint_result）
  * embodied 批次（关节/电量/模式）
  * trajectory 批次（位姿点）

默认 dry-run：只生成 payload 并做 spec 感知校验，不联网。
加 --send 才会真正 POST；由于 report_id / record_id 是确定性的，重跑安全（服务端幂等）。

示例
----
# 1) 离线生成并校验（不联网）；多个来源事件按 ts 合并
python3 reflow/agent.py --events logs/run.events.jsonl logs/qa.events.jsonl \
    --evaluation-id <UUID> --session-id <SID>

# 2) 确认无误后发送（先发 running，再批量，最后终态）
python3 reflow/agent.py --events logs/run.events.jsonl \
    --evaluation-id <UUID> --session-id <SID> --send \
    --api-key-file ~/.gdps/api_key

# 3) 只发终态（已经跑过 running 的情况）
python3 reflow/agent.py ... --send --skip-start
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = REPO_ROOT / "reflow" / "s22_spec.json"
BOOTSTRAP = REPO_ROOT / "tools" / "reflow_bootstrap.py"
CHECKPOINT_ORDER = ["S22-P1", "S22-P2", "S22-P3", "S22-P4", "S22-P5", "S22-P6"]
TRACK_PRESETS = {
    "s22": {"profile": "S22-v1", "spec": REPO_ROOT / "reflow" / "s22_spec.json"},
    "s05": {"profile": "S05-v1", "spec": REPO_ROOT / "reflow" / "s05_spec.json"},
}

# 事件 -> 检查点/记录类型/状态（S22 任务包允许值，见 logs/spec 快照）
OBSERVATION_EVENTS = {
    "qa_answered": ("S22-P2", "answered"),
    "qa_unanswered": ("S22-P2", "unanswered"),
    "language_switched": ("S22-P3", "language_switched"),
    "language_switch_failed": ("S22-P3", "switch_failed"),
    "tracking_started": ("S22-P4", "tracking_started"),
    "tracking_lost": ("S22-P4", "tracking_lost"),
    "tracking_recovered": ("S22-P4", "tracking_recovered"),
    "tracking_finished": ("S22-P4", "tracking_finished"),
    "collision": ("S22-P4", "collision"),
    "interaction_started": ("S22-P5", "interaction_started"),
    "interaction_finished": ("S22-P5", "interaction_finished"),
    "interaction_no_response": ("S22-P5", "no_response"),
    "recommendation_provided": ("S22-P6", "recommendation_provided"),
    "recommendation_absent": ("S22-P6", "no_recommendation"),
}
ATTEMPT_EVENTS = {
    "speech_started": ("S22-P1", "speech_started"),
    "speech_finished": ("S22-P1", "speech_finished"),
    "speech_failed": ("S22-P1", "speech_failed"),
    "language_switch_attempt": ("S22-P3", "language_switched"),
}
# 各检查点“完成”的判定依据（简化：存在对应终态事件即视为完成；否则按实际降级）
DONE_EVENTS = {
    "S22-P2": {"answered"},
    "S22-P3": {"language_switched"},
    "S22-P4": {"tracking_finished"},
    "S22-P5": {"interaction_finished"},
    "S22-P6": {"recommendation_provided"},
}


def iso_now() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def die(msg: str, code: int = 2) -> None:
    print("[FAIL] " + str(msg), file=sys.stderr)
    raise SystemExit(code)


def load_bootstrap():
    if not BOOTSTRAP.is_file():
        die("找不到 tools/reflow_bootstrap.py（用于校验与 HTTP 调用）")
    spec = importlib.util.spec_from_file_location("reflow_bootstrap", str(BOOTSTRAP))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                die("%s:%d JSON 解析失败：%s" % (path, lineno, exc))
    return rows


def merge_events(groups: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """多来源事件按 ts 合并（稳定排序，缺失 ts 的排在最前）。"""
    merged: List[Dict[str, Any]] = []
    for group in groups:
        merged.extend(group)
    return sorted(merged, key=lambda ev: parse_ts(ev.get("ts")) or "")


def parse_ts(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ).isoformat(timespec="milliseconds")
    except ValueError:
        return None


class Builder:
    """把事件流转成三类上报 payload。"""

    def __init__(self, events: List[Dict[str, Any]], args: argparse.Namespace, spec=None):
        self.events = events
        self.args = args
        self.spec = spec
        self.run_id = args.run_id
        self.evaluation_id = args.evaluation_id
        self.session_id = args.session_id
        self.profile = args.profile
        self.warnings: List[str] = []

    # ---------- 通用 ----------
    def _ts(self, event: Dict[str, Any]) -> str:
        return parse_ts(event.get("ts")) or iso_now()

    def _record(self, cp: str, kind: str, status: str, ts: str, details=None, operation_id=None, attempt_no=None) -> Dict[str, Any]:
        record = {
            "record_id": "%s-%s-%s-%03d" % (self.run_id, cp, kind, self._seq),
            "checkpoint_id": cp,
            "record_kind": kind,
            "status": status,
            "reported_at": ts,
        }
        if details:
            record["details"] = details
        if operation_id:
            record["operation_id"] = operation_id
        if attempt_no is not None:
            record["attempt_no"] = attempt_no
        self._seq += 1
        return record

    # ---------- 检查点 ----------
    def checkpoints(self) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]]]:
        records: List[Dict[str, Any]] = []
        self._seq = 1
        per_cp: Dict[str, int] = {}
        control_records: List[Dict[str, Any]] = []

        # --- P1 定点讲解：exhibit_stable / narration_start / narration_end ---
        narrations: List[Dict[str, Any]] = []
        open_narr: Optional[Dict[str, Any]] = None
        attempts = 0
        for ev in self.events:
            etype = ev.get("type")
            if etype == "exhibit_stable":
                attempts += 1
            elif etype == "narration_start":
                open_narr = {
                    "exhibit_id": ev.get("exhibit_id") or ev.get("template_id"),
                    "exhibit_name": ev.get("exhibit_name"),
                    "started": self._ts(ev),
                }
            elif etype == "narration_end":
                entry = open_narr or {
                    "exhibit_id": ev.get("exhibit_id") or ev.get("template_id"),
                    "exhibit_name": ev.get("exhibit_name"),
                    "started": self._ts(ev),
                }
                entry["ended"] = self._ts(ev)
                entry["duration_s"] = ev.get("duration_s")
                narrations.append(entry)
                open_narr = None
        if open_narr is not None:  # 讲解未正常结束（中断/异常）
            open_narr["ended"] = None
            open_narr["duration_s"] = None
            narrations.append(open_narr)

        narration_ok = [n for n in narrations if n.get("ended") and (n.get("duration_s") or 0) >= 0.0]
        p1_details: Dict[str, Any] = {
            "recognition_attempts": attempts,
            "narration_count": len(narrations),
            "narration_completed_count": len(narration_ok),
            "exhibit_ids": sorted({n["exhibit_id"] for n in narrations if n.get("exhibit_id")}),
        }
        if narrations:
            p1_details["narration_total_s"] = round(
                sum(float(n.get("duration_s") or 0.0) for n in narrations), 2
            )
        if attempts == 0:
            p1_status = "skipped"
        elif not narrations:
            p1_status = "failed"
        elif len(narration_ok) == 0:
            p1_status = "partial"  # 已开始讲解但未正常结束（中断）
        elif len(narration_ok) < len(narrations):
            p1_status = "partial"
        else:
            p1_status = "completed"
        if narrations:
            first = narrations[0]
            for idx, n in enumerate(narrations, 1):
                records.append(
                    self._record(
                        "S22-P1",
                        "attempt",
                        "speech_finished" if n.get("ended") else "speech_failed",
                        n.get("ended") or n["started"],
                        details={"exhibit_id": n.get("exhibit_id"), "duration_s": n.get("duration_s")},
                        operation_id=n.get("exhibit_id"),
                        attempt_no=idx,
                    )
                )
            records.append(
                self._record("S22-P1", "checkpoint_result", p1_status, narrations[-1].get("ended") or narrations[-1]["started"], p1_details)
            )
        else:
            records.append(self._record("S22-P1", "checkpoint_result", "skipped", self.start_at(), p1_details))
        per_cp["S22-P1"] = len(narrations)

        # --- P2..P6：通用 observation / attempt 映射 ---
        for cp in ["S22-P2", "S22-P3", "S22-P4", "S22-P5", "S22-P6"]:
            obs = [ev for ev in self.events if OBSERVATION_EVENTS.get(ev.get("type"), (None,))[0] == cp]
            att = [ev for ev in self.events if ATTEMPT_EVENTS.get(ev.get("type"), (None,))[0] == cp]
            seen_status = set()
            for ev in obs:
                _, status = OBSERVATION_EVENTS[ev["type"]]
                seen_status.add(status)
                records.append(
                    self._record(cp, "observation", status, self._ts(ev), details=ev.get("details") or {})
                )
            for ev in att:
                _, status = ATTEMPT_EVENTS[ev["type"]]
                if "attempt" in self._kinds_for(cp):
                    seen_status.add(status)
                    records.append(self._record(cp, "attempt", status, self._ts(ev), details=ev.get("details") or {}))
            done = DONE_EVENTS.get(cp, set())
            if cp == "S22-P2" and "answered" in seen_status:
                status = "completed"
            elif cp == "S22-P3" and "language_switched" in seen_status:
                status = "completed"
            elif cp == "S22-P4" and "tracking_finished" in seen_status:
                status = "completed" if "collision" not in seen_status else "partial"
            elif cp == "S22-P5" and "interaction_finished" in seen_status:
                status = "completed"
            elif cp == "S22-P6" and "recommendation_provided" in seen_status:
                status = "completed"
            elif seen_status:
                status = "partial"
            else:
                status = "skipped"
            if obs:
                last_ts = self._ts(obs[-1])
            elif att:
                last_ts = self._ts(att[-1])
            else:
                last_ts = self.start_at()
            records.append(self._record(cp, "checkpoint_result", status, last_ts, details={}))
            per_cp[cp] = len(obs) + len(att)

        control_records = self._control_records()
        return records, per_cp, control_records

    def _control_records(self) -> List[Dict[str, Any]]:
        control_records: List[Dict[str, Any]] = []
        for idx, ev in enumerate([e for e in self.events if e.get("type") == "control_mode_changed"], 1):
            mode = ev.get("mode")
            if mode not in ("autonomous", "teleoperation", "assisted"):
                self.warnings.append("忽略非法 control mode：%r" % (mode,))
                continue
            control_records.append(
                {
                    "record_id": "%s-control-%03d" % (self.run_id, idx),
                    "changed_at": self._ts(ev),
                    "mode": mode,
                }
            )
        return control_records

    def generic_records(self):
        """通用模式：事件显式携带 checkpoint/record_kind/status（适配 S05 等非导览赛道）。

        事件类型 checkpoint_record：
          {"type": "checkpoint_record", "checkpoint_id": "S05-P1",
           "record_kind": "checkpoint_result", "status": "completed", "details": {...}}
        未被任何 checkpoint_result 覆盖的检查点 → 自动补 skipped（如实上报未执行）。
        """
        records: List[Dict[str, Any]] = []
        per_cp: Dict[str, int] = {}
        seq = 1
        for ev in self.events:
            if ev.get("type") != "checkpoint_record":
                continue
            cp = ev.get("checkpoint_id")
            status = ev.get("status")
            kind = ev.get("record_kind", "checkpoint_result")
            if not cp or not status:
                self.warnings.append("忽略缺少 checkpoint_id/status 的 checkpoint_record")
                continue
            record = {
                "record_id": ev.get("record_id") or "%s-%s-%s-%03d" % (self.run_id, cp, kind, seq),
                "checkpoint_id": cp,
                "record_kind": kind,
                "status": status,
                "reported_at": self._ts(ev),
            }
            if ev.get("details"):
                record["details"] = ev["details"]
            for key in ("operation_id", "attempt_no"):
                if ev.get(key) is not None:
                    record[key] = ev[key]
            records.append(record)
            per_cp[cp] = per_cp.get(cp, 0) + 1
            seq += 1

        known = list((self.spec or {}).get("checkpoints", {}).keys())
        covered = {r["checkpoint_id"] for r in records if r["record_kind"] == "checkpoint_result"}
        fallback_ts = self.end_at() or self.start_at()
        for cp in known:
            if cp in covered:
                continue
            records.append(
                {
                    "record_id": "%s-%s-skipped-%03d" % (self.run_id, cp, seq),
                    "checkpoint_id": cp,
                    "record_kind": "checkpoint_result",
                    "status": "skipped",
                    "reported_at": fallback_ts,
                }
            )
            per_cp[cp] = per_cp.get(cp, 0)
            seq += 1
        return records, per_cp, self._control_records()

    def _kinds_for(self, cp: str) -> List[str]:
        return {"S22-P1": ["attempt", "observation", "checkpoint_result"],
                "S22-P3": ["attempt", "observation", "checkpoint_result"]}.get(cp, ["observation", "checkpoint_result"])

    # ---------- 时间与状态 ----------
    def start_at(self) -> str:
        if self.args.start_at:
            return self.args.start_at
        for ev in self.events:
            if ev.get("type") == "run_start":
                ts = parse_ts(ev.get("ts"))
                if ts:
                    return ts
        if self.events:
            return self._ts(self.events[0])
        return iso_now()

    def end_at(self) -> Optional[str]:
        if self.args.end_at:
            return self.args.end_at
        for ev in reversed(self.events):
            if ev.get("type") == "run_end":
                return parse_ts(ev.get("ts"))
        return self._ts(self.events[-1]) if self.events else None

    def interrupted(self) -> bool:
        for ev in self.events:
            if ev.get("type") == "run_end" and ev.get("interrupted"):
                return True
        return False

    # ---------- 组装 ----------
    def build(self) -> Dict[str, Any]:
        if getattr(self.args, "mode", "auto") == "generic":
            records, per_cp, control_records = self.generic_records()
        else:
            records, per_cp, control_records = self.checkpoints()
        start_at = self.start_at()
        end_at = self.end_at()
        if end_at:
            late = [
                ev for ev in self.events
                if parse_ts(ev.get("ts")) and parse_ts(ev.get("ts")) > end_at
            ]
            if late:
                self.warnings.append(
                    "%d 条事件晚于 run_end（检查时钟或多来源合并顺序）" % len(late)
                )
        completed = sum(1 for r in records if r["record_kind"] == "checkpoint_result" and r["status"] == "completed")
        skipped = sum(1 for r in records if r["record_kind"] == "checkpoint_result" and r["status"] == "skipped")
        if self.args.task_status:
            task_status = self.args.task_status
        elif self.interrupted():
            task_status = "aborted"
        elif completed == 0:
            task_status = "failed"
        elif completed == len(CHECKPOINT_ORDER):
            task_status = "completed"
        else:
            task_status = "partial"

        start_report = {
            "schema_version": "1.0",
            "reporting_profile_version": self.profile,
            "report_id": "%s-report-start" % self.run_id,
            "evaluation_id": self.evaluation_id,
            "session_id": self.session_id,
            "start_at": start_at,
            "task_status": "running",
            "checkpoints": [],
            "control_records": control_records[:1],
        }
        note = "事件流自动汇总：%d 个检查点完成，%d 个跳过" % (completed, skipped)
        if self.args.note:
            note += "；" + self.args.note
        if self.warnings:
            note += "；警告：" + "；".join(self.warnings[:5])
        final_report = {
            "schema_version": "1.0",
            "reporting_profile_version": self.profile,
            "report_id": "%s-report-final" % self.run_id,
            "evaluation_id": self.evaluation_id,
            "session_id": self.session_id,
            "start_at": start_at,
            "task_status": task_status,
            "checkpoints": records,
            "control_records": control_records,
            "completion_note": note[:5000],
        }
        if end_at:
            final_report["end_at"] = end_at
        if self.args.avg_speed is not None:
            final_report["avg_speed_mps"] = self.args.avg_speed

        batches = []
        samples = [e for e in self.events if e.get("type") == "embodied_sample"]
        chunks, joint_names = self._chunks(samples)
        for idx, chunk in enumerate(chunks, 1):
            batch = {
                "schema_version": "1.0",
                "reporting_profile_version": self.profile,
                "evaluation_id": self.evaluation_id,
                "session_id": self.session_id,
                "robot_profile_version": self.args.robot_profile_version,
                "batch_id": "%s-embodied-batch-%03d" % (self.run_id, idx),
                "stream_id": self.args.embodied_stream_id or ("%s-joint-stream" % self.run_id),
                "samples": chunk,
            }
            if joint_names:
                batch["joint_names"] = joint_names
            batches.append(("embodied", batch))
        points = [e for e in self.events if e.get("type") == "trajectory_point"]
        point_chunks, _ = self._chunks(points)
        for idx, chunk in enumerate(point_chunks, 1):
            batches.append((
                "trajectory",
                {
                    "schema_version": "1.0",
                    "reporting_profile_version": self.profile,
                    "evaluation_id": self.evaluation_id,
                    "session_id": self.session_id,
                    "batch_id": "%s-trajectory-batch-%03d" % (self.run_id, idx),
                    "stream_id": self.args.trajectory_stream_id or ("%s-base-stream" % self.run_id),
                    "entity_type": self.args.entity_type,
                    "entity_id": self.args.entity_id,
                    "frame_id": self.args.frame_id,
                    "pose_source": self.args.pose_source,
                    "points": chunk,
                },
            ))
        return {"start": start_report, "final": final_report, "batches": batches, "per_cp": per_cp}

    @staticmethod
    def _chunks(rows: List[Dict[str, Any]], size: int = 200):
        """把事件行转成 API 样本；joint_names 提升到批次级（样本内不允许该字段）。

        返回 (chunks, joint_names)。同一流内关节顺序不可变，取首个非空值。
        """
        clean = []
        joint_names = None
        for row in rows:
            if joint_names is None and row.get("joint_names"):
                joint_names = list(row["joint_names"])
            item = {
                k: v
                for k, v in row.items()
                if k not in ("type", "seq", "schema_version", "joint_names", "ts")
            }
            clean.append(item)
        return [clean[i : i + size] for i in range(0, len(clean), size)], joint_names


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导览事件 → 平台回流上报（S22）")
    parser.add_argument(
        "--events",
        required=True,
        nargs="+",
        help="guide events JSONL，可给多个（相机 + 问答/底盘模块各写一份，按 ts 合并）",
    )
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--profile", default="")
    parser.add_argument("--run-id", default="", help="默认 <session前8>-<日期时间>")
    parser.add_argument("--out-dir", default="logs/reflow_agent")
    parser.add_argument("--spec", default="")
    parser.add_argument("--track", choices=["", "s22", "s05"], default="", help="赛道预设：决定默认 profile/spec")
    parser.add_argument(
        "--mode",
        choices=["auto", "generic"],
        default="auto",
        help="auto=S22 导览事件聚合；generic=事件显式携带 checkpoint_record（适配 S05 等）",
    )
    parser.add_argument("--start-at", default="")
    parser.add_argument("--end-at", default="")
    parser.add_argument("--task-status", default="", choices=["", "running", "completed", "partial", "failed", "aborted"])
    parser.add_argument("--note", default="")
    parser.add_argument("--avg-speed", type=float, default=None)
    parser.add_argument("--robot-profile-version", default="g1-lab-v1")
    parser.add_argument("--embodied-stream-id", default="")
    parser.add_argument("--trajectory-stream-id", default="")
    parser.add_argument("--entity-type", default="robot_base")
    parser.add_argument("--entity-id", default="g1-lab-001")
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--pose-source", default="slam")
    parser.add_argument("--send", action="store_true", help="真正发送（默认 dry-run）")
    parser.add_argument("--skip-start", action="store_true", help="不重复发 running 报告")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key-file", default="")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.track:
        preset = TRACK_PRESETS[args.track]
        if not args.profile:
            args.profile = preset["profile"]
        if not args.spec:
            args.spec = str(preset["spec"])
    if not args.profile:
        args.profile = "S22-v1"
    if not args.spec:
        args.spec = str(DEFAULT_SPEC)
    bootstrap = load_bootstrap()
    spec = bootstrap.load_spec(Path(args.spec))
    if spec is None:
        die("找不到任务包快照：%s" % args.spec)
    groups = []
    for raw_path in args.events:
        events_path = Path(raw_path)
        if not events_path.is_file():
            die("事件文件不存在：%s" % events_path)
        rows = read_jsonl(events_path)
        if not rows:
            print("[warn] 事件文件为空，已跳过：%s" % events_path, file=sys.stderr)
            continue
        groups.append(rows)
    events = merge_events(groups)
    if not events:
        die("所有事件文件都为空")
    if not args.run_id:
        stamp = datetime.now(TZ).strftime("%Y%m%d%H%M")
        args.run_id = "%s-%s" % (args.session_id[:8], stamp)
    builder = Builder(events, args, spec=spec)
    payloads = builder.build()
    problems: List[str] = []
    for name, payload in (("start", payloads["start"]), ("final", payloads["final"])):
        problems += ["%s: %s" % (name, p) for p in bootstrap.validate_payload("report", payload, spec=spec)]
    for kind, payload in payloads["batches"]:
        problems += ["%s: %s" % (kind, p) for p in bootstrap.validate_payload(kind, payload, spec=spec)]
    if problems:
        print("[FAIL] 生成的 payload 未通过校验：", file=sys.stderr)
        for item in problems:
            print("  - " + item, file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report-start.json").write_text(json.dumps(payloads["start"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "report-final.json").write_text(json.dumps(payloads["final"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for idx, (kind, payload) in enumerate(payloads["batches"], 1):
        (out_dir / ("%s-%03d.json" % (kind, idx))).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[OK] payload 校验通过（spec=%s）" % args.spec)
    print("  run_id      = %s" % args.run_id)
    print("  start_at    = %s" % payloads["start"]["start_at"])
    print("  end_at      = %s" % payloads["final"].get("end_at"))
    print("  task_status = %s" % payloads["final"]["task_status"])
    print("  checkpoints = %s" % ", ".join("%s:%d" % (k, v) for k, v in payloads["per_cp"].items()))
    print("  batches     = %d" % len(payloads["batches"]))
    print("  out_dir     = %s" % out_dir)
    if not args.send:
        print("  dry-run：未联网。确认后加 --send 发送。")
        return 0

    api_key = args.api_key_file or ""
    api = bootstrap.Api(args.base_url or bootstrap.DEFAULT_BASE_URL, bootstrap.load_key(argparse.Namespace(api_key_file=api_key)), out_dir / "requests")
    sent = 0
    if not args.skip_start:
        print("[send] running 报告 …")
        api.call("POST", "/reflow/tasks/report", body=payloads["start"])
        sent += 1
    for kind, payload in payloads["batches"]:
        print("[send] %s %s …" % (kind, payload["batch_id"]))
        api.call("POST", "/reflow/%s" % ("embodied/batch" if kind == "embodied" else "trajectories/batch"), body=payload)
        sent += 1
    print("[send] 终态报告 …")
    api.call("POST", "/reflow/tasks/report", body=payloads["final"])
    sent += 1
    print("[OK] 已发送 %d 个请求" % sent)

    status = api.call("GET", "/reflow/sessions/%s/status" % args.session_id)
    data = status.get("data") or {}
    intake = data.get("intake") or {}
    print("  completeness = %s" % intake.get("completeness_status"))
    print("  missing      = %s" % (intake.get("missing_checkpoint_ids") or []))
    print("  gaps         = %s" % (intake.get("sequence_gaps") or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
