#!/usr/bin/env python3
"""Read-only Doubao realtime connectivity / TTS test for the guide.

Connects to the Doubao realtime API, creates a session with the guide persona,
asks it to speak one sentence and prints the received events / audio bytes.
Does not move the robot.

Usage:
    export DOUBAO_API_KEY="..."
    python3 scripts/tourism/check_doubao.py                 # receive audio, do not play
    python3 scripts/tourism/check_doubao.py --play          # also play through the G1 speaker
    python3 scripts/tourism/check_doubao.py --text "你好，我是小历。"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from gdps_tourism.guide.doubao_realtime import (  # noqa: E402
    DoubaoConfig,
    DoubaoRealtimeClient,
    G1AudioIO,
    NullAudioIO,
)
from gdps_tourism.guide.scene import DialogueKnowledge, build_greeting_scene  # noqa: E402


async def run(args) -> int:
    if not os.environ.get("DOUBAO_API_KEY", "").strip():
        print("请先设置 DOUBAO_API_KEY（export DOUBAO_API_KEY=...）", file=sys.stderr)
        return 2
    audio = G1AudioIO(volume=args.volume) if args.play else NullAudioIO()
    events = []
    received_audio = [0]

    async def on_event(event):
        events.append(event.kind)
        if event.kind == "audio.delta":
            delta = event.payload.get("delta") or ""
            received_audio[0] += len(delta)

    client = DoubaoRealtimeClient(
        DoubaoConfig(voice=args.voice),
        audio,
        on_event=on_event,
        on_error=lambda message: print("[doubao][error]", message, file=sys.stderr),
    )
    scene = build_greeting_scene(knowledge=DialogueKnowledge())
    started = time.time()
    try:
        await client.connect(scene)
        print("[doubao] session created in %.1fs" % (time.time() - started))
        await client.narrate(args.text)
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            if "audio.done" in events:
                break
        print("[doubao] events:", events)
        counter = getattr(audio, "played", None)
        played_bytes = sum(len(item) for item in counter) if counter else 0
        print("[doubao] audio_deltas=%d base64_chars=%d played_bytes=%d" % (
            events.count("audio.delta"), received_audio[0], played_bytes))
        ok = "audio.started" in events or "audio.delta" in events
        print("[doubao] result:", "OK" if ok else "FAILED (no audio received)")
        return 0 if ok else 1
    finally:
        await client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Doubao realtime connectivity test")
    parser.add_argument("--text", default="你好，我是上海市历史博物馆的导览员小历，很高兴为您服务。")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--volume", type=int, default=80)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--play", action="store_true", help="play through the G1 speaker")
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
