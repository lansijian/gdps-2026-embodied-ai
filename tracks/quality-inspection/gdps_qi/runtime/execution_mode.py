from __future__ import annotations

import enum
import os


class ExecutionMode(str, enum.Enum):
    """SIMULATION: explicit mock TF/camera allowed. FIELD: requires verified calibration."""

    SIMULATION = "simulation"
    FIELD = "field"


def get_execution_mode() -> ExecutionMode:
    raw = os.environ.get("GDPS_QI_EXECUTION_MODE", "field").strip().lower()
    if raw in ("sim", "simulation", "offline", "test"):
        return ExecutionMode.SIMULATION
    return ExecutionMode.FIELD


def allow_simulation_assets() -> bool:
    return get_execution_mode() is ExecutionMode.SIMULATION
