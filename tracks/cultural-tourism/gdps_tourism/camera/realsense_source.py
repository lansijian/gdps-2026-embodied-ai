"""Optional Intel RealSense colour source (Unitree G1 commonly carries D435i)."""

from __future__ import annotations

from typing import Optional

import numpy as np

from .video_source import VideoSource


class RealSenseSource(VideoSource):
    """Colour stream from an Intel RealSense camera via pyrealsense2.

    pyrealsense2 is only imported when this source is actually used, so the rest
    of the project keeps working on machines without the SDK installed.
    """

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30) -> None:
        try:
            import pyrealsense2 as rs  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on robot install
            raise RuntimeError(
                "RealSense 摄像头需要 pyrealsense2：pip install pyrealsense2\n"
                "（Jetson/Ubuntu 20.04 上的安装方式见 deploy/ubuntu_g1/README.md）"
            ) from exc
        self._rs = rs
        self._pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, int(width), int(height), rs.format.bgr8, int(fps))
        try:
            profile = self._pipeline.start(config)
        except Exception as exc:  # pragma: no cover - hardware dependent
            raise RuntimeError("无法启动 RealSense 彩色流：%s" % exc) from exc
        stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
        self.width = int(stream.width())
        self.height = int(stream.height())
        self.fps = float(stream.fps())
        self.frame_count = 0

    def read(self) -> Optional[np.ndarray]:
        try:
            frames = self._pipeline.wait_for_frames(1000)
        except RuntimeError:
            return None
        colour = frames.get_color_frame()
        if not colour:
            return None
        self.frame_count += 1
        return np.asanyarray(colour.get_data()).copy()

    def release(self) -> None:
        if getattr(self, "_pipeline", None) is not None:
            try:
                self._pipeline.stop()
            finally:
                self._pipeline = None


__all__ = ["RealSenseSource"]
