from __future__ import annotations

from dataclasses import dataclass, field

from .command import VelocityCommand


@dataclass
class MockLocoBackend:
    """Records commands for offline tests. Never talks to hardware."""

    name: str = "mock_loco"
    connected: bool = False
    history: list[VelocityCommand] = field(default_factory=list)
    stop_count: int = 0
    next_code: int = 0
    fail_connect: bool = False

    def connect(self) -> int:
        if self.fail_connect:
            return -1
        self.connected = True
        return 0

    def set_velocity(self, command: VelocityCommand) -> int:
        if not self.connected:
            return -2
        self.history.append(command)
        return self.next_code

    def stop_move(self) -> int:
        self.stop_count += 1
        self.history.append(VelocityCommand(source="stop_move"))
        return 0

    def close(self) -> None:
        self.connected = False
