"""Dry-run tour: no ROS, no camera, no cloud.  Prints/records the full timeline.

Used by scripts/tourism/guide_dryrun.py and by unit tests to prove the workflow
(navigate -> arrive -> observe -> narrate -> visitor intent -> END -> next).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .flow import Action, ActionKind, FlowConfig, GuideState, TourFlow
from .orchestrator import GuideOrchestrator, JsonlEventSink, OrchestratorConfig
from .scene import DialogueKnowledge, SceneText
from .stations import Station, StationBook


class MockDialogue:
    def __init__(self) -> None:
        self.scenes: List[str] = []
        self.narrations: List[str] = []
        self.briefs: List[str] = []
        self.cancelled = 0
        self.listening = 0

    async def update_scene(self, scene: SceneText) -> None:
        self.scenes.append(scene.instructions)

    async def narrate(self, text: str) -> None:
        self.narrations.append(text)

    async def cancel_speech(self) -> None:
        self.cancelled += 1

    async def listen(self) -> None:
        self.listening += 1

    async def speak_brief(self, text: str) -> None:
        self.briefs.append(text)


class MockNavigator:
    def __init__(self) -> None:
        self.goals: List[Dict[str, Any]] = []
        self.stops: List[str] = []

    async def go_to(self, payload: Dict[str, Any]) -> bool:
        self.goals.append(payload)
        return True

    async def stop(self, reason: str) -> None:
        self.stops.append(reason)


class MockCamera:
    def __init__(self, blind_stations: Optional[List[str]] = None) -> None:
        self.blind_stations = set(blind_stations or [])
        self.calls: List[str] = []

    async def observe(self, station: Station) -> Tuple[Optional[str], float]:
        self.calls.append(station.station_id)
        if station.station_id in self.blind_stations or not station.exhibit_ids:
            return None, 0.0
        return station.exhibit_ids[0], 0.92


@dataclass
class DryRunScript:
    """Per-station visitor intents (tool calls) used by the dry run."""

    default_intent: Dict[str, Any] = field(default_factory=lambda: {"name": "request_next_station", "arguments": {}})
    per_station: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    landmarks_during_nav: Dict[str, str] = field(default_factory=dict)


DEFAULT_SCRIPT = DryRunScript(
    per_station={
        "S02": [{"name": "request_recommendation", "arguments": {"category": "文创"}}],
        "S05": [
            {"name": "stop_narration", "arguments": {"reason": "游客想安静看一会"}},
            {"name": "request_next_station", "arguments": {}},
        ],
    },
    landmarks_during_nav={"S02": "L01"},
)


async def run_dry_tour(
    stations_path: Path,
    *,
    knowledge_path: Optional[Path] = None,
    exhibit_titles: Optional[Dict[str, str]] = None,
    narrations: Optional[Dict[str, str]] = None,
    short_summaries: Optional[Dict[str, str]] = None,
    script: Optional[DryRunScript] = None,
    out_json: Optional[Path] = None,
    max_steps: int = 60,
) -> Dict[str, Any]:
    book = StationBook.load(stations_path)
    flow = TourFlow(book, FlowConfig(auto_advance=True, listen_idle_end_s=0))
    sink = JsonlEventSink(out_json)
    dialogue = MockDialogue()
    navigator = MockNavigator()
    camera = MockCamera()
    orchestrator = GuideOrchestrator(
        flow=flow,
        dialogue=dialogue,
        navigator=navigator,
        camera=camera,
        sink=sink,
        knowledge=DialogueKnowledge.load(knowledge_path),
        config=OrchestratorConfig(observe_timeout_s=0.2, narration_seconds=0.0, brief_seconds=0.0),
        exhibit_titles=exhibit_titles or {},
        narrations=narrations or {},
        short_summaries=short_summaries or {},
    )
    script = script or DEFAULT_SCRIPT
    timeline: List[str] = []
    steps = 0

    async def step(actions_cost: int = 1) -> None:
        nonlocal steps
        steps += actions_cost
        if steps > max_steps:
            raise RuntimeError("dry-run exceeded max_steps (loop protection)")

    await orchestrator.execute(flow.start(greeting=False))
    await step()

    while flow.state is not GuideState.FINISHED and steps <= max_steps:
        station_id = flow.current_station_id
        if station_id is None:
            break
        station = book.get(station_id)
        timeline.append("navigate->%s (%s)" % (station_id, station.name if station else "?"))
        if station_id in script.landmarks_during_nav:
            await orchestrator.on_landmark(script.landmarks_during_nav[station_id])
            await step()
        await orchestrator.on_navigation_arrived(station_id)
        await step()
        await orchestrator.on_speech_finished()
        await step()
        intents = script.per_station.get(station_id, [script.default_intent])
        if station_id in script.per_station:
            intents = list(intents) + [script.default_intent]
        for intent in intents:
            await orchestrator.on_tool_call(str(intent["name"]), dict(intent.get("arguments") or {}))
            await step()
            if flow.state is GuideState.FINISHED:
                break
        if flow.state is not GuideState.FINISHED and flow.current_station_id == station_id:
            # nothing advanced us (e.g. only a P5 recommendation was requested)
            await orchestrator.on_tool_call(str(script.default_intent["name"]), dict(script.default_intent.get("arguments") or {}))
            await step()

    summary = {
        "stations_visited": [goal.get("station_id") for goal in navigator.goals],
        "end_signals": [line["payload"] for line in sink.lines if line["kind"] == "end_signal"],
        "narrations": len(dialogue.narrations),
        "briefs": dialogue.briefs,
        "cancelled": dialogue.cancelled,
        "final_state": flow.state.value,
        "finished_reason": flow.finished_reason,
        "steps": steps,
    }
    if out_json is not None:
        out_json.write_text(json.dumps({"summary": summary, "events": sink.lines}, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


__all__ = ["MockDialogue", "MockNavigator", "MockCamera", "DryRunScript", "DEFAULT_SCRIPT", "run_dry_tour"]
