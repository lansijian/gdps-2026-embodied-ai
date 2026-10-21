#!/usr/bin/env python3
"""GDPS 2026 在线回流 API 引导工具（读文档、拿快照、离线校验）。

只依赖标准库，兼容 Python 3.8（G1/Jetson 上直接可用）。
不会自动伪造数据：所有 POST 只发送你显式提供的 JSON。

用法示例
--------
# 0) 准备 Key（只读权限的文件，别提交到仓库）
export GDPS_API_KEY="$(cat ~/.gdps/api_key)"

# 1) 查任务目录（默认文旅导览 S22；实测用大写场景代码，cultural_services 查不到）
python3 tools/reflow_bootstrap.py tasks

# 2) 预览任务包（拿到 benchmark_task_id 后）
python3 tools/reflow_bootstrap.py preview --benchmark-task-id <UUID>

# 3) 建回流会话（评测中心拿到 evaluation_id 后）
python3 tools/reflow_bootstrap.py session --evaluation-id <UUID> --morphology wheeled

# 4) 冻结任务包 / 状态
python3 tools/reflow_bootstrap.py package --session-id <SID>
python3 tools/reflow_bootstrap.py status  --session-id <SID>

# 5) 上报前离线校验（不联网）
python3 tools/reflow_bootstrap.py validate --kind report --file report-final.json
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_BASE_URL = "https://platform.ieic.gdps.org.cn/api/v1"

# 赛道预设：spec 快照 + profile + 目录过滤用的 scene_code
TRACKS = {
    "s22": {
        "name": "S22 文旅导览",
        "profile": "S22-v1",
        "scene_code": "CULTURAL_TOURISM_EDUCATION",
        "spec": "reflow/s22_spec.json",
    },
    "s05": {
        "name": "S05 质检检测",
        "profile": "S05-v1",
        "scene_code": "INSPECTION_ANALYSIS",
        "spec": "reflow/s05_spec.json",
    },
}


def default_spec_path(track: str = "") -> Path:
    root = Path(__file__).resolve().parents[1]
    if track:
        return root / TRACKS[track]["spec"]
    return root / "reflow" / "s22_spec.json"
TZ = timezone(timedelta(hours=8))

MAX_RECORDS = 200
MAX_ID = 200
MAX_SHORT = 50
MAX_ENTITY = 100
MAX_VERSION = 100
MAX_NOTE = 5000

REQUIRED = {
    "report": [
        "schema_version",
        "reporting_profile_version",
        "report_id",
        "evaluation_id",
        "session_id",
        "start_at",
        "task_status",
        "checkpoints",
    ],
    "trajectory": [
        "schema_version",
        "reporting_profile_version",
        "evaluation_id",
        "session_id",
        "batch_id",
        "stream_id",
        "entity_type",
        "entity_id",
        "frame_id",
        "pose_source",
        "points",
    ],
    "embodied": [
        "schema_version",
        "reporting_profile_version",
        "evaluation_id",
        "session_id",
        "robot_profile_version",
        "batch_id",
        "stream_id",
        "samples",
    ],
}

ALLOWED_NESTED = {
    "checkpoint": {
        "record_id",
        "checkpoint_id",
        "record_kind",
        "operation_id",
        "attempt_no",
        "reported_at",
        "started_at",
        "ended_at",
        "status",
        "details",
        "evidence_refs",
    },
    "control": {"record_id", "changed_at", "mode", "checkpoint_id", "takeover_id"},
    "point": {
        "point_seq",
        "timestamp",
        "x_m",
        "y_m",
        "z_m",
        "yaw_rad",
        "orientation_xyzw",
        "checkpoint_id",
        "operation_id",
    },
    "sample": {
        "sample_seq",
        "timestamp",
        "joint_positions",
        "joint_velocities",
        "joint_efforts",
        "battery_pct",
        "mode",
        "sensors",
        "checkpoint_id",
        "operation_id",
    },
}


def _unknown_nested(item, allowed):
    return [k for k in item.keys() if k not in allowed]


ALLOWED_TOP_LEVEL = {
    "report": {
        "schema_version",
        "reporting_profile_version",
        "report_id",
        "evaluation_id",
        "session_id",
        "scene_id",
        "task_id",
        "start_at",
        "end_at",
        "task_status",
        "checkpoints",
        "control_records",
        "avg_speed_mps",
        "completion_note",
        "report_asset_ids",
    },
    "trajectory": {
        "schema_version",
        "reporting_profile_version",
        "evaluation_id",
        "session_id",
        "scene_id",
        "task_id",
        "batch_id",
        "stream_id",
        "entity_type",
        "entity_id",
        "frame_id",
        "pose_source",
        "points",
    },
    "embodied": {
        "schema_version",
        "reporting_profile_version",
        "evaluation_id",
        "session_id",
        "scene_id",
        "task_id",
        "robot_profile_version",
        "batch_id",
        "stream_id",
        "joint_names",
        "samples",
    },
}

ENUMS = {
    "task_status": {"running", "completed", "partial", "failed", "aborted"},
    "record_kind": {"attempt", "observation", "checkpoint_result"},
    "control_mode": {"autonomous", "teleoperation", "assisted"},
    "embodied_mode": {"autonomous", "teleoperation", "assisted", "unknown"},
    "entity_type": {"robot_base", "tool"},
    "pose_source": {"robot", "slam", "localization", "external"},
    "morphology": {"humanoid", "quadruped", "wheeled", "other"},
}


def now_stamp() -> str:
    return datetime.now(TZ).strftime("%Y%m%dT%H%M%S")


def build_ssl_context(insecure: bool):
    """优先用 certifi 的 CA 包，避免 macOS 自带 python 缺根证书；仅调试用 --insecure。"""
    if insecure:
        return ssl._create_unverified_context()
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def die(msg, code=2):
    print("[FAIL] " + str(msg), file=sys.stderr)
    raise SystemExit(code)


def ok(msg):
    print("[ OK ] " + str(msg))


class Api:
    def __init__(self, base_url: str, api_key: str, out_dir: Path, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.ssl_context = build_ssl_context(insecure)

    def call(self, method: str, path: str, body=None, extra_headers=None) -> dict:
        url = self.base_url + path
        data = None
        headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "gdps-reflow-bootstrap/1.0",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=45, context=self.ssl_context) as resp:
                status = resp.status
                payload = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            hint = ""
            if "CERTIFICATE" in reason.upper() or "SSL" in reason.upper():
                hint = "；证书问题：pip install certifi 重试，或临时加 --insecure（仅联调）"
            die("网络不可达：%s（base_url=%s）%s" % (reason, self.base_url, hint))

        elapsed_ms = int((time.time() - started) * 1000)
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"_raw": payload}

        request_id = parsed.get("request_id") if isinstance(parsed, dict) else None
        self._save(method, path, status, parsed, request_id)

        if status >= 400:
            err = parsed.get("error") if isinstance(parsed, dict) else None
            msg = (err or {}).get("message") or parsed.get("detail") or "HTTP %s" % status
            fields = (err or {}).get("field_errors") or []
            detail = "; ".join(
                "%s: %s" % (f.get("field"), f.get("message")) for f in fields
            )
            hint = ""
            if status == 422 and any(
                str(f.get("field", "")).lower().startswith("header.x-api-key") for f in fields
            ):
                hint = "（缺少/无效 X-API-Key：确认 Key 是否创建、是否被撤回）"
            die("HTTP %s %s%s%s | request_id=%s" % (status, msg, ("; " + detail) if detail else "", hint, request_id))
        return parsed

    def _save(self, method, path, status, parsed, request_id):
        safe = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        name = "%s_%s_%s_HTTP%d.json" % (now_stamp(), method, safe, status)
        record = {
            "ts": datetime.now(TZ).isoformat(timespec="milliseconds"),
            "method": method,
            "path": path,
            "http_status": status,
            "request_id": request_id,
            "response": parsed,
        }
        (self.out_dir / name).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_key(args) -> str:
    key = os.environ.get("GDPS_API_KEY", "").strip()
    if not key and args.api_key_file:
        path = Path(args.api_key_file).expanduser()
        if not path.is_file():
            die("API Key 文件不存在：%s" % path)
        key = path.read_text(encoding="utf-8").strip()
    if not key:
        die("缺少 API Key：设置环境变量 GDPS_API_KEY 或用 --api-key-file 指定文件")
    return key


def cmd_tasks(api: Api, args):
    query = {
        "page": str(args.page),
        "page_size": str(args.page_size),
    }
    scene_code = args.scene_code or (TRACKS[args.track]["scene_code"] if getattr(args, "track", "") else "CULTURAL_TOURISM_EDUCATION")
    if scene_code:
        query["scene_code"] = scene_code
    if args.task_code:
        query["task_code"] = args.task_code
    if args.q:
        query["q"] = args.q
    path = "/reflow/tasks?" + urllib.parse.urlencode(query)
    data = api.call("GET", path)
    body = data.get("data") or {}
    items = body.get("items") or []
    ok("目录返回 %d 条（total=%s）" % (len(items), body.get("total")))
    for it in items:
        print(
            "  - %s | %s | %s | profile=%s | benchmark_task_id=%s"
            % (
                it.get("scene_name") or it.get("scene_code"),
                it.get("task_name") or it.get("task_code"),
                it.get("version") or it.get("benchmark_version"),
                it.get("reporting_profile_version"),
                it.get("benchmark_task_id"),
            )
        )
    if not items:
        print(
            "  没有命中。下一步：去掉 --scene-code/--task-code 只留 --q 文旅；"
            "或试大写 scene_code=CULTURAL_TOURISM_EDUCATION；仍为空则联系赛事方确认发布状态。"
        )
    print("  快照已写入 %s" % api.out_dir)
    return data


def cmd_preview(api: Api, args):
    query = ""
    if args.morphology:
        query = "?morphology=" + urllib.parse.quote(args.morphology)
    data = api.call("GET", "/reflow/tasks/%s/task-package%s" % (args.benchmark_task_id, query))
    d = data.get("data") or {}
    ok("预览任务包 is_preview=%s" % d.get("is_preview"))
    print("  benchmark_version_id   = %s" % d.get("benchmark_version_id"))
    print("  reporting_profile_version = %s" % d.get("reporting_profile_version"))
    cps = d.get("checkpoints") or []
    print("  checkpoints = %d" % len(cps))
    for cp in cps[:30]:
        print(
            "    - %s | kinds=%s | statuses=%s | required_for_scoring=%s"
            % (
                cp.get("checkpoint_id"),
                cp.get("record_kinds"),
                cp.get("status_values"),
                cp.get("required_for_scoring"),
            )
        )
    chans = d.get("channels") or {}
    print("  channels = %s" % json.dumps(chans, ensure_ascii=False)[:400])
    print("  scoring = %s" % json.dumps(d.get("scoring"), ensure_ascii=False)[:400])
    print("  提示：预览的 opens_at/closes_at 与 robot_profile 为 null，正式以会话冻结任务包为准。")
    return data


def cmd_session(api: Api, args):
    if args.morphology not in ENUMS["morphology"]:
        die("morphology 必须是 %s" % sorted(ENUMS["morphology"]))
    idem = args.idempotency_key
    if not idem:
        idem = "%s-session-create" % now_stamp()
    if not (8 <= len(idem) <= 128):
        die("Idempotency-Key 必须 8–128 字符，当前 %d" % len(idem))
    body = {"evaluation_id": args.evaluation_id, "morphology": args.morphology}
    data = api.call("POST", "/reflow/sessions", body=body, extra_headers={"Idempotency-Key": idem})
    d = data.get("data") or {}
    ok("会话创建成功 HTTP 201（Idempotency-Key=%s）" % idem)
    print("  session_id                = %s" % d.get("session_id"))
    print("  reporting_profile_version = %s" % d.get("reporting_profile_version"))
    print("  upload_window             = %s" % json.dumps(d.get("upload_window"), ensure_ascii=False))
    print("  下一步：export SESSION_ID=%s" % d.get("session_id"))
    expected = args.expect_profile
    track = getattr(args, "track", "")
    if not expected and track:
        expected = TRACKS[track]["profile"]
    if not expected:
        spec = load_spec(default_spec_path())
        expected = (spec or {}).get("profile") or ""
    if expected and d.get("reporting_profile_version") != expected:
        print(
            "[WARN] 返回的 reporting_profile_version=%s 与期望 %s 不一致："
            "该 evaluation_id 很可能不是本赛道的评测任务，请勿上报数据，回评测中心重新发起。"
            % (d.get("reporting_profile_version"), expected),
            file=sys.stderr,
        )
    return data


def cmd_package(api: Api, args):
    data = api.call("GET", "/reflow/sessions/%s/task-package" % args.session_id)
    d = data.get("data") or {}
    ok("冻结任务包 reporting_profile_version=%s" % d.get("reporting_profile_version"))
    for cp in d.get("checkpoints") or []:
        print(
            "  - %s | kinds=%s | statuses=%s"
            % (cp.get("checkpoint_id"), cp.get("record_kinds"), cp.get("status_values"))
        )
    print("  channels = %s" % json.dumps(d.get("channels"), ensure_ascii=False)[:400])
    return data


def cmd_status(api: Api, args):
    data = api.call("GET", "/reflow/sessions/%s/status" % args.session_id)
    d = data.get("data") or {}
    intake = d.get("intake") or {}
    ok("session_status=%s task_status=%s completeness=%s"
       % (d.get("session_status"), d.get("task_status"), intake.get("completeness_status")))
    for key in ("automatic_scoring", "review"):
        print("  %s = %s" % (key, json.dumps(d.get(key), ensure_ascii=False)[:600]))
    missing = intake.get("missing_checkpoint_ids") or []
    gaps = intake.get("sequence_gaps") or []
    print("  missing_checkpoint_ids = %s" % missing)
    print("  sequence_gaps          = %s" % json.dumps(gaps, ensure_ascii=False)[:400])
    if missing:
        print("  → 需要补传：新报告 + 新 record_id，不要改已提交的终态记录。")
    if gaps:
        print("  → 在窗口内用原 stream_id 补缺失序号。")
    return data


def load_spec(path: Path):
    """读取任务包快照（reflow/s22_spec.json），用于离线校验检查点/记录类型/状态。"""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        die("spec 文件 JSON 解析失败：%s" % exc)
    table = {}
    for cp in spec.get("checkpoints") or []:
        table[cp["checkpoint_id"]] = {
            "record_kinds": cp.get("record_kinds") or [],
            "status_values": cp.get("status_values") or {},
        }
    return {
        "profile": spec.get("reporting_profile_version"),
        "checkpoints": table,
    }


def validate_payload(kind: str, payload: dict, spec=None):
    p = []
    allowed = ALLOWED_TOP_LEVEL[kind]
    unknown = [k for k in payload.keys() if k not in allowed]
    if unknown:
        p.append(
            "存在未定义顶层字段 %s（平台不接受未定义字段；注释/自定义字段请放到 details）"
            % ", ".join(sorted(unknown))
        )
    req = REQUIRED[kind]
    for field in req:
        if field not in payload:
            p.append("缺少必填字段 %s" % field)
    if payload.get("schema_version") != "1.0":
        p.append('schema_version 必须显式传字符串 "1.0"')
    if kind == "report":
        if payload.get("task_status") not in ENUMS["task_status"]:
            p.append("task_status 非法：%r" % payload.get("task_status"))
        cps = payload.get("checkpoints")
        if not isinstance(cps, list):
            p.append("checkpoints 必须是数组（可为 []）")
        else:
            if len(cps) > MAX_RECORDS:
                p.append("checkpoints 超过 %d 条" % MAX_RECORDS)
            seen = set()
            for i, cp in enumerate(cps):
                for f in ("record_id", "checkpoint_id", "record_kind", "status"):
                    if not cp.get(f):
                        p.append("checkpoints[%d] 缺少 %s" % (i, f))
                if cp.get("record_kind") not in ENUMS["record_kind"]:
                    p.append("checkpoints[%d].record_kind 非法：%r" % (i, cp.get("record_kind")))
                extra = _unknown_nested(cp, ALLOWED_NESTED["checkpoint"])
                if extra:
                    p.append("checkpoints[%d] 存在未定义字段 %s（details 内的字段不受此限）" % (i, ", ".join(extra)))
                if spec is not None:
                    known = spec["checkpoints"]
                    cid = cp.get("checkpoint_id")
                    if cid not in known:
                        p.append(
                            "checkpoints[%d].checkpoint_id 不在任务包中：%r（可用：%s）"
                            % (i, cid, ", ".join(sorted(known)))
                        )
                    else:
                        meta = known[cid]
                        rk = cp.get("record_kind")
                        if meta["record_kinds"] and rk not in meta["record_kinds"]:
                            p.append(
                                "checkpoints[%d] %s 不允许 record_kind=%r（允许：%s）"
                                % (i, cid, rk, meta["record_kinds"])
                            )
                        allowed = (meta["status_values"] or {}).get(rk) or []
                        if allowed and cp.get("status") not in allowed:
                            p.append(
                                "checkpoints[%d] %s/%s 不允许 status=%r（允许：%s）"
                                % (i, cid, rk, cp.get("status"), allowed)
                            )
                if cp.get("record_id"):
                    if cp["record_id"] in seen:
                        p.append("checkpoints[%d].record_id 重复：%s" % (i, cp["record_id"]))
                    seen.add(cp["record_id"])
                for f, limit in (("record_id", MAX_ID), ("checkpoint_id", MAX_SHORT), ("status", MAX_SHORT)):
                    v = cp.get(f)
                    if isinstance(v, str) and len(v) > limit:
                        p.append("checkpoints[%d].%s 超过 %d 字符" % (i, f, limit))
        ctrl = payload.get("control_records") or []
        if not isinstance(ctrl, list):
            p.append("control_records 必须是数组")
        elif len(ctrl) > MAX_RECORDS:
            p.append("control_records 超过 %d 条" % MAX_RECORDS)
        else:
            for i, c in enumerate(ctrl):
                for f in ("record_id", "changed_at", "mode"):
                    if not c.get(f):
                        p.append("control_records[%d] 缺少 %s" % (i, f))
                if c.get("mode") not in ENUMS["control_mode"]:
                    p.append("control_records[%d].mode 非法：%r" % (i, c.get("mode")))
                extra = _unknown_nested(c, ALLOWED_NESTED["control"])
                if extra:
                    p.append("control_records[%d] 存在未定义字段 %s" % (i, ", ".join(extra)))
        note = payload.get("completion_note")
        if isinstance(note, str) and len(note) > MAX_NOTE:
            p.append("completion_note 超过 %d 字符" % MAX_NOTE)
        if payload.get("task_status") in ("completed", "partial", "failed", "aborted") and not payload.get("end_at"):
            p.append("终态报告建议填写 end_at（缺失可能影响评分项）")
        if spec is not None and spec.get("profile") and payload.get("reporting_profile_version") != spec["profile"]:
            p.append(
                "reporting_profile_version=%r 与任务包快照 %r 不一致（每场以会话冻结任务包为准）"
                % (payload.get("reporting_profile_version"), spec["profile"])
            )
    elif kind == "trajectory":
        if payload.get("entity_type") not in ENUMS["entity_type"]:
            p.append("entity_type 非法：%r" % payload.get("entity_type"))
        if payload.get("pose_source") not in ENUMS["pose_source"]:
            p.append("pose_source 非法：%r" % payload.get("pose_source"))
        pts = payload.get("points")
        if not isinstance(pts, list) or not (1 <= len(pts) <= MAX_RECORDS):
            p.append("points 必须 1–%d 条" % MAX_RECORDS)
        else:
            for i, pt in enumerate(pts):
                for f in ("point_seq", "timestamp", "x_m", "y_m", "z_m"):
                    if f not in pt:
                        p.append("points[%d] 缺少 %s" % (i, f))
                seq = pt.get("point_seq")
                if not isinstance(seq, int) or seq < 0:
                    p.append("points[%d].point_seq 必须是非负整数" % i)
                ori = pt.get("orientation_xyzw")
                if ori is not None and (not isinstance(ori, list) or len(ori) != 4):
                    p.append("points[%d].orientation_xyzw 必须是 4 个数" % i)
                extra = _unknown_nested(pt, ALLOWED_NESTED["point"])
                if extra:
                    p.append("points[%d] 存在未定义字段 %s" % (i, ", ".join(extra)))
    elif kind == "embodied":
        if not payload.get("robot_profile_version"):
            p.append("robot_profile_version 必填（不能复制会话返回的 null）")
        names = payload.get("joint_names")
        if names is not None and (not isinstance(names, list) or len(names) > MAX_RECORDS):
            p.append("joint_names 必须 ≤%d 项的数组" % MAX_RECORDS)
        samples = payload.get("samples")
        if not isinstance(samples, list) or not (1 <= len(samples) <= MAX_RECORDS):
            p.append("samples 必须 1–%d 条" % MAX_RECORDS)
        else:
            for i, smp in enumerate(samples):
                for f in ("sample_seq", "timestamp", "mode"):
                    if f not in smp:
                        p.append("samples[%d] 缺少 %s" % (i, f))
                if smp.get("mode") not in ENUMS["embodied_mode"]:
                    p.append("samples[%d].mode 非法：%r" % (i, smp.get("mode")))
                has_payload = bool(smp.get("joint_positions")) or smp.get("battery_pct") is not None or bool(smp.get("sensors"))
                if not has_payload:
                    p.append("samples[%d] 不能只有 mode：需关节/电量/传感器至少一项" % i)
                if names and smp.get("joint_positions") is not None:
                    if len(smp["joint_positions"]) != len(names):
                        p.append("samples[%d].joint_positions 长度与 joint_names 不一致" % i)
                bp = smp.get("battery_pct")
                if bp is not None and not (0 <= bp <= 100):
                    p.append("samples[%d].battery_pct 越界（0–100）" % i)
                extra = _unknown_nested(smp, ALLOWED_NESTED["sample"])
                if extra:
                    p.append(
                        "samples[%d] 存在未定义字段 %s（joint_names 必须在批次级）" % (i, ", ".join(extra))
                    )
    return p


ENDPOINTS = {
    "report": "/reflow/tasks/report",
    "trajectory": "/reflow/trajectories/batch",
    "embodied": "/reflow/embodied/batch",
}


def cmd_send(api: Api, args):
    path = Path(args.file)
    if not path.is_file():
        die("文件不存在：%s" % path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    spec_path = Path(args.spec) if args.spec else default_spec_path(getattr(args, "track", ""))
    spec = load_spec(spec_path)
    problems = validate_payload(args.kind, payload, spec=spec)
    if problems:
        print("[FAIL] 校验未通过，未发送：" % (), file=sys.stderr)
        for item in problems:
            print("  - " + item, file=sys.stderr)
        raise SystemExit(1)
    ok("离线校验通过 → POST %s" % ENDPOINTS[args.kind])
    headers = {}
    if args.kind == "report" and args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key
    data = api.call("POST", ENDPOINTS[args.kind], body=payload, extra_headers=headers or None)
    d = data.get("data") or {}
    print("  回执 = %s" % json.dumps(d, ensure_ascii=False)[:800])
    return data


def cmd_validate(args):
    path = Path(args.file)
    if not path.is_file():
        die("文件不存在：%s" % path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die("JSON 解析失败：%s" % exc)
    spec_path = Path(args.spec) if args.spec else default_spec_path(getattr(args, "track", ""))
    spec = load_spec(spec_path)
    if spec is None:
        print("[warn] 未找到任务包快照 %s，跳过检查点/状态校验（可用 --spec 指定）" % spec_path)
    problems = validate_payload(args.kind, payload, spec=spec)
    if problems:
        print("[FAIL] %d 个问题：" % len(problems), file=sys.stderr)
        for item in problems:
            print("  - " + item, file=sys.stderr)
        raise SystemExit(1)
    ok("%s 校验通过（离线，未联网）" % args.kind)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="GDPS 在线回流 API 引导工具（stdlib only）")
    parser.add_argument("--base-url", default=os.environ.get("GDPS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-file", default=os.environ.get("GDPS_API_KEY_FILE", ""))
    parser.add_argument("--out-dir", default="logs/reflow", help="请求/响应快照目录")
    parser.add_argument("--insecure", action="store_true", help="跳过 TLS 校验（仅联调排障，正式不要用）")
    parser.add_argument("--track", choices=sorted(TRACKS), default="", help="赛道预设 s22/s05：决定默认 spec 与期望 profile")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tasks", help="查询可回流任务目录")
    p.add_argument("--scene-code", default="")
    p.add_argument("--task-code", default="")
    p.add_argument("--q", default="")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("preview", help="预览赛道任务包")
    p.add_argument("--benchmark-task-id", required=True)
    p.add_argument("--morphology", default="wheeled")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("session", help="绑定评测任务并创建回流会话")
    p.add_argument("--evaluation-id", required=True)
    p.add_argument("--morphology", default="wheeled")
    p.add_argument("--idempotency-key", default="")
    p.add_argument("--expect-profile", default="", help="期望的 reporting_profile_version；不填时按 --track 预设（如 S22-v1）")
    p.set_defaults(track="")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("package", help="获取会话冻结任务包")
    p.add_argument("--session-id", required=True)
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("status", help="查询回流接收/评分/评审状态")
    p.add_argument("--session-id", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("send", help="校验后上报一份 JSON（report/trajectory/embodied）")
    p.add_argument("--kind", choices=["report", "trajectory", "embodied"], required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--spec", default="", help="任务包快照 JSON（默认 reflow/s22_spec.json）")
    p.add_argument("--idempotency-key", default="", help="仅 report 使用（可选）")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("validate", help="上报前离线校验 JSON（不联网）")
    p.add_argument("--kind", choices=["report", "trajectory", "embodied"], required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--spec", default="", help="任务包快照 JSON（默认 reflow/s22_spec.json）")
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)

    api = Api(args.base_url, load_key(args), Path(args.out_dir), insecure=args.insecure)
    args.func(api, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
