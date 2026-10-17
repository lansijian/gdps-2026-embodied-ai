from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.adapters.readonly.image_decode import decode_sensor_image
from gdps_qi.adapters.readonly.ros2_probe import probe_ros2_topic_once, summarize_ros_message
from gdps_qi.types import VerificationStatus


@dataclass
class HeadCameraReadOnly:
    ros_rgb_topic: str = ""
    ros_depth_topic: str = ""
    ros_camera_info_topic: str = ""
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _last_frame: Optional[CameraFrame] = None
    _camera_info: Optional[CameraInfo] = None
    _camera_info_stamp: Optional[float] = None
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "head_camera",
            "rgb_topic": self.ros_rgb_topic,
            "depth_topic": self.ros_depth_topic,
            "camera_info_topic": self.ros_camera_info_topic,
            "depth_available": False,
            "frame_cached": False,
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

                ci = probe_ros2_topic_once(self.ros_camera_info_topic, CameraInfo, timeout_s, store_payload=True)
                report["camera_info"] = {k: v for k, v in ci.items() if k != "msg"}
                if ci.get("ok") and ci.get("msg") is not None:
                    self._ingest_camera_info(ci["msg"])
            except ImportError:
                report["camera_info"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        if self.ros_rgb_topic:
            try:
                from sensor_msgs.msg import Image

                rgb_probe = probe_ros2_topic_once(self.ros_rgb_topic, Image, timeout_s, store_payload=True)
                report["rgb"] = {k: v for k, v in rgb_probe.items() if k != "msg"}
                if rgb_probe.get("ok") and rgb_probe.get("msg") is not None:
                    self._cache_image(rgb_probe["msg"], depth_msg=None)
                    report["frame_cached"] = self._last_frame is not None
            except ImportError:
                report["rgb"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        if self.ros_depth_topic:
            try:
                from sensor_msgs.msg import Image

                d = probe_ros2_topic_once(self.ros_depth_topic, Image, timeout_s, store_payload=True)
                report["depth"] = {k: v for k, v in d.items() if k != "msg"}
                if d.get("ok"):
                    report["depth_available"] = True
                    if d.get("msg") is not None and self._last_frame is not None:
                        _, depth, enc = decode_sensor_image(d["msg"])
                        report["depth_encoding"] = enc
                        if depth is not None:
                            self._last_frame.depth_m = depth
            except ImportError:
                report["depth"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        else:
            report["missing"].append("depth_topic_unconfigured")
        self._last_probe = report
        if self._last_frame is not None:
            self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        return report

    def _ingest_camera_info(self, msg: object) -> None:
        summary = summarize_ros_message(msg)
        k = summary.get("k")
        if not isinstance(k, list) or len(k) < 9:
            return
        w = int(summary.get("width", 0))
        h = int(summary.get("height", 0))
        self._camera_info = CameraInfo(
            width=w,
            height=h,
            fx=float(k[0]),
            fy=float(k[4]),
            cx=float(k[2]),
            cy=float(k[5]),
            frame_id=str(summary.get("frame_id", "camera")),
            distortion=tuple(float(x) for x in summary.get("d", []) if isinstance(summary.get("d"), list)),
            calibration_id="ros_camera_info",
            verified=False,
        )
        stamp = summary.get("stamp_sec")
        self._camera_info_stamp = float(stamp) if stamp is not None else time.time()

    def _cache_image(self, msg: object, depth_msg: object) -> None:
        rgb, depth, enc = decode_sensor_image(msg)
        if rgb is None and depth is None:
            return
        info = self._camera_info or CameraInfo(
            width=rgb.shape[1] if rgb is not None else 640,
            height=rgb.shape[0] if rgb is not None else 480,
            fx=600.0,
            fy=600.0,
            cx=320.0,
            cy=240.0,
            verified=False,
        )
        self._last_frame = CameraFrame(
            rgb=rgb,
            depth_m=depth,
            stamp=time.time(),
            info=info,
        )

    def get_latest(self) -> Optional[CameraFrame]:
        return self._last_frame

    def get_camera_info_stamp(self) -> Optional[float]:
        return self._camera_info_stamp
