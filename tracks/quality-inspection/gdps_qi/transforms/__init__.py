"""Offline transforms; calibration file loading is an explicit optional dependency."""
from .transform_manager import TransformManager

__all__ = ["CalibrationManager", "TransformManager"]


def __getattr__(name):
    if name == "CalibrationManager":
        from .calibration_manager import CalibrationManager
        return CalibrationManager
    raise AttributeError(name)
