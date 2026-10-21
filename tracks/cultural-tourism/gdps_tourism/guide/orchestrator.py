"""Guide orchestrator: executes state-machine actions with pluggable ports.

Ports (dialogue / navigation / camera / event sink) are injected so the whole
workflow can run dry without ROS or the Doubao cloud, and can be swapped for the
real adapters on the robot.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .budget import Budget
from .flow import Action, ActionKind, GuideState, TourFlow
from .scene import DialogueKnowledge, SceneText, build_route_scene, build_station_scene
from .stations import Station

try:  # typing only
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object


class DialoguePort(Protocol):
    async def update_scene(self, scene: SceneText) -> None: ...
    async def narrate(self, text: str) -> None: ...
    async def cancel_speech(self) -> None: ...
    async def listen(self) -> None: ...
    async def speak_brief(self, text: str) -> None: ...


class NavigatorPort(Protocol):
    async def go_to(self, payload: Dict[str, Any]) -> bool: ...
    async def stop(self, reason: str) -> None: ...


class CameraPort(Protocol):
    async def observe(self, station: Station) -> Tuple[Optional[str], float]: ...


class EventSink(Protocol):
    def emit(self, action: Action) -> None: ...


@dataclass
class OrchestratorConfig:
    observe_timeout_s: float = 6.0
    narration_seconds: float = 45.0
    brief_seconds: float = 6.0
    idle_check_s: float = 1.0


@dataclass
class GuideOrchestrator:
    flow: TourFlow
    dialogue: DialoguePort
    navigator: NavigatorPort
    camera: CameraPort
    sink: EventSink
    knowledge: DialogueKnowledge = field(default_factory=DialogueKnowledge)
    config: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    exhibit_titles: Dict[str, str] = field(default_factory=dict)
    narrations: Dict[str, str] = field(default_factory=dict)
    short_summaries: Dict[str, str] = field(default_factory=dict)
    budget: Optional[Budget] = None
    started_at: float = field(default_factory=time.time)

    # -- scene helpers -----------------------------------------------------
    def station_scene(self, station: Station, exhibit_id: Optional[str]) -> SceneText:
        narration = self.narrations.get(exhibit_id or "", "") if exhibit_id else ""
        return build_station_scene(
            station,
            exhibit_title=self.exhibit_titles.get(exhibit_id or "", ""),
            narration=narration,
            short_summary=self.short_summaries.get(exhibit_id or "", ""),
            knowledge=self.knowledge,
        )

    def route_scene(self, next_station: Optional[Station]) -> SceneText:
        return build_route_scene(next_station=next_station, knowledge=self.knowledge)

    # -- action execution --------------------------------------------------
    async def execute(self, actions: List[Action]) -> None:
        for action in actions:
            self.sink.emit(action)
            await self._execute_one(action)

    async def _execute_one(self, action: Action) -> None:
        payload = action.payload
        if action.kind is ActionKind.NAVIGATE:
            if self.budget is not None:
                self.budget.finish_station()
            next_station = self.flow.book.get(str(payload.get("station_id")))
            await self.dialogue.update_scene(self.route_scene(self.flow.book.next_after(self.flow.current_station_id)))
            await self.navigator.go_to(payload)
        elif action.kind is ActionKind.UPDATE_SCENE:
            mode = payload.get("mode")
            if mode == "station_arrived":
                station = self.flow.book.get(str(payload.get("station_id")))
                if self.budget is not None and station is not None:
                    self.budget.start_station(station.station_id)
                    remaining = self._stations_left(station)
                    self.flow.config.narration_max_s = self.budget.narration_cap_s(remaining)
                if station is not None and payload.get("needs_observation"):
                    result = await asyncio.wait_for(
                        self.camera.observe(station), timeout=self.config.observe_timeout_s
                    )
                else:
                    result = (None, 0.0)
                await self.execute(self.flow.on_observation(result[0], result[1]))
        elif action.kind is ActionKind.NARRATE:
            station = self.flow.book.get(str(payload.get("station_id")))
            exhibit_id = payload.get("exhibit_id")
            scene = self.station_scene(station, exhibit_id) if station else build_route_scene(knowledge=self.knowledge)
            await self.dialogue.update_scene(scene)
            text = scene.narration_text or (("%s，%s" % (station.name, station.route_brief)) if station else "")
            if text:
                await self.dialogue.narrate(text)
            elif station is not None:
                await self.dialogue.speak_brief(station.route_brief or station.name)
        elif action.kind is ActionKind.SPEAK_BRIEF:
            await self.dialogue.speak_brief(str(payload.get("text") or ""))
        elif action.kind is ActionKind.CANCEL_SPEECH:
            await self.dialogue.cancel_speech()
        elif action.kind is ActionKind.LISTEN:
            await self.dialogue.listen()
        elif action.kind is ActionKind.RECOMMEND:
            # P5 answers are phrased by the model from the tool result; the dry run
            # just records the action for the timeline.
            pass
        elif action.kind is ActionKind.FINISH:
            await self.navigator.stop("tour_finished")
            await self.dialogue.cancel_speech()

    # -- inbound events ----------------------------------------------------
    async def on_navigation_arrived(self, station_id: str) -> None:
        await self.execute(self.flow.on_nav_arrived(station_id))

    async def on_speech_finished(self) -> None:
        await self.execute(self.flow.on_speech_finished())

    async def on_tool_call(self, name: str, arguments: Dict[str, Any]) -> None:
        await self.execute(self.flow.on_tool_call(name, arguments))

    async def on_landmark(self, station_id: str) -> None:
        action = self.flow.on_landmark(station_id)
        if action is not None:
            await self.execute([action])

    async def on_visual_target(self, exhibit_id: str, confidence: float = 0.0, source: str = "vision") -> None:
        """Vision module (or /tourism/visual_target) recognised an exhibit."""

        await self.execute(self.flow.on_visual_target(exhibit_id, confidence, source))

    async def on_budget_check(self) -> None:
        await self.execute(self.flow.on_budget_check())

    def _stations_left(self, station) -> int:
        order = list(self.flow.book.tour_order)
        if station.station_id not in order:
            return 1
        return max(1, len(order) - order.index(station.station_id))

    async def on_idle_timeout(self) -> None:
        await self.execute(self.flow.on_idle_timeout())


class JsonlEventSink:
    """Event sink for dry-run / debugging (one JSON object per line)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.lines: List[Dict[str, Any]] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def emit(self, action: Action) -> None:
        record = {"ts": round(time.time(), 3), "kind": action.kind.value, "payload": action.payload}
        self.lines.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = [
    "DialoguePort",
    "NavigatorPort",
    "CameraPort",
    "EventSink",
    "OrchestratorConfig",
    "GuideOrchestrator",
    "JsonlEventSink",
]
