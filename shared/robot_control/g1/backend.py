from __future__ import annotations

from typing import Protocol

from .command import VelocityCommand


class MotionBackend(Protocol):
    """Vendor-specific motion sink. Navigation never calls this protocol directly."""

    name: str

    def connect(self) -> int:
        """Return 0 on success. Never raises into a live walk on failure."""

    def set_velocity(self, command: VelocityCommand) -> int:
        """Send high-level walking velocity. Return vendor code (0 = OK)."""

    def stop_move(self) -> int:
        """Zero velocity via the same high-level walking API. Do not disable motors."""

    def close(self) -> None:
        """Release SDK resources. Must not switch to zero-torque."""
