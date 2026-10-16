from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pose2D:
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"
