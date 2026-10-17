from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class WaistPreviewResult:
    ok: bool
    joint_delta: Dict[str, float]
    message: str
    dry_run_only: bool = True


def preview_waist_yaw_adjustment(
    current_joints: Dict[str, float],
    bearing_rad: float,
    max_delta_rad: float = 0.08,
    joint_name: str = "waist_yaw_joint",
) -> WaistPreviewResult:
    """Dry-run waist yaw suggestion; does not send LowCmd."""
    if joint_name not in current_joints:
        return WaistPreviewResult(False, {}, "waist_joint_missing", True)
    delta = max(-max_delta_rad, min(max_delta_rad, -0.5 * bearing_rad))
    out = {joint_name: current_joints[joint_name] + delta}
    return WaistPreviewResult(True, out, "waist_yaw_preview", True)
