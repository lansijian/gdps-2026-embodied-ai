from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum

from shared.navigation.perception.obstacle_monitor import (
    AvoidDecision,
    ObstacleMonitor,
    ScanFrame,
)
from shared.navigation.safety.supervisor import SafetyHalt, SafetySupervisor
from shared.robot_control.g1.adapter import G1MotionAdapter, MotionMode
from shared.robot_control.g1.command import VelocityCommand

from .types import Pose2D


class NavCapability(str, Enum):
    LOCAL_AVOID = "local_avoid"
    FULL_NAV2 = "full_autonomous_nav"


class NavState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAULT = "fault"


@dataclass
class NavStatus:
    state: NavState
    capability: NavCapability
    mode: str
    halt: str
    reasons: list[str]
    last_decision: str
    last_return_code: int | None
    goal: Pose2D | None
    pose_known: bool
    path_unreachable: bool


@dataclass
class SharedNavigator:
    """Public API for all three tracks. Do not call LocoClient from track code."""

    adapter: G1MotionAdapter
    safety: SafetySupervisor
    obstacles: ObstacleMonitor
    capability: NavCapability = NavCapability.LOCAL_AVOID
    cruise_vx: float = 0.08
    detour_wz: float = 0.12
    goal_xy_tolerance_m: float = 0.25
    goal: Pose2D | None = None
    pose: Pose2D | None = None
    state: NavState = NavState.IDLE
    path_unreachable: bool = False
    _last_health_halt: str = SafetyHalt.NONE.value
    events: list[str] = field(default_factory=list)

    def start(self) -> NavStatus:
        if self.adapter.mode is MotionMode.LIVE and self.capability is NavCapability.FULL_NAV2:
            self._note("live full Nav2 is gated; using local_avoid command path until Nav2 is verified")
        self.safety.clear_manual_stop()
        self.path_unreachable = False
        self.state = NavState.RUNNING
        self._note("navigation started")
        return self.get_status()

    def set_goal(self, goal: Pose2D) -> NavStatus:
        self.goal = goal
        self.path_unreachable = False
        self._note(f"goal set {goal.x:.3f},{goal.y:.3f} frame={goal.frame_id}")
        if self.state is NavState.IDLE:
            self.state = NavState.RUNNING
        return self.get_status()

    def pause(self) -> NavStatus:
        self.state = NavState.PAUSED
        self.adapter.stop("pause")
        self._note("paused")
        return self.get_status()

    def stop(self, reason: str = "api_stop") -> NavStatus:
        self.safety.request_manual_stop()
        self.state = NavState.STOPPED
        self.adapter.stop(reason)
        self._note(f"stopped:{reason}")
        return self.get_status()

    def notify_path_unreachable(self) -> NavStatus:
        self.path_unreachable = True
        self.state = NavState.FAULT
        self.adapter.stop("path_unreachable")
        self._note("path unreachable")
        return self.get_status()

    def on_scan(self, scan: ScanFrame) -> None:
        self.obstacles.update(scan)
        self.safety.mark_sensor()

    def on_pose(self, pose: Pose2D) -> None:
        self.pose = pose
        self.safety.mark_odom()
        self.safety.mark_tf()

    def on_heartbeat(self) -> None:
        self.safety.mark_heartbeat()

    def step(self) -> VelocityCommand:
        health = self.safety.evaluate()
        self._last_health_halt = health.halt.value
        if self.state in {NavState.IDLE, NavState.STOPPED, NavState.PAUSED}:
            cmd = VelocityCommand(source=f"hold:{self.state.value}")
            self.adapter.send_velocity(cmd)
            return cmd
        if not health.ok:
            self.state = NavState.FAULT
            self.adapter.stop(health.halt.value)
            return VelocityCommand(source=f"halt:{health.halt.value}")
        if self.path_unreachable:
            self.adapter.stop("path_unreachable")
            return VelocityCommand(source="halt:path_unreachable")

        decision = self.obstacles.last_decision
        if decision is AvoidDecision.NO_SENSOR:
            self.state = NavState.FAULT
            self.adapter.stop("no_sensor")
            return VelocityCommand(source="halt:no_sensor")
        if decision is AvoidDecision.STOP:
            cmd = VelocityCommand(source="obstacle_stop")
            self.adapter.send_velocity(cmd)
            return cmd

        vx, wz = self._desired_from_goal()
        if decision is AvoidDecision.SLOW:
            vx *= 0.4
        elif decision is AvoidDecision.DETOUR_LEFT:
            vx = min(vx, 0.5 * self.cruise_vx)
            wz = abs(self.detour_wz)
        elif decision is AvoidDecision.DETOUR_RIGHT:
            vx = min(vx, 0.5 * self.cruise_vx)
            wz = -abs(self.detour_wz)

        cmd = VelocityCommand(vx=vx, vy=0.0, wz=wz, source=f"local:{decision.value}")
        self.adapter.send_velocity(cmd)
        self.adapter.watchdog_tick()
        return cmd

    def get_status(self) -> NavStatus:
        health = self.safety.evaluate()
        return NavStatus(
            state=self.state,
            capability=self.capability,
            mode=self.adapter.mode.value,
            halt=health.halt.value if not health.ok else self._last_health_halt,
            reasons=list(health.reasons),
            last_decision=self.obstacles.last_decision.value,
            last_return_code=self.adapter.last_return_code,
            goal=self.goal,
            pose_known=self.pose is not None,
            path_unreachable=self.path_unreachable,
        )

    def _desired_from_goal(self) -> tuple[float, float]:
        if self.goal is None or self.pose is None:
            return self.cruise_vx, 0.0
        dx = self.goal.x - self.pose.x
        dy = self.goal.y - self.pose.y
        dist = math.hypot(dx, dy)
        if dist <= self.goal_xy_tolerance_m:
            self.state = NavState.IDLE
            self._note("goal reached (local pose, not Nav2)")
            return 0.0, 0.0
        heading = math.atan2(dy, dx)
        yaw_err = math.atan2(math.sin(heading - self.pose.yaw), math.cos(heading - self.pose.yaw))
        wz = max(-self.detour_wz, min(self.detour_wz, yaw_err))
        vx = self.cruise_vx if abs(yaw_err) < 0.6 else 0.0
        return vx, wz

    def _note(self, message: str) -> None:
        self.events.append(f"{time.time():.3f} {message}")
