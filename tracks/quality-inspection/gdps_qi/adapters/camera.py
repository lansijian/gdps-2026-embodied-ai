from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from gdps_qi.types import VerificationStatus


@dataclass(frozen=True)
class CameraInfo:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    frame_id: str = "head_camera_optical"
    distortion: Tuple[float, ...] = ()
    calibration_id: str = "mock"
    verified: bool = False

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("invalid image size")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("invalid focal length")


@dataclass
class CameraFrame:
    rgb: Optional[np.ndarray]
    depth_m: Optional[np.ndarray]
    stamp: float
    info: Optional[CameraInfo]
    host_received_at: float = 0.0
    rgb_frame_id: str = ""
    depth_frame_id: str = ""
    depth_scale_confirmed: bool = False
    depth_aligned_to_rgb: bool = False
    intrinsics_trusted: bool = False


@dataclass
class CameraAdapter:
    """RGB/Depth access. Default mock stream for offline tests."""

    interface_status: VerificationStatus = VerificationStatus.UNKNOWN
    _info: CameraInfo = field(
        default_factory=lambda: CameraInfo(
            width=640,
            height=480,
            fx=600.0,
            fy=600.0,
            cx=320.0,
            cy=240.0,
            verified=False,
        )
    )
    _frame: Optional[CameraFrame] = None

    def connect(self) -> int:
        return 0

    def get_camera_info(self) -> CameraInfo:
        return self._info

    def set_mock_frame(self, rgb: np.ndarray, depth_m: Optional[np.ndarray] = None) -> None:
        self._info.validate()
        if rgb.shape[0] != self._info.height or rgb.shape[1] != self._info.width:
            raise ValueError("rgb shape mismatch")
        if depth_m is not None and depth_m.shape != rgb.shape[:2]:
            raise ValueError("depth shape mismatch")
        now = time.time()
        self._frame = CameraFrame(
            rgb=rgb,
            depth_m=depth_m,
            stamp=now,
            info=self._info,
            host_received_at=now,
            intrinsics_trusted=self._info.fx > 0 and self._info.fy > 0,
            depth_scale_confirmed=depth_m is not None,
            depth_aligned_to_rgb=depth_m is not None,
        )

    def grab(self, max_age_s: float = 0.5) -> Optional[CameraFrame]:
        if self._frame is None:
            return None
        if (time.time() - self._frame.stamp) > max_age_s:
            return None
        return self._frame
