from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from gdps_qi.math_se3 import compose_transform, invert_transform


@dataclass
class BimanualRelativePose:
    """Maintains T_left^-1 * T_right for dual-hand tasks (e.g. cap twist)."""

    t_left_tcp: np.ndarray
    t_right_tcp: np.ndarray

    def relative_right_in_left(self) -> np.ndarray:
        return compose_transform(invert_transform(self.t_left_tcp), self.t_right_tcp)

    def axis_alignment_error_rad(self, axis_left: np.ndarray, axis_right: np.ndarray) -> float:
        a = axis_left / np.linalg.norm(axis_left)
        b = axis_right / np.linalg.norm(axis_right)
        dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
        return float(np.arccos(abs(dot)))

    def update(
        self, t_left_tcp: np.ndarray, t_right_tcp: np.ndarray
    ) -> Tuple[np.ndarray, float]:
        self.t_left_tcp = t_left_tcp
        self.t_right_tcp = t_right_tcp
        rel = self.relative_right_in_left()
        return rel, float(np.linalg.norm(rel[:3, 3]))
