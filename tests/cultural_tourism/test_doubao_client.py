"""Unit tests for the Doubao realtime client with a fake transport/audio."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide import protocol  # noqa: E402
from gdps_tourism.guide.doubao_realtime import DoubaoConfig, DoubaoRealtimeClient, NullAudioIO  # noqa: E402
from gdps_tourism.guide.scene import DialogueKnowledge, build_station_scene  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"


class FakeTransport:
    def __init__(self) -> None:
        self.sent = []
        self.inbox = asyncio.Queue()
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def send(self, payload) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return await self.inbox.get()

    async def close(self) -> None:
        self.closed = True

    def push(self, event) -> None:
        self.inbox.put_nowait(json.dumps(event))


def _scene():
    book = StationBook.load(STATIONS)
    return build_station_scene(
        book.get("S02"),
        exhibit_title="《豫园仰山堂宴会图》",
        narration="这是晚清海派纪实画作。",
        knowledge=DialogueKnowledge(),
    )


async def _connect(client, transport, scene) -> None:
    task = asyncio.ensure_future(client.connect(scene))
    for _ in range(10):
        await asyncio.sleep(0.01)
        if transport.sent:
            break
    transport.push({"type": "session.created", "session": {"id": "sess_1"}})
    await task


class DoubaoClientTest(unittest.TestCase):
    def test_connect_sends_session_create(self) -> None:
        async def run():
            transport = FakeTransport()
            client = DoubaoRealtimeClient(
                DoubaoConfig(hotwords=["汇丰铜狮"]), NullAudioIO(), transport_factory=lambda: transport
            )
            await _connect(client, transport, _scene())
            create = transport.sent[0]
            self.assertEqual(create["type"], "session.create")
            self.assertEqual(create["session"]["model"], protocol.MODEL)
            self.assertIn("豫园仰山堂宴会图", create["session"]["instructions"])
            self.assertEqual(create["session"]["context"]["hotwords"], [{"word": "汇丰铜狮"}])
            await client.close()
            self.assertTrue(transport.closed)

        asyncio.run(run())

    def test_update_scene_and_narrate(self) -> None:
        async def run():
            transport = FakeTransport()
            audio = NullAudioIO()
            client = DoubaoRealtimeClient(DoubaoConfig(), audio, transport_factory=lambda: transport)
            await _connect(client, transport, _scene())
            scene = _scene()
            scene.instructions = "新站场景"
            await client.update_scene(scene)
            update = [item for item in transport.sent if item["type"] == "session.update"][-1]
            self.assertEqual(update["session"]["instructions"], "新站场景")
            self.assertIn("tools", update["session"])

            await client.narrate("这是预置讲解词。")
            speech = [item for item in transport.sent if item["type"] == "speech_text_buffer.commit"][-1]
            self.assertEqual(speech["text"], "这是预置讲解词。")

            await client.send_tool_result("call_1", "正在前往汇丰铜狮")
            result = [item for item in transport.sent if item["type"] == "conversation.item.create"][-1]
            self.assertEqual(result["items"][0]["call_id"], "call_1")
            self.assertEqual(result["items"][0]["role"], "tool")
            await client.close()

        asyncio.run(run())

    def test_audio_events_play_and_mute(self) -> None:
        async def run():
            transport = FakeTransport()
            audio = NullAudioIO()
            events = []

            async def on_event(event):
                events.append(event.kind)

            client = DoubaoRealtimeClient(
                DoubaoConfig(), audio, transport_factory=lambda: transport, on_event=on_event
            )
            await _connect(client, transport, None)
            payload = base64.b64encode(b"\x01\x02" * 100).decode()
            transport.push({"type": "response.output_audio.started"})
            transport.push({"type": "response.output_audio.delta", "delta": payload})
            transport.push({"type": "response.output_audio.done"})
            for _ in range(40):
                await asyncio.sleep(0.01)
                if "audio.done" in events and audio.played:
                    break
                if audio.muted and "audio.done" in events:
                    break
            self.assertTrue(any(item["type"] == "input_audio_mute.commit" for item in transport.sent))
            self.assertIn("audio.started", events)
            self.assertIn("audio.done", events)
            await client.close()

        asyncio.run(run())

    def test_cancel_and_function_call(self) -> None:
        async def run():
            transport = FakeTransport()
            audio = NullAudioIO()
            calls = []

            async def on_event(event):
                if event.kind == "fc.done" and event.tool is not None:
                    calls.append(event.tool)

            client = DoubaoRealtimeClient(
                DoubaoConfig(), audio, transport_factory=lambda: transport, on_event=on_event
            )
            await _connect(client, transport, None)
            await client.cancel_response()
            self.assertEqual(transport.sent[-1]["type"], "response.cancel")

            transport.push(
                {
                    "type": "response.function_call_arguments.done",
                    "items": [
                        {
                            "call_id": "call_7",
                            "name": "request_next_station",
                            "arguments": json.dumps({"target_name": "汇丰铜狮"}),
                        }
                    ],
                }
            )
            for _ in range(30):
                await asyncio.sleep(0.01)
                if calls:
                    break
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].name, "request_next_station")
            self.assertEqual(calls[0].arguments["target_name"], "汇丰铜狮")
            await client.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
