from __future__ import annotations

import atexit
import os
import time
from dataclasses import dataclass, field
from enum import Enum

from .command import VelocityCommand
from .motion_lock import MotionLock, MotionLockError


class MotionMode(str, Enum):
    DRY_RUN = "dry-run"
    LIVE = "live"


@dataclass
class AdapterLimits:
    max_vx: float = 0.10
    max_vy: float = 0.00
    max_wz: float = 0.15
    command_timeout_s: float = 0.25
    command_duration_s: float = 1.0
    comm_fail_stop: bool = True


@dataclass
class G1MotionAdapter:
    """Single entry for walking commands. Default is dry-run (no hardware output)."""

    backend: object
    owner: str = "gdps_g1_navigation"
    limits: AdapterLimits = field(default_factory=AdapterLimits)
    mode: MotionMode = MotionMode.DRY_RUN
    live_token: str = ""
    lock_path: str | None = None
    _lock: MotionLock | None = None
    last_return_code: int | None = None
    last_command: VelocityCommand | None = None
    last_command_monotonic: float = 0.0
    last_error: str = ""
    dry_run_history: list[VelocityCommand] = field(default_factory=list)
    _closed: bool = False

    def __post_init__(self) -> None:
        atexit.register(self.close)

    def connect(self) -> int:
        try:
            self._lock = MotionLock.acquire(self.owner, self.lock_path)
        except MotionLockError as exc:
            self.last_error = str(exc)
            self.last_return_code = -30
            return -30
        code = int(self.backend.connect())
        self.last_return_code = code
        if code != 0:
            self.last_error = f"backend connect failed: {code}"
            self._release_lock()
        return code

    def enable_live(self, token: str, confirm_phrase: str) -> None:
        """Enter live mode only after explicit human authorization.

        Requires:
        - env GDPS_G1_LIVE=1
        - token matching configured live_token
        - confirm_phrase == 'ENABLE LIVE MOTION'
        """
        if os.environ.get("GDPS_G1_LIVE") != "1":
            raise PermissionError("set GDPS_G1_LIVE=1 after on-site safety checklist")
        if not self.live_token or token != self.live_token:
            raise PermissionError("live token mismatch")
        if confirm_phrase != "ENABLE LIVE MOTION":
            raise PermissionError("confirm phrase mismatch")
        self.mode = MotionMode.LIVE

    def clamp(self, command: VelocityCommand) -> VelocityCommand:
        vx = max(-self.limits.max_vx, min(self.limits.max_vx, command.vx))
        vy = max(-self.limits.max_vy, min(self.limits.max_vy, command.vy))
        wz = max(-self.limits.max_wz, min(self.limits.max_wz, command.wz))
        duration = command.duration_s or self.limits.command_duration_s
        return VelocityCommand(
            vx=vx, vy=vy, wz=wz, duration_s=duration, source=command.source
        )

    def send_velocity(self, command: VelocityCommand) -> int:
        if self._closed:
            self.last_return_code = -31
            return -31
        clamped = self.clamp(command)
        self.last_command = clamped
        self.last_command_monotonic = time.monotonic()
        if self.mode is MotionMode.DRY_RUN:
            self.dry_run_history.append(clamped)
            self.last_return_code = 0
            return 0
        code = int(self.backend.set_velocity(clamped))
        self.last_return_code = code
        if code != 0:
            self.last_error = f"set_velocity returned {code}"
            if self.limits.comm_fail_stop:
                self.stop("backend_error")
        return code

    def watchdog_tick(self, now: float | None = None) -> int | None:
        now = time.monotonic() if now is None else now
        if self.last_command_monotonic <= 0.0:
            return None
        if (now - self.last_command_monotonic) <= self.limits.command_timeout_s:
            return None
        return self.stop("command_timeout")

    def stop(self, reason: str) -> int:
        zero = VelocityCommand(source=f"stop:{reason}")
        self.last_command = zero
        self.last_command_monotonic = time.monotonic()
        if self.mode is MotionMode.DRY_RUN:
            self.dry_run_history.append(zero)
            self.last_return_code = 0
            self.last_error = reason
            return 0
        code = int(self.backend.stop_move())
        self.last_return_code = code
        self.last_error = reason
        return code

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.stop("adapter_close")
            if hasattr(self.backend, "close"):
                self.backend.close()
        finally:
            self._release_lock()
            self._closed = True

    def _release_lock(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None
