#!/usr/bin/env python3
"""Cultural-tourism guide node: navigation + camera + Doubao dialogue.

Modes:
  --dry-run   full workflow timeline without ROS / camera / cloud (default on a PC)
  default     ROS 2 Foxy mode: NavigateToPose action + /tourism/guide_event +
              G1 audio + Doubao realtime session

Start signal: /tourism/start (std_msgs/String JSON, e.g. {"mode":"tour","greeting":true})
or --autostart for on-site debugging.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

from gdps_tourism.guide.camera import CameraConfig, ExhibitCamera
from gdps_tourism.guide.doubao_realtime import (
    DoubaoConfig,
    DoubaoRealtimeClient,
    G1AudioIO,
    NullAudioIO,
)
from gdps_tourism.guide.budget import Budget
from gdps_tourism.guide.flow import Action, ActionKind, FlowConfig, GuideState, TourFlow
from gdps_tourism.guide.knowledge_base import load_knowledge_base
from gdps_tourism.guide.offline_audio import FallbackDialogue, OfflineAudioDialogue
from gdps_tourism.guide.orchestrator import GuideOrchestrator, OrchestratorConfig
from gdps_tourism.guide.scene import DialogueKnowledge, build_greeting_scene
from gdps_tourism.guide.stations import StationBook


class GuideLogSink:
    """Writes every action to JSONL; publishes END/FINISH/NAV to the nav team."""

    def __init__(self, ros, log_path: Optional[Path] = None) -> None:
        self.ros = ros
        self.log_path = log_path
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")

    def emit(self, action: Action) -> None:
        record = {
            "ts": round(time.time(), 3),
            "kind": action.kind.value,
            "payload": action.payload,
            "state": None,
        }
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.ros is not None:
            if action.kind is ActionKind.END_SIGNAL:
                self.ros.publish_event(action.payload)
            elif action.kind is ActionKind.FINISH:
                self.ros.publish_event({"type": "FINISHED", "reason": action.payload.get("reason"), "ts": time.time()})
            elif action.kind is ActionKind.NAVIGATE:
                self.ros.publish_event(
                    {
                        "type": "NAV_REQUEST",
                        "station_id": action.payload.get("station_id"),
                        "station_name": action.payload.get("station_name"),
                        "frame_id": action.payload.get("frame_id"),
                        "x": action.payload.get("x"),
                        "y": action.payload.get("y"),
                        "yaw": action.payload.get("yaw"),
                        "eta_s": action.payload.get("eta_s"),
                        "ts": time.time(),
                    }
                )
        print("[guide] " + json.dumps(record, ensure_ascii=False), flush=True)


class RosNavigator:
    def __init__(self, ros) -> None:
        self.ros = ros

    async def go_to(self, payload: Dict[str, Any]) -> bool:
        self.ros.send_goal(payload)
        return True

    async def stop(self, reason: str) -> None:
        self.ros.cancel_goal()


class DoubaoDialogueAdapter:
    """Maps the orchestrator dialogue port onto the realtime client."""

    def __init__(self, client: DoubaoRealtimeClient) -> None:
        self.client = client

    async def update_scene(self, scene) -> None:
        await self.client.update_scene(scene)

    async def narrate(self, text: str) -> None:
        await self.client.narrate(text)

    async def cancel_speech(self) -> None:
        await self.client.cancel_response()

    async def listen(self) -> None:
        await self.client.unmute()

    async def speak_brief(self, text: str) -> None:
        await self.client.speak_brief(text)


def _tool_reply(tool, flow: TourFlow, knowledge: DialogueKnowledge, book: StationBook) -> str:
    if tool.name == "request_next_station":
        target = str(tool.arguments.get("target_name") or "").strip()
        if target:
            resolution = book.resolve_target(target)
            if resolution.ok:
                return "正在前往%s。" % resolution.station.name
            return "无法前往%s，请告诉游客该地点不在可到达范围，并给出附近可去的点位。" % target
        next_station = flow.current_station
        return "正在前往%s。" % (next_station.name if next_station else "下一站")
    if tool.name == "stop_narration":
        return "已停止讲解。"
    if tool.name == "request_recommendation":
        return "可推荐清单：\n" + knowledge.recommendations_text()
    return "已执行。"


async def async_main(args: argparse.Namespace) -> int:
    book = StationBook.load(Path(args.stations))
    knowledge = DialogueKnowledge.load(Path(args.knowledge) if args.knowledge else None)
    exhibit_kb = load_knowledge_base(Path(args.templates)) if args.templates else None

    camera = None
    ros = None
    audio = None
    client = None
    sink = None
    try:
        budget = Budget(
            total_s=args.total_budget_s,
            reserve_s=args.budget_reserve_s,
            max_station_s=args.station_max_s,
            max_narration_s=args.narration_max_s,
        )
        flow = TourFlow(
            book,
            FlowConfig(
                auto_advance=not args.no_auto_advance,
                listen_idle_end_s=args.listen_idle_end_s,
                narration_max_s=args.narration_max_s,
                station_max_s=args.station_max_s,
            ),
        )
        if not args.no_ros:
            from gdps_tourism.guide.ros2_adapters import RosBridge, RosConfig

            ros = RosBridge(
                RosConfig(
                    action_name=args.action_name,
                    visual_target_topic=args.visual_target_topic,
                )
            )
            ros.start()
        log_path = Path(args.log_dir) / ("guide_%s.jsonl" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        sink = GuideLogSink(ros, log_path)
        camera = ExhibitCamera(
            CameraConfig(
                templates_dir=args.templates or "",
                method=args.method,
                prefilter=args.prefilter,
                device=str(args.camera),
                backend=args.backend,
                video_path=args.video,
                min_accept_confidence=args.min_confidence,
                image_topic=args.image_topic,
            )
        )
        camera.start(
            {station.station_id: list(station.exhibit_ids) for station in book.stations},
            ros=ros,
        )
        audio = NullAudioIO() if args.null_audio else G1AudioIO(volume=args.volume)
        client = DoubaoRealtimeClient(
            DoubaoConfig(voice=args.voice, hotwords=(exhibit_kb.hotwords[:80] if exhibit_kb else [])),
            audio,
            on_event=None,
            on_error=lambda message: asyncio.ensure_future(_on_error(sink, message)),
        )
        offline = None
        dialogue_port = DoubaoDialogueAdapter(client)
        if args.offline_audio_dir:
            offline = OfflineAudioDialogue.from_dir(args.offline_audio_dir)
            offline.on_missing = lambda text: sink.emit(
                Action(ActionKind.LOG, {"event": "offline_audio_missing", "text": text[:40]})
            )
            dialogue_port = FallbackDialogue(dialogue_port, offline)
        orchestrator = GuideOrchestrator(
            flow=flow,
            dialogue=dialogue_port,
            navigator=RosNavigator(ros) if ros is not None else _NoopNavigator(),
            camera=camera,
            sink=sink,
            knowledge=knowledge,
            config=OrchestratorConfig(),
            exhibit_titles=(exhibit_kb.titles if exhibit_kb else {}),
            narrations=(exhibit_kb.narrations if exhibit_kb else {}),
            short_summaries=(exhibit_kb.short_summaries if exhibit_kb else {}),
            budget=budget,
        )

        async def on_event(event) -> None:
            if event.kind == "fc.done" and event.tool is not None:
                await orchestrator.on_tool_call(event.tool.name, event.tool.arguments)
                await client.send_tool_result(
                    event.tool.call_id, _tool_reply(event.tool, flow, knowledge, book)
                )
            elif event.kind == "audio.done":
                await orchestrator.on_speech_finished()
            elif event.kind == "asr.completed":
                sink.emit(Action(ActionKind.LOG, {"event": "asr", "text": event.text}))
            elif event.kind == "error":
                await _on_error(sink, "doubao: %s" % (event.text or event.payload))
            elif event.kind == "response.done":
                sink.emit(Action(ActionKind.LOG, {"event": "response_done"}))

        client._on_event = on_event
        greeting_scene = build_greeting_scene(knowledge=knowledge)
        if offline is not None:
            offline.on_finished = lambda: asyncio.ensure_future(orchestrator.on_speech_finished())
        if args.offline:
            if offline is None:
                raise RuntimeError("--offline 需要同时给 --offline-audio-dir")
            dialogue_port.degraded = True
            sink.emit(Action(ActionKind.LOG, {"event": "offline_mode", "audio_dir": args.offline_audio_dir}))
        else:
            try:
                await client.connect(greeting_scene)
            except Exception as exc:
                if offline is None:
                    raise
                dialogue_port.degraded = True
                sink.emit(
                    Action(
                        ActionKind.LOG,
                        {"event": "doubao_unavailable_offline_fallback", "error": str(exc)[:200]},
                    )
                )
                print("[guide][warn] 豆包不可用，切换本地音频兜底：%s" % exc, file=sys.stderr, flush=True)

        started = asyncio.Event()

        async def start_tour(payload: Dict[str, Any]) -> None:
            if started.is_set():
                return
            started.set()
            budget.start()
            await sink_async(orchestrator.execute(flow.start(greeting=bool(payload.get("greeting", args.greeting)))))

        async def poll_ros() -> None:
            while True:
                await asyncio.sleep(0.05)
                if ros is None:
                    continue
                for event in ros.poll_events():
                    if event["type"] == "start":
                        await start_tour(event.get("payload") or {})
                    elif event["type"] == "nav_arrived":
                        await orchestrator.on_navigation_arrived(str(event.get("station_id")))
                    elif event["type"] == "visual_target":
                        payload = event.get("payload") or {}
                        exhibit_id = str(payload.get("exhibit_id") or "")
                        if exhibit_id:
                            await orchestrator.on_visual_target(
                                exhibit_id,
                                float(payload.get("confidence") or 0.0),
                                str(payload.get("source") or "external"),
                            )
                    elif event["type"] == "nav_failed":
                        sink.emit(
                            Action(
                                ActionKind.LOG,
                                {"event": "navigation_failed", "payload": event},
                            )
                        )
                    elif event["type"] == "health":
                        if not ros.healthy:
                            sink.emit(Action(ActionKind.LOG, {"event": "nav_unhealthy", "payload": event.get("payload")}))

        async def idle_loop() -> None:
            next_report = time.monotonic() + 60.0
            while True:
                await asyncio.sleep(1.0)
                if not started.is_set():
                    continue
                await orchestrator.on_idle_timeout()
                await orchestrator.on_budget_check()
                now = time.monotonic()
                if now >= next_report:
                    next_report = now + 60.0
                    sink.emit(
                        Action(
                            ActionKind.LOG,
                            {
                                "event": "budget",
                                "elapsed_s": round(budget.elapsed_s(), 1),
                                "remaining_s": round(budget.remaining_s(), 1),
                                "state": flow.state.value,
                            },
                        )
                    )

        async def route_scan_loop() -> None:
            while True:
                await asyncio.sleep(max(0.5, args.scan_interval))
                if not started.is_set() or flow.state is not GuideState.NAVIGATING:
                    continue
                station_id = await camera.scan_route()
                if station_id:
                    await orchestrator.on_landmark(station_id)

        async def vision_nav_loop() -> None:
            """Vision-triggered navigation: see exhibit -> walk to its station -> narrate."""

            last_trigger_at = 0.0
            while True:
                await asyncio.sleep(max(0.3, args.vision_nav_interval))
                if not args.vision_nav or not started.is_set():
                    continue
                if flow.state not in (GuideState.GREETING, GuideState.LISTENING):
                    continue
                now = time.monotonic()
                if now - last_trigger_at < args.vision_nav_cooldown:
                    continue
                exhibit_id, confidence = await camera.scan_exhibit()
                if not exhibit_id or confidence < args.vision_min_confidence:
                    continue
                station = book.station_for_exhibit(exhibit_id)
                if station is None or station.station_id == flow.current_station_id:
                    continue
                last_trigger_at = now
                sink.emit(
                    Action(
                        ActionKind.LOG,
                        {
                            "event": "vision_nav_trigger",
                            "exhibit_id": exhibit_id,
                            "station_id": station.station_id,
                            "confidence": round(float(confidence), 3),
                        },
                    )
                )
                await orchestrator.on_visual_target(exhibit_id, confidence, "vision_loop")

        tasks = [
            asyncio.ensure_future(poll_ros()),
            asyncio.ensure_future(idle_loop()),
            asyncio.ensure_future(route_scan_loop()),
            asyncio.ensure_future(vision_nav_loop()),
        ]
        if args.autostart:
            await start_tour({"greeting": args.greeting})
        else:
            print("[guide] 等待 /tourism/start（或加 --autostart）", flush=True)
        await started.wait()
        while flow.state is not GuideState.FINISHED:
            await asyncio.sleep(0.5)
        for task in tasks:
            task.cancel()
        return 0
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        if camera is not None:
            camera.close()
        if ros is not None:
            ros.stop()


class _NoopNavigator:
    async def go_to(self, payload: Dict[str, Any]) -> bool:
        return True

    async def stop(self, reason: str) -> None:
        return None


async def _on_error(sink: Optional[GuideLogSink], message: str) -> None:
    if sink is not None:
        sink.emit(Action(ActionKind.LOG, {"event": "error", "message": message}))
    print("[guide][error] " + message, file=sys.stderr, flush=True)


async def sink_async(coroutine) -> None:
    await coroutine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cultural-tourism guide node")
    parser.add_argument("--stations", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--knowledge", default=None, help="knowledge_dialogue.json")
    parser.add_argument("--templates", default=os.environ.get("GDPS_TOURISM_TEMPLATES"), help="exhibit templates dir")
    parser.add_argument("--camera", default="0")
    parser.add_argument("--backend", default=None)
    parser.add_argument("--video", default=None, help="replay video instead of a camera (dry dev)")
    parser.add_argument("--image-topic", default=None, help="ROS sensor_msgs/Image topic (instead of /dev/video*)")
    parser.add_argument("--action-name", default="/navigate_to_pose", help="Nav2 NavigateToPose action")
    parser.add_argument("--visual-target-topic", default="/tourism/visual_target")
    parser.add_argument("--vision-nav", action="store_true", help="enable vision-triggered navigation")
    parser.add_argument("--vision-nav-interval", type=float, default=1.0)
    parser.add_argument("--vision-nav-cooldown", type=float, default=20.0)
    parser.add_argument("--vision-min-confidence", type=float, default=0.75)
    parser.add_argument("--method", choices=("sift", "orb"), default="orb")
    parser.add_argument("--prefilter", choices=("orb", "off"), default="orb")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--null-audio", action="store_true", help="no G1 speaker/mic (laptop tests)")
    parser.add_argument("--offline-audio-dir", default=None, help="pre-generated fallback wav directory")
    parser.add_argument("--offline", action="store_true", help="never connect to Doubao; use local wav only")
    parser.add_argument("--no-ros", action="store_true", help="no ROS bridge (debug without rclpy)")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--greeting", action="store_true", help="open with the P1 intake greeting")
    parser.add_argument("--no-auto-advance", action="store_true")
    parser.add_argument("--listen-idle-end-s", type=float, default=30.0)
    parser.add_argument("--narration-max-s", type=float, default=120.0)
    parser.add_argument("--scan-interval", type=float, default=2.0, help="route landmark scan period")
    parser.add_argument("--total-budget-s", type=float, default=1800.0, help="whole mission budget (default 30 min)")
    parser.add_argument("--budget-reserve-s", type=float, default=180.0, help="reserve for closing/recovery")
    parser.add_argument("--station-max-s", type=float, default=180.0, help="hard cap per station")
    parser.add_argument("--log-dir", default="logs/tourism")
    parser.add_argument("--dry-run", action="store_true", help="run the scripted dry-run timeline and exit")
    parser.add_argument("--dry-run-out", default=None)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.dry_run:
        from gdps_tourism.guide.dryrun import run_dry_tour

        summary = asyncio.run(
            run_dry_tour(
                Path(args.stations),
                knowledge_path=Path(args.knowledge) if args.knowledge else None,
                out_json=Path(args.dry_run_out) if args.dry_run_out else None,
            )
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\n[guide] 已中断", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
