"""End-to-end guide integration: state machine + orchestrator + Doubao client + events.

No ROS, no camera, no cloud: FakeRos/FakeTransport replace the outside world,
but the flow, orchestrator, client protocol and END-signal contract are the
real implementations used on the robot.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide.doubao_realtime import (  # noqa: E402
    DoubaoConfig,
    DoubaoRealtimeClient,
    NullAudioIO,
)
from gdps_tourism.guide.dryrun import MockCamera  # noqa: E402
from gdps_tourism.guide.flow import Action, ActionKind, FlowConfig, GuideState, TourFlow  # noqa: E402
from gdps_tourism.guide.orchestrator import GuideOrchestrator  # noqa: E402
from gdps_tourism.guide.scene import DialogueKnowledge  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"


class FakeRos:
    def __init__(self) -> None:
        self.published = []
        self.goals = []
        self.cancelled = 0
        self.healthy = True

    def publish_event(self, payload) -> None:
        self.published.append(payload)

    def send_goal(self, payload) -> None:
        self.goals.append(payload)

    def cancel_goal(self) -> None:
        self.cancelled += 1


class FakeTransport:
    def __init__(self) -> None:
        self.sent = []
        self.inbox: "asyncio.Queue[str]" = asyncio.Queue()
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send(self, payload) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return await self.inbox.get()

    async def close(self) -> None:
        self.closed = True

    def push(self, event) -> None:
        self.inbox.put_nowait(json.dumps(event))


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


class Navigator:
    def __init__(self, ros: FakeRos) -> None:
        self.ros = ros

    async def go_to(self, payload) -> bool:
        self.ros.send_goal(payload)
        return True

    async def stop(self, reason: str) -> None:
        self.ros.cancel_goal()


class Sink:
    def __init__(self, ros: FakeRos) -> None:
        self.ros = ros
        self.actions = []

    def emit(self, action: Action) -> None:
        self.actions.append(action)
        if action.kind is ActionKind.END_SIGNAL:
            self.ros.publish_event(action.payload)
        elif action.kind is ActionKind.FINISH:
            self.ros.publish_event({"type": "FINISHED", "reason": action.payload.get("reason")})

    def kinds(self):
        return [action.kind for action in self.actions]


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


class GuideIntegrationTest(unittest.TestCase):
    def test_vision_voice_and_end_signal_round_trip(self) -> None:
        async def run():
            transport = FakeTransport()
            client = DoubaoRealtimeClient(DoubaoConfig(), NullAudioIO(), transport_factory=lambda: transport)
            ros = FakeRos()
            sink = Sink(ros)
            flow = TourFlow(StationBook.load(STATIONS), FlowConfig(auto_advance=True, listen_idle_end_s=0))
            orchestrator = GuideOrchestrator(
                flow=flow,
                dialogue=DialogueAdapter(client),
                navigator=Navigator(ros),
                camera=MockCamera(),
                sink=sink,
                knowledge=DialogueKnowledge(),
            )

            async def on_event(event):
                if event.kind == "fc.done" and event.tool is not None:
                    await orchestrator.on_tool_call(event.tool.name, event.tool.arguments)
                    await client.send_tool_result(event.tool.call_id, "已处理")
                elif event.kind == "audio.done":
                    await orchestrator.on_speech_finished()

            client._on_event = on_event
            connect_task = asyncio.ensure_future(client.connect(None))
            await _wait_until(lambda: bool(transport.sent))
            transport.push({"type": "session.created", "session": {"id": "s1"}})
            await connect_task

            # 1) tour starts -> first navigation goal
            await orchestrator.execute(flow.start())
            self.assertEqual(ros.goals[-1]["station_id"], "S01")

            # 2) arrival -> camera observation -> narration text sent to Doubao
            await orchestrator.on_navigation_arrived("S01")
            speech = [item for item in transport.sent if item["type"] == "speech_text_buffer.commit"]
            self.assertTrue(speech, "station narration should be sent to Doubao")
            transport.push({"type": "response.output_audio.done"})
            await _wait_until(lambda: flow.state is GuideState.LISTENING)

            # 3) voice request for a specific exhibit -> END + navigate + FC result
            transport.push(
                {
                    "type": "response.function_call_arguments.done",
                    "items": [
                        {
                            "call_id": "call_tourism",
                            "name": "request_next_station",
                            "arguments": json.dumps({"target_name": "汇丰铜狮"}),
                        }
                    ],
                }
            )
            await _wait_until(lambda: any(goal["station_id"] == "S07" for goal in ros.goals))
            end_signals = [item for item in ros.published if item.get("type") == "END_NARRATION"]
            self.assertTrue(end_signals)
            self.assertEqual(end_signals[-1]["next_station_id"], "S07")
            self.assertTrue(
                any(item["type"] == "response.cancel" for item in transport.sent),
                "ending narration must cancel the Doubao response",
            )
            tool_results = [item for item in transport.sent if item["type"] == "conversation.item.create"]
            self.assertTrue(tool_results)
            self.assertEqual(tool_results[-1]["items"][0]["role"], "tool")

            # 4) external vision trigger while walking -> redirect to the exhibit's station
            await orchestrator.on_visual_target("EXH_002", 0.9, "external")
            self.assertTrue(any(goal["station_id"] == "S03" for goal in ros.goals))

            await client.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
