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
class CameraReadOnlyConfig:
    depth_scale_m: Optional[float] = None
    allow_16uc1_depth: bool = False
    treat_mono16_as_depth: bool = False
    max_rgb_depth_stamp_delta_s: float = 0.05
    require_matching_resolution: bool = True


@dataclass
class HeadCameraReadOnly:
    ros_rgb_topic: str = ""
    ros_depth_topic: str = ""
    ros_camera_info_topic: str = ""
    camera_cfg: CameraReadOnlyConfig = field(default_factory=CameraReadOnlyConfig)
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _last_frame: Optional[CameraFrame] = None
    _camera_info: Optional[CameraInfo] = None
    _camera_info_stamp: Optional[float] = None
    _rgb_meta: Dict[str, object] = field(default_factory=dict)
    _depth_meta: Dict[str, object] = field(default_factory=dict)
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "head_camera",
            "rgb_topic": self.ros_rgb_topic,
            "depth_topic": self.ros_depth_topic,
            "camera_info_topic": self.ros_camera_info_topic,
            "image_received": False,
            "decode_ok": False,
            "intrinsics_trusted": False,
            "depth_usable": False,
            "depth_aligned": False,
            "frame_cached": False,
            "missing": [],
            "errors": [],
        }
        if not self.ros_rgb_topic:
            report["missing"].append("rgb_topic_unconfigured")
        if not live:
            report["mode"] = "dry_run_schema"
            self._last_probe = report
            return report
        report["mode"] = "live_readonly"
        host_now = time.time()
        if self.ros_camera_info_topic:
            try:
                from sensor_msgs.msg import CameraInfo

                ci = probe_ros2_topic_once(self.ros_camera_info_topic, CameraInfo, timeout_s, store_payload=True)
                report["camera_info"] = {k: v for k, v in ci.items() if k != "msg"}
                if ci.get("ok") and ci.get("msg") is not None:
                    self._ingest_camera_info(ci["msg"])
                    report["intrinsics_trusted"] = self._camera_info is not None and bool(
                        self._camera_info and self._camera_info.fx > 0
                    )
            except ImportError:
                report["camera_info"] = {"ok": False, "error": "sensor_msgs_unavailable"}
                report["errors"].append("sensor_msgs_unavailable")
        else:
            report["missing"].append("camera_info_unconfigured")

        rgb_msg = None
        if self.ros_rgb_topic:
            try:
                from sensor_msgs.msg import Image

                rgb_probe = probe_ros2_topic_once(self.ros_rgb_topic, Image, timeout_s, store_payload=True)
                report["rgb"] = {k: v for k, v in rgb_probe.items() if k != "msg"}
                if rgb_probe.get("ok"):
                    report["image_received"] = True
                    rgb_msg = rgb_probe.get("msg")
            except ImportError:
                report["rgb"] = {"ok": False, "error": "sensor_msgs_unavailable"}
                report["errors"].append("sensor_msgs_unavailable")

        depth_msg = None
        if self.ros_depth_topic:
            try:
                from sensor_msgs.msg import Image

                d = probe_ros2_topic_once(self.ros_depth_topic, Image, timeout_s, store_payload=True)
                report["depth"] = {k: v for k, v in d.items() if k != "msg"}
                if d.get("ok"):
                    depth_msg = d.get("msg")
            except ImportError:
                report["depth"] = {"ok": False, "error": "sensor_msgs_unavailable"}
                report["errors"].append("sensor_msgs_unavailable")
        else:
            report["missing"].append("depth_topic_unconfigured")

        if rgb_msg is not None:
            decoded = decode_sensor_image(
                rgb_msg,
                depth_scale_m=self.camera_cfg.depth_scale_m,
                allow_16uc1_depth=self.camera_cfg.allow_16uc1_depth,
                treat_mono16_as_depth=self.camera_cfg.treat_mono16_as_depth,
            )
            self._rgb_meta = {
                "encoding": decoded.encoding,
                "frame_id": decoded.frame_id,
                "stamp_sec": decoded.stamp_sec,
                "message": decoded.message,
            }
            if decoded.ok and decoded.rgb is not None:
                report["decode_ok"] = True
                self._cache_rgb(decoded, host_now)
                report["frame_cached"] = self._last_frame is not None
            else:
                report["errors"].append(decoded.message)

        if depth_msg is not None and self._last_frame is not None:
            ddec = decode_sensor_image(
                depth_msg,
                depth_scale_m=self.camera_cfg.depth_scale_m,
                allow_16uc1_depth=self.camera_cfg.allow_16uc1_depth,
                treat_mono16_as_depth=self.camera_cfg.treat_mono16_as_depth,
            )
            self._depth_meta = {
                "encoding": ddec.encoding,
                "frame_id": ddec.frame_id,
                "stamp_sec": ddec.stamp_sec,
                "message": ddec.message,
            }
            report["depth_decode_message"] = ddec.message
            if ddec.ok and ddec.depth_m is not None and ddec.depth_scale_confirmed:
                aligned, align_err = self._check_depth_alignment(ddec)
                report["depth_aligned"] = aligned
                if aligned:
                    self._last_frame.depth_m = ddec.depth_m
                    self._last_frame.depth_frame_id = ddec.frame_id
                    self._last_frame.depth_scale_confirmed = True
                    self._last_frame.depth_aligned_to_rgb = True
                    report["depth_usable"] = True
                else:
                    report["errors"].append(align_err)
            elif ddec.encoding.lower() in ("16uc1", "mono16") and not ddec.depth_scale_confirmed:
                report["errors"].append(ddec.message or "depth_scale_unknown")

        if self._last_frame is not None:
            self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        self._last_probe = report
        return report

    def _check_depth_alignment(self, ddec: object) -> tuple:
        from gdps_qi.adapters.readonly.image_decode import ImageDecodeResult

        if not isinstance(ddec, ImageDecodeResult):
            return False, "bad_decode_meta"
        if self._last_frame is None or self._last_frame.rgb is None:
            return False, "no_rgb_for_alignment"
        cfg = self.camera_cfg
        rgb_stamp = self._rgb_meta.get("stamp_sec")
        depth_stamp = ddec.stamp_sec
        if rgb_stamp is not None and depth_stamp is not None:
            if abs(float(rgb_stamp) - float(depth_stamp)) > cfg.max_rgb_depth_stamp_delta_s:
                return False, "rgb_depth_stamp_mismatch"
        if cfg.require_matching_resolution:
            if ddec.width != self._last_frame.rgb.shape[1] or ddec.height != self._last_frame.rgb.shape[0]:
                return False, "rgb_depth_resolution_mismatch"
        if self._camera_info and cfg.require_matching_resolution:
            if self._camera_info.width != ddec.width or self._camera_info.height != ddec.height:
                return False, "camera_info_depth_resolution_mismatch"
        return True, "ok"

    def _ingest_camera_info(self, msg: object) -> None:
        summary = summarize_ros_message(msg)
        k = summary.get("k")
        if not isinstance(k, list) or len(k) < 9:
            return
        w = int(summary.get("width", 0))
        h = int(summary.get("height", 0))
        if w <= 0 or h <= 0:
            return
        stamp = summary.get("stamp_sec")
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
        self._camera_info_stamp = float(stamp) if stamp is not None else None

    def _cache_rgb(self, decoded: object, host_received_at: float) -> None:
        from gdps_qi.adapters.readonly.image_decode import ImageDecodeResult

        if not isinstance(decoded, ImageDecodeResult) or decoded.rgb is None:
            return
        sensor_stamp = decoded.stamp_sec if decoded.stamp_sec is not None else host_received_at
        info = self._camera_info
        trusted = info is not None and info.fx > 0 and info.fy > 0
        self._last_frame = CameraFrame(
            rgb=decoded.rgb,
            depth_m=None,
            stamp=float(sensor_stamp),
            info=info,
            host_received_at=host_received_at,
            rgb_frame_id=decoded.frame_id,
            intrinsics_trusted=trusted,
        )

    def get_latest(self) -> Optional[CameraFrame]:
        return self._last_frame

    def get_camera_info_stamp(self) -> Optional[float]:
        return self._camera_info_stamp
