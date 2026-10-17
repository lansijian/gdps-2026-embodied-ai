from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.types import VerificationStatus


@dataclass
class HeadCameraReadOnly:
    """Read-only head camera probe. ROS/SDK bindings wired on robot after verification."""

    status: VerificationStatus = VerificationStatus.UNKNOWN
    ros_rgb_topic: str = ""
    ros_depth_topic: str = ""
    ros_camera_info_topic: str = ""
    _last_frame: Optional[CameraFrame] = None

    def connect(self) -> Tuple[bool, str]:
        if self.ros_rgb_topic:
            self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
            return True, "ros_topics_configured_not_subscribed"
        return False, "no_rgb_topic_configured"

    def read_file(self, path: str, info: CameraInfo) -> CameraFrame:
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("PIL required for offline image read")
        img = np.array(Image.open(path).convert("RGB"))
        self._last_frame = CameraFrame(rgb=img, depth_m=None, stamp=time.time(), info=info)
        self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        return self._last_frame

    def get_latest(self) -> Optional[CameraFrame]:
        return self._last_frame

    def field_check_steps(self) -> Tuple[str, ...]:
        return (
            "ros2 topic list -t | grep -i image",
            "ros2 topic info <rgb_topic> -v",
            "ros2 topic echo --once <camera_info_topic>",
            "If teleimager: confirm ZMQ/HTTP endpoint from Device.md",
            "Record whether aligned depth exists; do not assume D435i",
        )
