"""Tour guide state machine (navigation + narration + visitor intents).

Pure Python: no ROS, no audio, no camera.  The orchestrator feeds events in and
executes the returned actions.  The END signal consumed by the navigation team
is emitted from here, so the contract stays in one place.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .stations import Station, StationBook, TargetResolution


class GuideState(enum.Enum):
    IDLE = "idle"
    GREETING = "greeting"
    NAVIGATING = "navigating"
    ARRIVED = "arrived"
    NARRATING = "narrating"
    LISTENING = "listening"
    FINISHED = "finished"


class ActionKind(enum.Enum):
    UPDATE_SCENE = "update_scene"      # build/send station scene to Doubao
    NARRATE = "narrate"                # speak the station narration
    SPEAK_BRIEF = "speak_brief"        # P3 one-liner while walking
    NAVIGATE = "navigate"              # ask navigation to go to a station
    CANCEL_SPEECH = "cancel_speech"    # response.cancel + local PlayStop
    LISTEN = "listen"                  # open microphone / wait for visitor
    END_SIGNAL = "end_signal"          # END event for the navigation team
    RECOMMEND = "recommend"            # P5: answer with the recommendation list
    LOG = "log"
    FINISH = "finish"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowConfig:
    observe_timeout_s: float = 6.0
    narration_min_s: float = 12.0
    narration_max_s: float = 120.0
    station_max_s: float = 180.0
    listen_idle_end_s: float = 30.0  # 0 disables auto-advance while the visitor is silent
    brief_gap_s: float = 20.0
    auto_advance: bool = True


@dataclass
class TourFlow:
    book: StationBook
    config: FlowConfig = field(default_factory=FlowConfig)
    state: GuideState = GuideState.IDLE
    current_station_id: Optional[str] = None
    current_exhibit_id: Optional[str] = None
    pending_exhibit_id: Optional[str] = None
    narration_started_at: Optional[float] = None
    spoken_briefs: Set[str] = field(default_factory=set)
    last_brief_at: float = 0.0
    last_action_at: float = 0.0
    finished_reason: str = ""

    # -- helpers -----------------------------------------------------------
    @property
    def current_station(self) -> Optional[Station]:
        if self.current_station_id is None:
            return None
        return self.book.get(self.current_station_id)

    def _now(self) -> float:
        return time.monotonic()

    def _touch(self) -> None:
        self.last_action_at = self._now()

    def _pose_payload(self, station: Station) -> Dict[str, Any]:
        pose = station.pose
        return {
            "station_id": station.station_id,
            "station_name": station.name,
            "frame_id": pose.frame_id if pose else self.book.frame_id,
            "x": pose.x if pose else 0.0,
            "y": pose.y if pose else 0.0,
            "yaw": pose.yaw if pose else 0.0,
            "reachable": station.reachable,
            "eta_s": station.eta_s,
        }

    def _navigate(self, station: Optional[Station], reason: str) -> List[Action]:
        if station is None:
            return self._finish("tour_complete")
        self.current_station_id = station.station_id
        self.current_exhibit_id = None
        self.state = GuideState.NAVIGATING
        self._touch()
        return [
            Action(ActionKind.LOG, {"event": "navigate", "station_id": station.station_id, "reason": reason}),
            Action(ActionKind.NAVIGATE, self._pose_payload(station)),
        ]

    def _end_signal(self, station: Optional[Station], next_station: Optional[Station], reason: str) -> Action:
        self._touch()
        return Action(
            ActionKind.END_SIGNAL,
            {
                "type": "END_NARRATION",
                "station_id": station.station_id if station else None,
                "station_name": station.name if station else None,
                "next_station_id": next_station.station_id if next_station else None,
                "next_station_name": next_station.name if next_station else None,
                "reason": reason,
                "ts": time.time(),
                "source": "tourism_guide",
            },
        )

    def _finish(self, reason: str) -> List[Action]:
        self.state = GuideState.FINISHED
        self.finished_reason = reason
        self._touch()
        return [Action(ActionKind.FINISH, {"reason": reason})]

    # -- lifecycle ---------------------------------------------------------
    def start(self, *, greeting: bool = False) -> List[Action]:
        """Start the tour; greeting=True opens with the P1 intake scene."""

        if self.state is not GuideState.IDLE:
            return [Action(ActionKind.LOG, {"event": "start_ignored", "state": self.state.value})]
        if greeting:
            self.state = GuideState.GREETING
            self._touch()
            return [
                Action(ActionKind.UPDATE_SCENE, {"mode": "greeting"}),
                Action(ActionKind.LISTEN, {"reason": "greeting"}),
            ]
        return self._navigate(self.book.next_after(None), "tour_start")

    def on_nav_arrived(self, station_id: Optional[str] = None) -> List[Action]:
        station = self.book.get(station_id) if station_id else self.current_station
        if station is None:
            return [Action(ActionKind.LOG, {"event": "arrived_unknown_station", "station_id": station_id})]
        self.current_station_id = station.station_id
        self.state = GuideState.ARRIVED
        self._touch()
        return [
            Action(ActionKind.LOG, {"event": "arrived", "station_id": station.station_id}),
            Action(
                ActionKind.UPDATE_SCENE,
                {"mode": "station_arrived", "station_id": station.station_id, "needs_observation": station.needs_observation},
            ),
        ]

    def on_observation(self, exhibit_id: Optional[str], confidence: float = 0.0) -> List[Action]:
        """Camera result after arrival (None = nothing recognised / timed out)."""

        station = self.current_station
        if station is None:
            return [Action(ActionKind.LOG, {"event": "observation_without_station"})]
        chosen = exhibit_id or self.pending_exhibit_id
        self.pending_exhibit_id = None
        if chosen is None and station.exhibit_ids:
            chosen = station.exhibit_ids[0]
            note = "fallback_station_exhibit"
        else:
            note = "visual_match" if chosen else "no_exhibit"
        self.current_exhibit_id = chosen
        self.state = GuideState.NARRATING
        self.narration_started_at = self._now()
        self._touch()
        return [
            Action(
                ActionKind.LOG,
                {
                    "event": "observation",
                    "station_id": station.station_id,
                    "exhibit_id": chosen,
                    "confidence": round(float(confidence), 3),
                    "note": note,
                },
            ),
            Action(
                ActionKind.NARRATE,
                {
                    "station_id": station.station_id,
                    "exhibit_id": chosen,
                    "profile": station.narration_profile,
                },
            ),
        ]

    def on_visual_target(self, exhibit_id: str, confidence: float = 0.0, source: str = "vision") -> List[Action]:
        """A recognised exhibit (vision module or visitor request) triggers navigation.

        Behaviour:
          - already at the station and listening  -> narrate right away
          - already at the station and narrating  -> ignore (no duplicate)
          - elsewhere                             -> end current narration, navigate
        The matched exhibit is remembered so the arrival narration uses it.
        """

        station = self.book.station_for_exhibit(exhibit_id)
        if station is None:
            return [
                Action(
                    ActionKind.LOG,
                    {"event": "visual_target_unmapped", "exhibit_id": exhibit_id, "confidence": confidence},
                ),
            ]
        self.pending_exhibit_id = exhibit_id
        log = Action(
            ActionKind.LOG,
            {
                "event": "visual_target",
                "exhibit_id": exhibit_id,
                "station_id": station.station_id,
                "confidence": round(float(confidence), 3),
                "source": source,
                "state": self.state.value,
            },
        )
        already_here = self.current_station_id == station.station_id and self.state in (
            GuideState.ARRIVED,
            GuideState.NARRATING,
            GuideState.LISTENING,
        )
        if already_here:
            if self.state is GuideState.LISTENING:
                return [log] + self.on_observation(exhibit_id, confidence)
            return [log]

        actions = [log]
        if self.state in (
            GuideState.GREETING,
            GuideState.ARRIVED,
            GuideState.NARRATING,
            GuideState.LISTENING,
        ):
            actions.append(self._end_signal(self.current_station, station, "visual_target"))
            actions.append(Action(ActionKind.CANCEL_SPEECH, {}))
        actions += self._navigate(station, "visual_target")
        return actions

    def on_speech_finished(self) -> List[Action]:
        if self.state is GuideState.NARRATING:
            self.state = GuideState.LISTENING
            self.narration_started_at = None
            self._touch()
            return [Action(ActionKind.LISTEN, {"reason": "narration_done"})]
        return []

    def on_budget_check(self, now: Optional[float] = None) -> List[Action]:
        """Cut the narration / advance the station when the time budget is spent."""

        if self.state is not GuideState.NARRATING or self.narration_started_at is None:
            return []
        moment = self._now() if now is None else now
        elapsed = moment - self.narration_started_at
        if elapsed < self.config.narration_max_s:
            return []
        station = self.current_station
        next_station = self.book.next_after(self.current_station_id)
        self.narration_started_at = None
        actions = [
            Action(
                ActionKind.LOG,
                {
                    "event": "narration_budget_timeout",
                    "station_id": station.station_id if station else None,
                    "elapsed_s": round(elapsed, 1),
                    "limit_s": self.config.narration_max_s,
                },
            ),
            Action(ActionKind.CANCEL_SPEECH, {}),
            self._end_signal(station, next_station, "narration_budget_timeout"),
        ]
        if next_station is None:
            actions += self._finish("budget_finished")
        else:
            actions += self._navigate(next_station, "narration_budget_timeout")
        return actions

    # -- visitor intents ---------------------------------------------------
    def on_tool_call(self, name: str, arguments: Dict[str, Any]) -> List[Action]:
        args = arguments or {}
        if name == "request_next_station":
            return self._handle_next_station(args)
        if name == "stop_narration":
            return self._handle_stop_narration(args)
        if name == "request_recommendation":
            self._touch()
            return [Action(ActionKind.RECOMMEND, {"category": str(args.get("category") or "全部")})]
        return [Action(ActionKind.LOG, {"event": "unknown_tool", "name": name, "args": args})]

    def _handle_next_station(self, args: Dict[str, Any]) -> List[Action]:
        station = self.current_station
        target_text = str(args.get("target_name") or "").strip()
        resolution: TargetResolution = self.book.resolve_target(target_text) if target_text else TargetResolution(
            query="", station=self.book.next_after(self.current_station_id)
        )
        if target_text and not resolution.ok:
            self._touch()
            return [
                Action(
                    ActionKind.LOG,
                    {"event": "target_unresolved", "query": target_text},
                ),
                Action(ActionKind.RECOMMEND, {"category": "unknown_target", "query": target_text}),
            ]
        next_station = resolution.station
        reason = str(args.get("reason") or "visitor_next_request")
        actions = [self._end_signal(station, next_station, reason), Action(ActionKind.CANCEL_SPEECH, {})]
        if next_station is None:
            actions += self._finish("visitor_finished")
            return actions
        actions += self._navigate(next_station, reason)
        return actions

    def _handle_stop_narration(self, args: Dict[str, Any]) -> List[Action]:
        station = self.current_station
        reason = str(args.get("reason") or "visitor_stop")
        self.state = GuideState.LISTENING
        self._touch()
        return [
            Action(ActionKind.LOG, {"event": "stop_narration", "reason": reason}),
            Action(ActionKind.CANCEL_SPEECH, {}),
            self._end_signal(station, None, "narration_stopped"),
            Action(ActionKind.LISTEN, {"reason": "visitor_stop"}),
        ]

    # -- P3 route briefs ---------------------------------------------------
    def on_route_exhibit(self, exhibit_id: str, now: Optional[float] = None) -> Optional[Action]:
        """Camera matched an exhibit while walking; map it to a route brief."""

        station = self.book.station_for_route_exhibit(exhibit_id)
        if station is None:
            return None
        return self.on_landmark(station.station_id, now=now)

    def on_landmark(self, station_id: str, now: Optional[float] = None) -> Optional[Action]:
        """Feed a configured landmark while walking; returns at most one brief."""

        if self.state is not GuideState.NAVIGATING:
            return None
        station = self.book.get(station_id)
        if station is None or not station.route_brief:
            return None
        if station.station_id in self.spoken_briefs:
            return None
        moment = self._now() if now is None else now
        if moment - self.last_brief_at < self.config.brief_gap_s:
            return None
        self.spoken_briefs.add(station.station_id)
        self.last_brief_at = moment
        self._touch()
        return Action(
            ActionKind.SPEAK_BRIEF,
            {
                "station_id": station.station_id,
                "name": station.name,
                "text": station.route_brief,
            },
        )

    # -- misc --------------------------------------------------------------
    def on_idle_timeout(self, now: Optional[float] = None) -> List[Action]:
        """Visitor silence while listening: advance when configured."""

        if self.state is not GuideState.LISTENING or not self.config.auto_advance:
            return []
        moment = self._now() if now is None else now
        if moment - self.last_action_at < self.config.listen_idle_end_s:
            return []
        station = self.current_station
        next_station = self.book.next_after(self.current_station_id)
        actions = [self._end_signal(station, next_station, "listen_timeout"), Action(ActionKind.CANCEL_SPEECH, {})]
        actions += self._navigate(next_station, "listen_timeout")
        return actions

    def on_stop(self, reason: str = "operator_stop") -> List[Action]:
        return self._finish(reason)


__all__ = ["GuideState", "ActionKind", "Action", "FlowConfig", "TourFlow"]
