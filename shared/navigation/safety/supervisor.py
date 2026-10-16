from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class SafetyHalt(str, Enum):
    NONE = "none"
    SENSOR_STALE = "sensor_stale"
    ODOM_STALE = "odom_stale"
    TF_STALE = "tf_stale"
    MANUAL_STOP = "manual_stop"
    OBSTACLE_STOP = "obstacle_stop"
    PATH_UNREACHABLE = "path_unreachable"
    COMM_LOSS = "comm_loss"
    HEARTBEAT_STALE = "heartbeat_stale"


@dataclass
class HealthReport:
    ok: bool
    halt: SafetyHalt = SafetyHalt.NONE
    reasons: list[str] = field(default_factory=list)


@dataclass
class SafetySupervisor:
    sensor_timeout_s: float = 0.5
    odom_timeout_s: float = 0.5
    tf_timeout_s: float = 0.5
    heartbeat_timeout_s: float = 1.0
    last_sensor_monotonic: float = 0.0
    last_odom_monotonic: float = 0.0
    last_tf_monotonic: float = 0.0
    last_heartbeat_monotonic: float = 0.0
    manual_stop: bool = False
    require_sensor: bool = True
    require_odom: bool = False
    require_tf: bool = False
    require_heartbeat: bool = False

    def mark_sensor(self) -> None:
        self.last_sensor_monotonic = time.monotonic()

    def mark_odom(self) -> None:
        self.last_odom_monotonic = time.monotonic()

    def mark_tf(self) -> None:
        self.last_tf_monotonic = time.monotonic()

    def mark_heartbeat(self) -> None:
        self.last_heartbeat_monotonic = time.monotonic()

    def request_manual_stop(self) -> None:
        self.manual_stop = True

    def clear_manual_stop(self) -> None:
        self.manual_stop = False

    def evaluate(self, now: float | None = None) -> HealthReport:
        now = time.monotonic() if now is None else now
        reasons: list[str] = []
        halt = SafetyHalt.NONE
        if self.manual_stop:
            halt = SafetyHalt.MANUAL_STOP
            reasons.append("operator stop")
        if self.require_sensor and not self._fresh(self.last_sensor_monotonic, now, self.sensor_timeout_s):
            halt = SafetyHalt.SENSOR_STALE
            reasons.append("obstacle sensor stale or missing")
        if self.require_odom and not self._fresh(self.last_odom_monotonic, now, self.odom_timeout_s):
            halt = SafetyHalt.ODOM_STALE
            reasons.append("odometry stale or missing")
        if self.require_tf and not self._fresh(self.last_tf_monotonic, now, self.tf_timeout_s):
            halt = SafetyHalt.TF_STALE
            reasons.append("TF stale or missing")
        heartbeat_required = self.require_heartbeat or self.last_heartbeat_monotonic > 0.0
        if heartbeat_required and not self._fresh(
            self.last_heartbeat_monotonic, now, self.heartbeat_timeout_s
        ):
            halt = SafetyHalt.HEARTBEAT_STALE
            reasons.append("operator/host heartbeat stale (treat as possible SSH loss)")
        ok = halt is SafetyHalt.NONE
        return HealthReport(ok=ok, halt=halt, reasons=reasons)

    @staticmethod
    def _fresh(stamp: float, now: float, timeout: float) -> bool:
        if stamp <= 0.0:
            return False
        return (now - stamp) <= timeout
