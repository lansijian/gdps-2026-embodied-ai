"""Uniform webcam / image / video reading for the tourism CLIs.

Runs unchanged on macOS (AVFoundation), Linux (V4L2, including Ubuntu 20.04
on a Unitree G1) and Windows (DirectShow / MSMF).  Intel RealSense cameras are
supported through the optional "realsense" backend.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import List, Optional, Union

import numpy as np

from .._cv2 import require_cv2

CameraIndex = Union[int, str]


def default_camera_backend() -> str:
    """Backend name that matches this platform."""

    if sys.platform == "darwin":
        return "avfoundation"
    if sys.platform.startswith("win"):
        return "dshow"
    return "v4l2"


def normalize_backend(backend: Optional[str]) -> str:
    """Map a backend name from another platform onto this one."""

    key = (backend or "any").strip().lower()
    if sys.platform == "darwin" and key in ("dshow", "msmf", "v4l2"):
        return "avfoundation"
    if sys.platform.startswith("linux") and key in ("dshow", "msmf", "avfoundation"):
        return "v4l2"
    if sys.platform.startswith("win") and key in ("avfoundation", "v4l2"):
        return "dshow"
    return key


def normalize_camera_index(index: Union[int, str]) -> Union[int, str]:
    """Keep paths / URLs as strings; convert "0" / "1" to int indices."""

    if isinstance(index, str):
        text = index.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return text
    return int(index)


def backend_code(name: str) -> int:
    """OpenCV backend constant for a normalised backend name."""

    cv2 = require_cv2()
    return {
        "dshow": getattr(cv2, "CAP_DSHOW", 0),
        "msmf": getattr(cv2, "CAP_MSMF", 0),
        "avfoundation": getattr(cv2, "CAP_AVFOUNDATION", 0),
        "v4l2": getattr(cv2, "CAP_V4L2", 0),
        "any": 0,
    }[name]


def list_cameras() -> List[dict]:
    """Best-effort camera enumeration.

    Linux reads the sysfs entries so no camera is opened; other platforms return
    an empty list because probing would trigger the macOS permission dialog.
    """

    devices: List[dict] = []
    if sys.platform.startswith("linux"):
        root = Path("/sys/class/video4linux")
        if root.is_dir():
            for entry in sorted(root.glob("video*")):
                name = ""
                name_file = entry / "name"
                try:
                    name = name_file.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    pass
                devices.append({"index": "/dev/" + entry.name, "name": name})
    return devices


def describe_camera_help() -> str:
    """Platform-specific hint appended to camera errors."""

    if sys.platform == "darwin":
        return (
            "【权限提示】macOS 需要为运行 Python 的终端授权摄像头：\n"
            "系统设置 -> 隐私与安全性 -> 摄像头，勾选 Terminal / iTerm / VSCode 等。"
        )
    if sys.platform.startswith("linux"):
        return (
            "【Linux 排查】\n"
            "1) ls -l /dev/video*            确认设备节点存在\n"
            "2) sudo usermod -aG video $USER 然后重新登录（或 sudo chmod 666 /dev/video0）\n"
            "3) v4l2-ctl --list-devices     列出可用摄像头（apt install v4l-utils）\n"
            "4) 无显示器的机器请加 --headless"
        )
    return "请确认摄像头未被其它程序占用，或尝试 --camera 1 / --backend msmf。"


class VideoSource:
    """Small common interface: read() returns a BGR frame or None."""

    fps = 30.0
    frame_count = 0
    width = 0
    height = 0

    def read(self) -> Optional[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError

    def release(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def duration_s(self) -> float:
        if self.fps <= 0 or self.frame_count <= 0:
            return 0.0
        return self.frame_count / self.fps

    def __enter__(self) -> "VideoSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ImageSource(VideoSource):
    """Yield a single image (decoded through bytes for CJK paths)."""

    def __init__(self, path) -> None:
        cv2 = require_cv2()
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError("image does not exist: %s" % self.path)
        payload = self.path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cannot decode image: %s" % self.path)
        self._frame: Optional[np.ndarray] = frame
        self.height, self.width = frame.shape[:2]
        self.frame_count = 1
        self.fps = 1.0

    def read(self) -> Optional[np.ndarray]:
        frame = self._frame
        self._frame = None
        return frame

    def release(self) -> None:
        self._frame = None


class VideoFileSource(VideoSource):
    """Read frames from a video file (useful for offline replay on the robot)."""

    def __init__(self, path) -> None:
        cv2 = require_cv2()
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError("video does not exist: %s" % self.path)
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise RuntimeError("cannot open video: %s" % self.path)
        reported_fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.fps = reported_fps if reported_fps > 0 else 30.0
        self.frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        if getattr(self, "_cap", None) is not None:
            self._cap.release()
            self._cap = None


class WebcamSource(VideoSource):
    """Read frames from a local camera (number, /dev/videoN or a stream URL)."""

    def __init__(
        self,
        index: CameraIndex = 0,
        width: int = 1280,
        height: int = 720,
        backend: Optional[str] = None,
    ) -> None:
        cv2 = require_cv2()
        self.requested_index = index
        self.index = normalize_camera_index(index)
        self.backend = normalize_backend(backend or default_camera_backend())
        if self.backend not in ("dshow", "msmf", "avfoundation", "v4l2", "any"):
            raise ValueError(
                "unknown camera backend %r (use avfoundation, v4l2, dshow, msmf, any or realsense)"
                % (backend,)
            )

        code = backend_code(self.backend)
        cap = cv2.VideoCapture(self.index, code)
        if not cap.isOpened() and code != 0:
            cap.release()
            cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(
                "无法打开摄像头 %r（backend=%s）\n%s"
                % (self.index, self.backend, describe_camera_help())
            )
        self._cap = cap
        if width > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        if height > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or width)
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or height)
        reported_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.fps = reported_fps if reported_fps > 0 else 30.0
        self.frame_count = 0

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        if getattr(self, "_cap", None) is not None:
            self._cap.release()
            self._cap = None


def open_camera_source(
    index: CameraIndex = 0,
    width: int = 1280,
    height: int = 720,
    backend: Optional[str] = None,
) -> VideoSource:
    """Open a camera by backend name ("realsense" gets its own source)."""

    key = normalize_backend(backend or default_camera_backend())
    if key == "realsense":
        from .realsense_source import RealSenseSource

        return RealSenseSource(width=width, height=height)
    return WebcamSource(index=index, width=width, height=height, backend=backend)


__all__ = [
    "ImageSource",
    "VideoFileSource",
    "VideoSource",
    "WebcamSource",
    "open_camera_source",
    "default_camera_backend",
    "normalize_backend",
    "normalize_camera_index",
    "list_cameras",
    "describe_camera_help",
]
