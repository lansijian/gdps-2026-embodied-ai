#!/usr/bin/env python3
"""On-robot guide self test: real camera + real Doubao + workflow, NO robot motion.

Drives the real TourFlow/GuideOrchestrator with a MockNavigator (navigation is
skipped) and a real ExhibitCamera + DoubaoRealtimeClient.  At each simulated
station arrival it observes the camera, narrates a truncated station narration
through Doubao (audible), waits for the audio to finish, then simulates the
visitor saying "go to the next point" via the function-call path.

Usage:
    export DOUBAO_API_KEY=...
    python3 scripts/tourism/guide_selftest.py --camera 4 --flip 180 \
        --stations 2 --truncate 120 --play
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from gdps_tourism.guide.camera import CameraConfig, ExhibitCamera  # noqa: E402
from gdps_tourism.guide.doubao_realtime import (  # noqa: E402
    DoubaoConfig,
    DoubaoRealtimeClient,
    G1AudioIO,
    NullAudioIO,
)
from gdps_tourism.guide.dryrun import MockDialogue, MockNavigator  # noqa: E402
from gdps_tourism.guide.flow import Action, ActionKind, FlowConfig, GuideState, TourFlow  # noqa: E402
from gdps_tourism.guide.knowledge_base import load_knowledge_base  # noqa: E402
from gdps_tourism.guide.offline_audio import (  # noqa: E402
    G1WavPlayer,
    OfflineAudioDialogue,
    SubprocessPlayer,
)
from gdps_tourism.guide.orchestrator import GuideOrchestrator  # noqa: E402
from gdps_tourism.guide.scene import DialogueKnowledge, build_greeting_scene  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402


class NullDialogue:
    """Offline dialogue port: no network, no cost (flow / camera / END only)."""

    async def update_scene(self, scene) -> None:
        return None

    async def narrate(self, text: str) -> None:
        return None

    async def cancel_speech(self) -> None:
        return None

    async def listen(self) -> None:
        return None

    async def speak_brief(self, text: str) -> None:
        return None


class DialogueAdapter:
    def __init__(self, client) -> None:
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


class RecordingSink:
    def __init__(self) -> None:
        self.actions = []

    def emit(self, action: Action) -> None:
        self.actions.append(action)
        if action.kind in (ActionKind.END_SIGNAL, ActionKind.NAVIGATE):
            print("[selftest]", action.kind.value, json.dumps(action.payload, ensure_ascii=False)[:160], flush=True)


async def run(args) -> int:
    book = StationBook.load(Path(args.stations_config))
    knowledge = DialogueKnowledge.load(Path(args.knowledge) if args.knowledge else None)
    kb = load_knowledge_base(Path(args.templates))
    narrations = {key: text[: args.truncate] for key, text in kb.narrations.items()}

    camera = ExhibitCamera(
        CameraConfig(
            templates_dir=args.templates,
            method=args.method,
            prefilter="orb",
            device=str(args.camera),
            flip=args.flip,
            fast_reject_features=0,
        )
    )
    camera.start({station.station_id: list(station.exhibit_ids) for station in book.stations})

    events = []
    done = asyncio.Event()
    received = {"bytes": 0}

    async def on_event(event):
        events.append(event.kind)
        if event.kind == "audio.delta":
            received["bytes"] += len(event.payload.get("delta") or "")
        if event.kind == "audio.done":
            done.set()

    client = None
    audio = NullAudioIO()
    if args.doubao:
        if not os.environ.get("DOUBAO_API_KEY", "").strip():
            print("--doubao 需要 DOUBAO_API_KEY（会产生 API 费用）", file=sys.stderr)
            return 2
        audio = NullAudioIO() if not args.play else G1AudioIO(volume=args.volume)
        client = DoubaoRealtimeClient(
            DoubaoConfig(voice=args.voice),
            audio,
            on_event=on_event,
            on_error=lambda message: print("[selftest][doubao-error]", message, file=sys.stderr),
        )
        dialogue_port = DialogueAdapter(client)
        mode = "doubao"
    elif args.offline_audio_dir:
        player = G1WavPlayer(volume=args.volume) if args.play else SubprocessPlayer()
        dialogue_port = OfflineAudioDialogue.from_dir(Path(args.offline_audio_dir), player=player)
        mode = "offline-audio"
    else:
        dialogue_port = NullDialogue()
        mode = "offline-null"
    flow = TourFlow(book, FlowConfig(auto_advance=True))
    sink = RecordingSink()
    orchestrator = GuideOrchestrator(
        flow=flow,
        dialogue=dialogue_port,
        navigator=MockNavigator(),
        camera=camera,
        sink=sink,
        knowledge=knowledge,
        exhibit_titles=kb.titles,
        narrations=narrations,
        short_summaries=kb.short_summaries,
    )

    started = time.time()
    try:
        if client is not None:
            await client.connect(build_greeting_scene(knowledge=knowledge))
            print("[selftest] doubao session %.1fs" % (time.time() - started), flush=True)
        else:
            print("[selftest] mode=%s (no Doubao API call, no cost)" % mode, flush=True)
        await orchestrator.execute(flow.start())
        for index in range(args.stations):
            station_id = flow.current_station_id
            station = book.get(station_id)
            if station is None:
                break
            observe_started = time.time()
            await orchestrator.on_navigation_arrived(station_id)
            observe_ms = (time.time() - observe_started) * 1000.0
            print("[selftest]   recognized_exhibit=%s" % getattr(flow, "current_exhibit_id", None), flush=True)
            print("[selftest] station %s (%s) camera+scene %.0fms" % (station_id, station.name, observe_ms), flush=True)
            if client is not None:
                done.clear()
                try:
                    await asyncio.wait_for(done.wait(), timeout=args.timeout)
                except asyncio.TimeoutError:
                    print("[selftest] WARN audio timeout at %s" % station_id, file=sys.stderr)
                feed = ""
                if hasattr(audio, "pcm_bytes"):
                    feed = " speaker_chunks=%d speaker_bytes=%d" % (audio.play_calls, audio.pcm_bytes)
                print("[selftest]   audio chars=%d flow_state=%s%s" % (received["bytes"], flow.state.value, feed), flush=True)
                pending = getattr(audio, "pending_bytes", None)
                wait_started = time.time()
                while pending is not None and float(pending()) > 0 and time.time() - wait_started < 30.0:
                    await asyncio.sleep(0.1)
                print("[selftest]   playback drained in %.1fs" % (time.time() - wait_started), flush=True)
            else:
                await asyncio.sleep(0.2)
            await orchestrator.on_speech_finished()
            await orchestrator.on_tool_call("request_next_station", {"reason": "selftest"})
        print("[selftest] summary:", json.dumps({
            "stations": args.stations,
            "end_signals": sum(1 for a in sink.actions if a.kind is ActionKind.END_SIGNAL),
            "navigations": sum(1 for a in sink.actions if a.kind is ActionKind.NAVIGATE),
            "audio_events": events.count("audio.done"),
            "mode": mode,
            "final_state": flow.state.value,
        }, ensure_ascii=False))
        return 0
    finally:
        if client is not None:
            await client.close()
        else:
            try:
                await dialogue_port.cancel_speech()
            except Exception:
                pass
        camera.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="On-robot tourism guide self test (no motion)")
    parser.add_argument("--stations-config", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--stations", type=int, default=2, help="how many stations to simulate")
    parser.add_argument("--knowledge", default=str(TOURISM_ROOT / "configs" / "knowledge_dialogue.json"))
    parser.add_argument("--templates", default="templates")
    parser.add_argument("--camera", default="4")
    parser.add_argument("--flip", default="none")
    parser.add_argument("--method", default="orb")
    parser.add_argument("--truncate", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--doubao", action="store_true", help="use the paid Doubao API (default: offline, no cost)")
    parser.add_argument("--offline-audio-dir", default=None, help="pre-generated fallback wav directory")
    parser.add_argument("--play", action="store_true", help="play through the G1 speaker")
    parser.add_argument("--volume", type=int, default=60)
    parser.add_argument("--voice", default=None)
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
