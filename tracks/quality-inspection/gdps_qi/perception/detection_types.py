from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Detection:
    object_id: str
    label: str
    confidence: float
    bbox_xywh: Tuple[int, int, int, int]
    center_uv: Tuple[float, float]
