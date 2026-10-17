"""Hardware adapters; motion implementations load only when explicitly requested."""
from .camera import CameraAdapter, CameraFrame, CameraInfo

__all__ = ["CameraAdapter", "CameraFrame", "CameraInfo", "Dex3HandAdapter", "HandCommand", "HandState", "RobotHardwareAdapter"]


def __getattr__(name):
    if name in ("Dex3HandAdapter", "HandCommand", "HandState"):
        from . import dex3_hand
        return getattr(dex3_hand, name)
    if name == "RobotHardwareAdapter":
        from .robot_hardware import RobotHardwareAdapter
        return RobotHardwareAdapter
    raise AttributeError(name)
