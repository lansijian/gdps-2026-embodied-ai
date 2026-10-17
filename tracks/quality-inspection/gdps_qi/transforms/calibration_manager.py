from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

import numpy as np

from gdps_qi.math_se3 import transform_from_pose
from gdps_qi.transforms.transform_manager import TransformManager


@dataclass
class CalibrationBundle:
    calibration_id: str
    robot_variant: str
    calibrated: bool
    created_at: float
    transforms: Dict[str, Dict[str, Any]]
    notes: str = ""


@dataclass
class CalibrationManager:
    bundle: Optional[CalibrationBundle] = None
    max_age_s: float = 86400.0

    def load_yaml(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.bundle = CalibrationBundle(
            calibration_id=str(data.get("calibration_id", "unknown")),
            robot_variant=str(data.get("robot_variant", "G1_UNKNOWN")),
            calibrated=bool(data.get("calibrated", False)),
            created_at=float(data.get("created_at", time.time())),
            transforms=dict(data.get("transforms", {})),
            notes=str(data.get("notes", "")),
        )

    def is_valid(self, now: Optional[float] = None) -> Tuple[bool, str]:
        if self.bundle is None:
            return False, "no_calibration_loaded"
        if not self.bundle.calibrated:
            return False, "calibrated_flag_false"
        now = now or time.time()
        if (now - self.bundle.created_at) > self.max_age_s:
            return False, "calibration_expired"
        return True, "ok"

    def apply_to_transform_manager(self, tf: TransformManager) -> None:
        if self.bundle is None:
            raise RuntimeError("no bundle")
        for key, entry in self.bundle.transforms.items():
            parent, child = key.split("->", 1)
            pos = entry["position"]
            quat = entry["orientation_xyzw"]
            t = transform_from_pose(pos, quat)
            tf.set_transform(
                parent,
                child,
                t,
                stamp=self.bundle.created_at,
                calibration_id=self.bundle.calibration_id,
                static=bool(entry.get("static", True)),
            )
