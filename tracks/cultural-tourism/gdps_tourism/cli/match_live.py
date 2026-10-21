"""Live webcam / single-image exhibit matching."""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .._cv2 import require_cv2
from ..camera.video_source import (
    ImageSource,
    VideoFileSource,
    WebcamSource,
    default_camera_backend,
    list_cameras,
    open_camera_source,
)
from ..matching.feature_matcher import ExhibitMatcher, TemplateLibrary
from ..matching.temporal_filter import TemporalVoteFilter
from ..matching.types import MatchResult, StableMatch
from .overlay import ChineseTextRenderer, draw_homography_quad, draw_hud

# <repo>/tracks/cultural-tourism/gdps_tourism/cli/match_live.py
# Both anchors are derived from __file__ so the CLI also works when the tree is
# copied together with its template directory.
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # repository root
PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # tracks/cultural-tourism

# 导览事件统一使用 +08:00 时间戳，与平台回流要求一致（ISO 8601，显式时区）。
_EVENT_TZ = timezone(timedelta(hours=8))


def _iso_now() -> str:
    return datetime.now(_EVENT_TZ).isoformat(timespec="milliseconds")


DEFAULT_MATCHER: Dict[str, Any] = {
    "method": "sift",
    "max_side": 1200,
    "max_features": 1500,
    "ratio_test": 0.70,
    "ransac_reproj_px": 5.0,
    "min_inliers": 20,
    "min_inlier_ratio": 0.40,
    "min_confidence": 0.50,
    "min_margin": 0.15,
    "confidence_full_inliers": 120.0,
    "confidence_full_ratio": 0.60,
    "confidence_full_margin": 0.50,
    "top_k": 3,
    "fast_reject_features": 0,
    # Coarse ORB prefilter + exact-match shortlist (see docs/INTERFACE_CONTRACT_v1.md).
    "prefilter": "orb",
    "prefilter_top_k": 3,
    "dedupe": True,
}

DEFAULT_TEMPORAL: Dict[str, Any] = {
    "window_s": 1.0,
    "min_vote_ratio": 0.6,
    "hold_s": 1.6,
    # 0 = derive from the measured camera fps / video.match_every; a positive
    # value is an explicit manual override for cameras that report no fps.
    "assumed_match_rate": 0.0,
}

DEFAULT_VIDEO: Dict[str, Any] = {
    "match_every": 2,
    "output_fps": 0.0,
}

# prefilter_reason values that mean "fell back to an exact scan of every template".
_PREFILTER_FALLBACK_REASONS = frozenset({"low_score", "low_margin", "too_few_templates"})

DEFAULT_CAMERA: Dict[str, Any] = {
    "index": 0,
    "width": 1280,
    "height": 720,
    "backend": default_camera_backend(),
}

_WINDOW_NAME = "GDPS tourism target matching (q/ESC)"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match exhibit templates from a webcam or a single image."
    )
    parser.add_argument(
        "--templates",
        default=os.environ.get("GDPS_TOURISM_TEMPLATES"),
        help="template image directory (or GDPS_TOURISM_TEMPLATES)",
    )
    parser.add_argument(
        "--camera",
        type=str,
        default=None,
        help="camera index/path (default 0; e.g. 1, /dev/video2 or an RTSP URL)",
    )
    parser.add_argument("--image", default=None, help="match one image and print JSON")
    parser.add_argument(
        "--video",
        default=None,
        help="replay a video file instead of a camera (headless friendly)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="list video devices and exit",
    )
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="replay --video as fast as possible instead of pacing to its fps",
    )
    parser.add_argument("--config", default=None, help="optional YAML/JSON config")
    parser.add_argument("--method", choices=("sift", "orb"), default=None)
    parser.add_argument(
        "--prefilter",
        choices=("orb", "off"),
        default=None,
        help="coarse prefilter before the exact scan (default from config: orb)",
    )
    parser.add_argument(
        "--prefilter-top-k",
        type=int,
        default=None,
        help="number of templates kept by the coarse prefilter (default 3)",
    )
    parser.add_argument(
        "--match-every",
        type=int,
        default=None,
        help="only push every Nth frame into the matcher (default 2; 1 = every frame)",
    )
    parser.add_argument(
        "--no-dedupe",
        dest="dedupe",
        action="store_false",
        default=None,
        help="keep byte-identical templates in the competition (default: deduped)",
    )
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument(
        "--backend",
        choices=("dshow", "msmf", "avfoundation", "v4l2", "realsense", "any"),
        default=None,
        help="camera backend (default: platform native; realsense needs pyrealsense2)",
    )
    parser.add_argument("--headless", action="store_true", help="no preview window")
    parser.add_argument("--log-jsonl", default=None, help="write one JSON object per match")
    parser.add_argument(
        "--events-jsonl",
        default=None,
        help="写结构化导览事件（默认与 --log-jsonl 同目录：<log>.events.jsonl）；供 reflow/agent.py 转成回流上报记录",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="press 's' in the preview to save the raw frame here",
    )
    parser.add_argument(
        "--capture-frame",
        default=None,
        help="capture one webcam frame to this path and run matching on it",
    )
    parser.add_argument(
        "--countdown",
        type=float,
        default=8.0,
        help="seconds to wait before --capture-frame (default 8)",
    )
    parser.add_argument("--min-inliers", type=int, default=None, help="override acceptance threshold")
    parser.add_argument("--min-inlier-ratio", type=float, default=None)
    parser.add_argument("--min-confidence", type=float, default=None)
    parser.add_argument("--min-margin", type=float, default=None)
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N frames (debug)")
    parser.add_argument(
        "--control-mode",
        default=None,
        choices=("autonomous", "teleoperation", "assisted"),
        help="声明本场实际控制模式；会作为 control_mode_changed 事件写入 --events-jsonl（不传则不写入）",
    )
    parser.add_argument(
        "--tts",
        dest="tts",
        action="store_true",
        help="启用语音合成播报展品讲解词 (macOS: say；Linux: espeak-ng)",
    )
    parser.add_argument("--no-tts", dest="tts", action="store_false", help="关闭语音播报")
    return parser


def _load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        from shared.utils.config_loader import load_mapping
    except ImportError as exc:  # pragma: no cover - depends on launch directory
        raise RuntimeError(
            "cannot import shared.utils.config_loader; run from the repository root"
        ) from exc
    return dict(load_mapping(path))


def _section(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError("config section %r must be a mapping" % name)
    return value


def _merged(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(defaults)
    result.update({key: value for key, value in overrides.items() if value is not None})
    return result


def _supported_matcher_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Drop prefilter/dedupe options an older matching core does not understand.

    Keeps the CLI usable while the matching core is upgraded independently; the
    final core accepts every key, so nothing is dropped.
    """
    if not extra:
        return {}
    try:
        import inspect

        parameters = inspect.signature(ExhibitMatcher.__init__).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return dict(extra)
    dropped = sorted(key for key in extra if key not in parameters)
    if dropped:
        print(
            "[warn] matching core ignores unsupported options: %s" % ", ".join(dropped),
            flush=True,
        )
    return {key: value for key, value in extra.items() if key in parameters}


def _build_matcher(templates_dir: str, matcher_cfg: Dict[str, Any]):
    requested = str(matcher_cfg["method"]).lower()
    library = TemplateLibrary.from_directory(
        templates_dir,
        method=requested,
        max_side=int(matcher_cfg["max_side"]),
        max_features=int(matcher_cfg["max_features"]),
    )
    matcher = ExhibitMatcher(
        library,
        max_side=int(matcher_cfg["max_side"]),
        ratio=float(matcher_cfg["ratio_test"]),
        ransac_reproj_px=float(matcher_cfg["ransac_reproj_px"]),
        min_inliers=int(matcher_cfg["min_inliers"]),
        min_inlier_ratio=float(matcher_cfg["min_inlier_ratio"]),
        min_confidence=float(matcher_cfg["min_confidence"]),
        min_margin=float(matcher_cfg["min_margin"]),
        confidence_full_inliers=float(matcher_cfg["confidence_full_inliers"]),
        confidence_full_ratio=float(matcher_cfg["confidence_full_ratio"]),
        confidence_full_margin=float(matcher_cfg["confidence_full_margin"]),
        top_k=int(matcher_cfg["top_k"]),
        **_supported_matcher_extra(
            {
                "prefilter": str(matcher_cfg["prefilter"]).lower(),
                "prefilter_top_k": int(matcher_cfg["prefilter_top_k"]),
                "dedupe": bool(matcher_cfg["dedupe"]),
                "fast_reject_features": int(matcher_cfg.get("fast_reject_features", 0)),
            }
        ),
    )
    return library, matcher


def _print_templates(library: TemplateLibrary, matcher: ExhibitMatcher) -> None:
    print("[templates] %d (%s)" % (len(library), matcher.method_used), flush=True)
    for info in library.templates:
        print(
            "  #%02d  kp=%-5d  %s"
            % (info.index + 1, info.keypoint_count, info.template_id),
            flush=True,
        )


def _candidate_dict(candidate) -> Dict[str, Any]:
    return {
        "index": candidate.info.index + 1,
        "template_id": candidate.template_id,
        "display_name": candidate.display_name,
        "confidence": round(candidate.confidence, 4),
        "inliers": candidate.inliers,
        "good_matches": candidate.good_matches,
        "inlier_ratio": round(candidate.inlier_ratio, 4),
        "geometry_valid": candidate.geometry_valid,
    }


def _result_dict(result: MatchResult) -> Dict[str, Any]:
    return {
        "accepted": result.accepted,
        "unknown_reason": result.unknown_reason,
        "best": _candidate_dict(result.best) if result.best is not None else None,
        "top": [_candidate_dict(candidate) for candidate in result.candidates],
        "diagnostics": result.diagnostics,
    }


class _MatcherWorker(threading.Thread):
    """Match the newest frame while the main thread keeps the preview alive."""

    def __init__(
        self,
        matcher: ExhibitMatcher,
        vote_filter: TemporalVoteFilter,
        frame_queue: "queue.Queue[Tuple[int, Any]]",
        result_queue: "queue.Queue[Tuple]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self.matcher = matcher
        self.vote_filter = vote_filter
        self.frame_queue = frame_queue
        self.result_queue = result_queue
        self.stop_event = stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                frame_id, frame = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            started = time.perf_counter()
            try:
                result = self.matcher.match(frame)
                stable = self.vote_filter.update(result)
            except Exception as exc:  # noqa: BLE001 - surfaced to the main thread
                self._put(("error", frame_id, exc))
                return
            match_ms = (time.perf_counter() - started) * 1000.0
            self._put(("result", frame_id, result, stable, match_ms))

    def _put(self, item: Tuple) -> None:
        try:
            self.result_queue.put_nowait(item)
        except queue.Full:
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.result_queue.put_nowait(item)
            except queue.Full:
                pass


def _run_capture(
    args: argparse.Namespace,
    matcher: ExhibitMatcher,
    camera_cfg: Dict[str, Any],
) -> int:
    """Show a countdown, capture one frame, then match it."""

    cv2 = require_cv2()
    if args.countdown < 0:
        raise ValueError("--countdown must be non-negative")
    source = open_camera_source(
        index=camera_cfg["index"],
        width=int(camera_cfg["width"]),
        height=int(camera_cfg["height"]),
        backend=str(camera_cfg["backend"]),
    )
    target = Path(args.capture_frame)
    target.parent.mkdir(parents=True, exist_ok=True)
    preview = not args.headless and _display_available()
    if preview:
        cv2.namedWindow(_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(_WINDOW_NAME, source.width, source.height)
        try:
            cv2.setWindowProperty(_WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass

    start = time.perf_counter()
    frame = None
    try:
        while True:
            current = source.read()
            if current is None:
                break
            frame = current
            remaining = float(args.countdown) - (time.perf_counter() - start)
            if preview:
                display = frame.copy()
                cv2.putText(
                    display,
                    "Capturing in %.1fs - hold the exhibit photo" % max(0.0, remaining),
                    (20, 42),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow(_WINDOW_NAME, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    return 1
            if remaining <= 0:
                break
    finally:
        source.release()
        if preview:
            cv2.destroyAllWindows()

    if frame is None:
        raise RuntimeError("camera returned no frames")

    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise RuntimeError("cannot encode the captured frame")
    target.write_bytes(encoded.tobytes())

    started = time.perf_counter()
    result = matcher.match(frame)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload = {
        "image": str(target),
        "method": matcher.method_used,
        "elapsed_ms": round(elapsed_ms, 2),
    }
    payload.update(_result_dict(result))
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

    renderer = ChineseTextRenderer()
    annotated = frame.copy()
    stable = None
    if result.accepted and result.best is not None:
        stable = StableMatch(
            template_id=result.best.template_id,
            display_name=result.best.display_name,
            confidence=result.best.confidence,
            raw_accepted=True,
            reason=None,
            template_index=result.best.info.index,
        )
        draw_homography_quad(annotated, result.best)
    draw_hud(annotated, stable, result, renderer, progress_text="captured frame")
    ok, encoded = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if ok:
        annotated_path = target.with_name(target.stem + "_annotated.jpg")
        annotated_path.write_bytes(encoded.tobytes())
        print("[snapshot] %s" % target, flush=True)
        print("[annotated] %s" % annotated_path, flush=True)
    return 0 if result.accepted else 1


def _run_image(args: argparse.Namespace, matcher: ExhibitMatcher) -> int:
    with ImageSource(args.image) as source:
        frame = source.read()
    if frame is None:
        raise RuntimeError("cannot read image: %s" % args.image)
    started = time.perf_counter()
    result = matcher.match(frame)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload = {
        "image": str(args.image),
        "templates": len(matcher.library),
        "method": matcher.method_used,
        "elapsed_ms": round(elapsed_ms, 2),
    }
    payload.update(_result_dict(result))
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.accepted else 1


def _prefilter_sample(result: Optional[MatchResult]) -> Optional[Tuple[bool, float]]:
    """Extract (fell_back_to_full_scan, prefilter_ms) from one matcher result.

    Returns None when the matching core has no prefilter diagnostics or when the
    prefilter is disabled, so the fallback rate only counts frames that actually
    ran the coarse stage.
    """
    diagnostics = getattr(result, "diagnostics", None) or {}
    if "prefilter_reason" not in diagnostics:
        return None
    reason = diagnostics.get("prefilter_reason")
    if reason == "disabled":
        return None
    if "full_scan_used" in diagnostics:
        # The matcher only reports a fallback when it actually swept every template;
        # a low-confidence vote that still resolved on the shortlist is not a fallback.
        return bool(diagnostics.get("full_scan_used")), float(diagnostics.get("prefilter_ms") or 0.0)
    return reason in _PREFILTER_FALLBACK_REASONS, float(diagnostics.get("prefilter_ms") or 0.0)


def _display_available() -> bool:
    """True when a GUI window can be created on this machine.

    A Unitree G1 is normally driven over SSH with no X server, where
    cv2.imshow would abort the process, so the live loop falls back to
    headless automatically.
    """

    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _speak_async(text: str) -> None:
    """Announce the exhibit without blocking the capture loop."""

    def _worker(payload: str) -> None:
        import shutil
        import subprocess

        if sys.platform == "darwin":
            command = ["say", "-v", "Tingting", payload]
        else:
            engine = shutil.which("espeak-ng") or shutil.which("espeak")
            if not engine:
                return
            command = [engine, "-v", "zh", payload]
        try:
            subprocess.run(command, check=False)
        except OSError:
            pass

    threading.Thread(target=_worker, args=(text,), daemon=True).start()


def _run_live(
    args: argparse.Namespace,
    matcher: ExhibitMatcher,
    camera_cfg: Dict[str, Any],
    temporal_cfg: Dict[str, Any],
    video_cfg: Dict[str, Any],
    source=None,
    source_label: Optional[str] = None,
) -> int:
    cv2 = require_cv2()
    match_every = int(video_cfg["match_every"])
    if match_every < 1:
        raise ValueError("video.match_every must be at least 1")

    if source is None:
        source = open_camera_source(
            index=camera_cfg["index"],
            width=int(camera_cfg["width"]),
            height=int(camera_cfg["height"]),
            backend=str(camera_cfg["backend"]),
        )
        label = "camera %s" % (camera_cfg["index"],)
    else:
        label = source_label or "source"
    print(
        "[source] %s  %dx%d  %.1ffps  match_every=%d"
        % (label, source.width, source.height, source.fps, match_every),
        flush=True,
    )

    # The temporal window is configured in seconds, so it must be converted with
    # this session's real match rate: measured camera fps / match_every. The
    # configured assumed_match_rate is only a fallback for cameras that report
    # no frame rate at all.
    camera_fps = float(getattr(source, "fps", 0.0) or 0.0)
    if camera_fps > 0.0:
        match_rate = camera_fps / float(match_every)
        rate_note = "camera %.1ffps / match_every %d" % (camera_fps, match_every)
    else:
        configured_rate = float(temporal_cfg.get("assumed_match_rate", 0.0) or 0.0)
        if configured_rate > 0.0:
            match_rate = configured_rate
            rate_note = "temporal.assumed_match_rate fallback %.1f" % configured_rate
        else:
            match_rate = 5.0
            rate_note = "fallback 5.0 match/s (camera reports no fps)"
    vote_filter = TemporalVoteFilter.from_seconds(
        window_s=float(temporal_cfg["window_s"]),
        min_vote_ratio=float(temporal_cfg["min_vote_ratio"]),
        hold_s=float(temporal_cfg["hold_s"]),
        match_rate=match_rate,
    )
    print(
        "[temporal] window=%d min_votes=%d hold=%d (%.1f match/s: %s)"
        % (
            vote_filter.window,
            vote_filter.min_votes,
            vote_filter.hold_results,
            match_rate,
            rate_note,
        ),
        flush=True,
    )

    frame_queue: "queue.Queue[Tuple[int, Any]]" = queue.Queue(maxsize=1)
    result_queue: "queue.Queue[Tuple]" = queue.Queue(maxsize=1)
    stop_event = threading.Event()
    worker = _MatcherWorker(matcher, vote_filter, frame_queue, result_queue, stop_event)
    worker.start()

    preview = not args.headless and _display_available()
    if not args.headless and not preview:
        print(
            "[preview] 未检测到显示环境（DISPLAY/WAYLAND_DISPLAY 为空），自动切换 headless 模式",
            flush=True,
        )
    if preview:
        cv2.namedWindow(_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(_WINDOW_NAME, source.width, source.height)
        try:
            cv2.setWindowProperty(_WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass

    renderer = ChineseTextRenderer()
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else None
    if snapshot_dir is not None:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_seq = 0
    log_handle = None
    if args.log_jsonl:
        log_path = Path(args.log_jsonl)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(str(log_path), "w", encoding="utf-8")

    # 结构化导览事件：供 reflow/agent.py 转成平台回流记录（P1 定点讲解等）。
    # 与逐帧 jsonl 分开，文件小、可读、可回放。
    events_handle = None
    events_seq = 0
    events_path: Optional[Path] = None
    if getattr(args, "events_jsonl", None):
        events_path = Path(args.events_jsonl)
    elif args.log_jsonl:
        events_path = Path(args.log_jsonl).with_name(Path(args.log_jsonl).stem + ".events.jsonl")
    if events_path is not None:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_handle = open(str(events_path), "w", encoding="utf-8", buffering=1)

    def emit(event_type: str, **fields: Any) -> None:
        nonlocal events_seq
        if events_handle is None:
            return
        events_seq += 1
        record: Dict[str, Any] = {
            "schema_version": "1.0",
            "seq": events_seq,
            "ts": _iso_now(),
            "type": event_type,
        }
        record.update(fields)
        try:
            events_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - 事件写入失败不应中断导览
            print("[events] 写入失败 seq=%d type=%s: %r" % (events_seq, event_type, exc), file=sys.stderr, flush=True)

    # template_id -> (展品组 ID, 展品组中文名)：同一展品的多张模板归组
    template_groups: Dict[str, Tuple[str, str]] = {}
    try:
        for tpl in matcher.library.templates:
            template_groups[tpl.template_id] = (
                tpl.exhibit_id or tpl.template_id,
                tpl.exhibit_name or tpl.display_name,
            )
    except Exception:
        template_groups = {}

    active_exhibit: Optional[Dict[str, Any]] = None

    def close_active(reason: str) -> None:
        nonlocal active_exhibit
        if active_exhibit is None:
            return
        now = time.perf_counter()
        emit(
            "exhibit_left",
            template_id=active_exhibit["template_id"],
            exhibit_id=active_exhibit["exhibit_id"],
            exhibit_name=active_exhibit["exhibit_name"],
            dwell_s=round(max(0.0, now - active_exhibit["started_perf"]), 2),
            reason=reason,
        )
        if active_exhibit.get("narration_perf") is not None:
            emit(
                "narration_end",
                template_id=active_exhibit["template_id"],
                exhibit_id=active_exhibit["exhibit_id"],
                exhibit_name=active_exhibit["exhibit_name"],
                duration_s=round(max(0.0, now - active_exhibit["narration_perf"]), 2),
                reason=reason,
            )
        active_exhibit = None

    emit(
        "run_start",
        source=label,
        match_every=match_every,
        template_count=len(template_groups),
        match_rate=round(match_rate, 3),
    )
    if getattr(args, "control_mode", None):
        emit("control_mode_changed", mode=args.control_mode, source="run_start")

    # 尝试加载知识库讲解词
    kb_narrations: Dict[str, Dict[str, str]] = {}
    templates_root = Path(args.templates or ".")
    for kb_path in (
        templates_root / "knowledge_base.json",
        templates_root.parent / "knowledge_base.json",
        PACKAGE_ROOT / "knowledge_base.json",
        PROJECT_ROOT / "knowledge_base.json",
    ):
        if kb_path.is_file():
            try:
                kb_content = json.loads(kb_path.read_text(encoding="utf-8"))
                for item in kb_content.get("exhibits", []) + kb_content.get("composite_boards", []):
                    info = {
                        "name": item.get("name", ""),
                        "short_summary": item.get("short_summary", ""),
                        "narration": item.get("narration", ""),
                    }
                    kb_narrations[item.get("id")] = info
                    kb_narrations[item.get("name")] = info
                    for img_f in item.get("associated_images", []):
                        kb_narrations[Path(img_f).stem] = info
            except Exception:
                pass
            break

    result: Optional[MatchResult] = None
    stable: Optional[StableMatch] = None
    last_stable_key = None
    match_count = 0
    match_ms_total = 0.0
    prefilter_scanned = 0
    prefilter_fallbacks = 0
    prefilter_ms_total = 0.0
    frame_id = 0
    display_start = time.perf_counter()
    last_headless_status = display_start
    # --video replay is paced to the file fps so match_every / temporal voting
    # behave the same way as with a live camera (use --no-realtime to benchmark).
    pace_interval = 0.0
    if (
        getattr(args, "video", None)
        and not getattr(args, "no_realtime", False)
        and float(getattr(source, "fps", 0.0) or 0.0) > 0.0
    ):
        pace_interval = 1.0 / float(source.fps)

    interrupted = False
    try:
        while True:
            frame = source.read()
            if frame is None:
                break
            frame_id += 1
            if pace_interval > 0.0:
                delay = display_start + frame_id * pace_interval - time.perf_counter()
                if delay > 0.0:
                    time.sleep(delay)
            # Scheme C: only every N-th frame is investigated while the preview
            # keeps updating at the full camera rate.
            if frame_id % match_every == 0:
                try:
                    frame_queue.put_nowait((frame_id, frame.copy()))
                except queue.Full:
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        frame_queue.put_nowait((frame_id, frame.copy()))
                    except queue.Full:
                        pass

            try:
                while True:
                    item = result_queue.get_nowait()
                    if item[0] == "error":
                        raise RuntimeError("matcher worker failed: %s" % item[2])
                    _tag, _item_frame, result, stable, match_ms = item
                    match_count += 1
                    match_ms_total += match_ms
                    pref_sample = _prefilter_sample(result)
                    if pref_sample is not None:
                        pref_fallback, pref_ms = pref_sample
                        prefilter_scanned += 1
                        prefilter_ms_total += pref_ms
                        if pref_fallback:
                            prefilter_fallbacks += 1
                    if log_handle is not None:
                        log_handle.write(
                            json.dumps(
                                {
                                    "ts": _iso_now(),
                                    "frame_id": _item_frame,
                                    "match_ms": round(match_ms, 2),
                                    "stable_id": stable.template_id,
                                    "stable_name": stable.display_name,
                                    "stable_confidence": round(stable.confidence, 4),
                                    "raw": _result_dict(result),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
            except queue.Empty:
                pass

            if stable is not None:
                stable_key = (stable.template_id, stable.template_index)
                if stable_key != last_stable_key:
                    last_stable_key = stable_key
                    if stable.template_id is not None:
                        best = result.best if result is not None else None
                        disp_name = stable.display_name or stable.template_id or ""
                        print(
                            "[MATCH] #%02d %s conf=%.2f inliers=%s"
                            % (
                                (stable.template_index or 0) + 1,
                                disp_name,
                                stable.confidence,
                                best.inliers if best is not None else "-",
                            ),
                            flush=True,
                        )
                        close_active("switch")
                        exhibit_id, exhibit_name = template_groups.get(
                            stable.template_id, (stable.template_id, disp_name)
                        )
                        active_exhibit = {
                            "template_id": stable.template_id,
                            "exhibit_id": exhibit_id,
                            "exhibit_name": exhibit_name,
                            "started_perf": time.perf_counter(),
                            "narration_perf": None,
                        }
                        emit(
                            "exhibit_stable",
                            template_id=stable.template_id,
                            exhibit_id=exhibit_id,
                            exhibit_name=exhibit_name,
                            confidence=round(stable.confidence, 4),
                            inliers=best.inliers if best is not None else None,
                            frame_id=_item_frame,
                        )
                        narration_info = kb_narrations.get(stable.template_id) or kb_narrations.get(disp_name)
                        if narration_info:
                            summary = narration_info.get("short_summary", "")
                            if summary:
                                print(f"📢 [讲解词速览] {summary}", flush=True)
                            tts_enabled = bool(getattr(args, "tts", False))
                            if tts_enabled:
                                speech_text = f"识别到展品：{disp_name}。" + (summary[:80] if summary else "")
                                _speak_async(speech_text)
                            active_exhibit["narration_perf"] = time.perf_counter()
                            emit(
                                "narration_start",
                                template_id=stable.template_id,
                                exhibit_id=exhibit_id,
                                exhibit_name=exhibit_name,
                                has_summary=bool(summary),
                                tts=tts_enabled,
                            )
                        else:
                            emit(
                                "narration_unavailable",
                                template_id=stable.template_id,
                                exhibit_id=exhibit_id,
                                exhibit_name=exhibit_name,
                            )
                    else:
                        reason = stable.reason or "unknown"
                        close_active("unknown")
                        print("[UNKNOWN] %s" % reason, flush=True)
                        emit("exhibit_unknown", reason=reason, frame_id=_item_frame)

            elapsed = time.perf_counter() - display_start
            display_fps = frame_id / elapsed if elapsed > 0 else 0.0
            match_fps = match_count / elapsed if elapsed > 0 else 0.0
            if preview:
                raw_frame = frame
                display = frame.copy() if snapshot_dir is not None else frame
                progress = "display %.1ffps  match %.1ffps (every %d)  matches=%d" % (
                    display_fps,
                    match_fps,
                    match_every,
                    match_count,
                )
                draw_hud(display, stable, result, renderer, progress_text=progress)
                if result is not None and result.accepted and result.best is not None:
                    draw_homography_quad(display, result.best)
                cv2.imshow(_WINDOW_NAME, display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("s") and snapshot_dir is not None:
                    snapshot_seq += 1
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    snapshot_path = snapshot_dir / ("live_%s_%03d.jpg" % (stamp, snapshot_seq))
                    ok, encoded = cv2.imencode(
                        ".jpg", raw_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]
                    )
                    if ok:
                        snapshot_path.write_bytes(encoded.tobytes())
                        print("[snapshot] %s" % snapshot_path, flush=True)
                if key in (27, ord("q")):
                    break
            elif (time.perf_counter() - last_headless_status) >= 5.0:
                last_headless_status = time.perf_counter()
                stable_label = stable.display_name if stable is not None else None
                print(
                    "[live] frames=%d matches=%d display_fps=%.1f match_fps=%.1f "
                    "mean_match=%.1fms stable=%s"
                    % (
                        frame_id,
                        match_count,
                        display_fps,
                        match_fps,
                        match_ms_total / match_count if match_count else 0.0,
                        stable_label or "-",
                    ),
                    flush=True,
                )
            if args.max_frames and frame_id >= args.max_frames:
                break
    except KeyboardInterrupt:
        interrupted = True
        # Ctrl+C must still reach the [done] summary below (SSH sessions rely on it).
        print("", flush=True)
        print("[interrupt] 收到 Ctrl+C，正在退出并汇总统计…", flush=True)
    finally:
        close_active("run_end")
        emit(
            "run_end",
            interrupted=interrupted,
            frames=frame_id,
            matches=match_count,
            mean_match_ms=round(match_ms_total / match_count, 2) if match_count else 0.0,
        )
        if events_handle is not None:
            events_handle.close()
        stop_event.set()
        try:
            frame_queue.put_nowait((frame_id, None))
        except queue.Full:
            pass
        worker.join(timeout=2.0)
        source.release()
        if log_handle is not None:
            log_handle.close()
        if preview:
            cv2.destroyAllWindows()

    elapsed = time.perf_counter() - display_start
    mean_match_ms = match_ms_total / match_count if match_count else 0.0
    mean_prefilter_ms = prefilter_ms_total / prefilter_scanned if prefilter_scanned else 0.0
    fallback_text = "n/a"
    if prefilter_scanned:
        fallback_text = "%.1f%% (%d/%d)" % (
            100.0 * prefilter_fallbacks / prefilter_scanned,
            prefilter_fallbacks,
            prefilter_scanned,
        )
    print(
        "[done] frames=%d matches=%d  display=%.1ffps  match=%.1ffps  "
        "mean_match=%.1fms  mean_prefilter=%.1fms  prefilter_fallback=%s"
        % (
            frame_id,
            match_count,
            frame_id / elapsed if elapsed > 0 else 0.0,
            match_count / elapsed if elapsed > 0 else 0.0,
            mean_match_ms,
            mean_prefilter_ms,
            fallback_text,
        ),
        flush=True,
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    if getattr(args, "list_cameras", False):
        devices = list_cameras()
        if devices:
            for device in devices:
                print("  %-16s %s" % (device["index"], device.get("name") or ""), flush=True)
        else:
            print("[cameras] 未自动枚举到设备；请检查 ls -l /dev/video* 或 --backend", flush=True)
        return 0

    templates_dir = args.templates or os.environ.get("GDPS_TOURISM_TEMPLATES")
    if not templates_dir:
        raise ValueError("--templates or GDPS_TOURISM_TEMPLATES is required")

    config = _load_config(args.config)
    matcher_cfg = _merged(DEFAULT_MATCHER, _section(config, "matcher"))
    temporal_cfg = _merged(DEFAULT_TEMPORAL, _section(config, "temporal"))
    camera_cfg = _merged(DEFAULT_CAMERA, _section(config, "camera"))
    video_cfg = _merged(DEFAULT_VIDEO, _section(config, "video"))
    if args.method:
        matcher_cfg["method"] = args.method
    if args.camera is not None:
        camera_cfg["index"] = args.camera
    if args.width is not None:
        camera_cfg["width"] = args.width
    if args.height is not None:
        camera_cfg["height"] = args.height
    if args.backend is not None:
        camera_cfg["backend"] = args.backend
    if args.min_inliers is not None:
        matcher_cfg["min_inliers"] = args.min_inliers
    if args.min_inlier_ratio is not None:
        matcher_cfg["min_inlier_ratio"] = args.min_inlier_ratio
    if args.min_confidence is not None:
        matcher_cfg["min_confidence"] = args.min_confidence
    if args.min_margin is not None:
        matcher_cfg["min_margin"] = args.min_margin
    # CLI flags win over the config file for the optimisation switches.
    if args.prefilter is not None:
        matcher_cfg["prefilter"] = args.prefilter
    if args.prefilter_top_k is not None:
        matcher_cfg["prefilter_top_k"] = args.prefilter_top_k
    if args.dedupe is not None:
        matcher_cfg["dedupe"] = args.dedupe
    if args.match_every is not None:
        video_cfg["match_every"] = args.match_every

    prefilter_mode = str(matcher_cfg["prefilter"]).strip().lower()
    if prefilter_mode not in ("orb", "off"):
        raise ValueError(
            "matcher.prefilter/--prefilter must be 'orb' or 'off', got %r"
            % matcher_cfg["prefilter"]
        )
    matcher_cfg["prefilter"] = prefilter_mode
    matcher_cfg["prefilter_top_k"] = int(matcher_cfg["prefilter_top_k"])
    if matcher_cfg["prefilter_top_k"] < 1:
        raise ValueError(
            "matcher.prefilter_top_k/--prefilter-top-k must be at least 1"
        )
    matcher_cfg["dedupe"] = bool(matcher_cfg["dedupe"])
    video_cfg["match_every"] = int(video_cfg["match_every"])
    if video_cfg["match_every"] < 1:
        raise ValueError("video.match_every/--match-every must be at least 1")

    library, matcher = _build_matcher(templates_dir, matcher_cfg)
    _print_templates(library, matcher)

    if args.image:
        return _run_image(args, matcher)
    if getattr(args, "capture_frame", None):
        return _run_capture(args, matcher, camera_cfg)
    if getattr(args, "video", None):
        source = VideoFileSource(args.video)
        return _run_live(
            args,
            matcher,
            camera_cfg,
            temporal_cfg,
            video_cfg,
            source=source,
            source_label="video %s" % args.video,
        )
    return _run_live(args, matcher, camera_cfg, temporal_cfg, video_cfg)


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\n[interrupt] 已中断（启动阶段或非实时路径）", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
