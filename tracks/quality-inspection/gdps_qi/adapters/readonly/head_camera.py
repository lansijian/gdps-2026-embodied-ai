from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.adapters.readonly.ros2_probe import probe_ros2_topic_once
from gdps_qi.types import VerificationStatus


@dataclass
class HeadCameraReadOnly:
    ros_rgb_topic: str = ""
    ros_depth_topic: str = ""
    ros_camera_info_topic: str = ""
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _last_frame: Optional[CameraFrame] = None
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "head_camera",
            "rgb_topic": self.ros_rgb_topic,
            "depth_topic": self.ros_depth_topic,
            "camera_info_topic": self.ros_camera_info_topic,
            "depth_available": False,
            "missing": [],
        }
        if not self.ros_rgb_topic:
            report["missing"].append("rgb_topic_unconfigured")
        if not live:
            report["mode"] = "dry_run_schema"
            self._last_probe = report
            return report
        report["mode"] = "live_readonly"
        if self.ros_camera_info_topic:
            try:
                from sensor_msgs.msg import CameraInfo

                report["camera_info"] = probe_ros2_topic_once(
                    self.ros_camera_info_topic, CameraInfo, timeout_s
                )
            except ImportError:
                report["camera_info"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        if self.ros_rgb_topic:
            try:
                from sensor_msgs.msg import Image

                report["rgb"] = probe_ros2_topic_once(self.ros_rgb_topic, Image, timeout_s)
            except ImportError:
                report["rgb"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        if self.ros_depth_topic:
            try:
                from sensor_msgs.msg import Image

                d = probe_ros2_topic_once(self.ros_depth_topic, Image, timeout_s)
                report["depth"] = d
                report["depth_available"] = bool(d.get("ok"))
            except ImportError:
                report["depth"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        else:
            report["missing"].append("depth_topic_unconfigured")
        self._last_probe = report
        if report.get("rgb", {}).get("ok"):
            self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        return report

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
