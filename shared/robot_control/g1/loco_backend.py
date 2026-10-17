"""Write-capable SDK backend; only G1MotionAdapter may issue velocity commands.

Read-only field packages deliberately exclude this module.
"""
from __future__ import annotations
import math
from .command import VelocityCommand
from .loco_readonly import (LocoReadOnlyClient, G1_LOCO_SERVICE_NAME,
    G1_LOCO_GET_FSM_ID_API_ID, G1_LOCO_GET_FSM_MODE_API_ID, G1_LOCO_GET_BALANCE_MODE_API_ID)
G1_LOCO_SET_VELOCITY_API_ID = 7105


class UnitreeLocoBackend(LocoReadOnlyClient):
    name = "unitree_loco"

    def set_velocity(self, command: VelocityCommand) -> int:
        if self._client is None:
            return -2
        values = (command.vx, command.vy, command.wz, command.duration_s)
        try:
            if not all(math.isfinite(float(x)) for x in values) or not 0 < command.duration_s <= 1.0:
                return -16
        except (ValueError, TypeError, OverflowError):
            return -16
        try:
            code = self._client.SetVelocity(
                float(command.vx), float(command.vy),
                float(command.wz), float(command.duration_s),
            )
            if code is None:
                return -17  # Never turn missing acknowledgment into success.
            return self.rpc_code(code)
        except Exception as exc:
            self.last_error = repr(exc)
            return -12

    def stop_move(self) -> int:
        if self._client is None:
            return -2
        try:
            # Software zero-velocity command, NOT a hardware emergency stop.
            code = self._client.SetVelocity(0.0, 0.0, 0.0, 1.0)
            return self.rpc_code(code) if code is not None else -17
        except Exception as exc:
            self.last_error = repr(exc)
            return -13

    def close(self) -> None:
        self._client = None
