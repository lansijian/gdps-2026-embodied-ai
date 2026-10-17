from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class LogicalFrame(str, enum.Enum):
    ODOM = "odom"
    ROBOT_CENTER = "robot_center"
    PELVIS = "pelvis"
    TORSO = "torso"
    HEAD_CAMERA_LINK = "head_camera_link"
    CAMERA_COLOR_OPTICAL = "camera_color_optical_frame"
    CAMERA_DEPTH_OPTICAL = "camera_depth_optical_frame"
    LIVOX = "livox_frame"
    TABLE = "table_frame"
    TARGET = "target_frame"


# Aliases seen on robot / URDF (map at runtime; do not assume equality).
FRAME_ALIASES: Dict[LogicalFrame, tuple[str, ...]] = {
    LogicalFrame.CAMERA_COLOR_OPTICAL: (
        "camera_color_optical_frame",
        "head_camera_optical",
        "camera_optical_frame",
    ),
    LogicalFrame.CAMERA_DEPTH_OPTICAL: (
        "camera_depth_optical_frame",
        "head_camera_depth_optical",
    ),
    LogicalFrame.LIVOX: ("livox_frame", "utlidar_lidar", "livox"),
}


@dataclass
class TransformChainStatus:
    edge: str
    parent: str
    child: str
    available: bool
    stamp: Optional[float]
    calibration_id: str
    reason: str = ""


@dataclass
class FrameGraphReport:
    base_frame: str
    statuses: List[TransformChainStatus] = field(default_factory=list)
    T_base_camera: Optional[List[List[float]]] = None
    T_base_lidar: Optional[List[List[float]]] = None
    T_base_target: Optional[List[List[float]]] = None
    T_odom_base: Optional[List[List[float]]] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "base_frame": self.base_frame,
            "statuses": [s.__dict__ for s in self.statuses],
            "T_base_camera": self.T_base_camera,
            "T_base_lidar": self.T_base_lidar,
            "T_base_target": self.T_base_target,
            "T_odom_base": self.T_odom_base,
            "errors": self.errors,
        }
