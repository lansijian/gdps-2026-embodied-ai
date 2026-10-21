"""Camera observation adapter: exhibit matching -> guide observations.

Wraps the existing SIFT/ORB matcher (tracks/cultural-tourism/gdps_tourism/matching)
and exposes two async operations used by the orchestrator:
  - observe(station): after arrival, identify the exhibit on screen
  - scan_route(): low-frequency P3 landmark scan while walking
Matching runs in a thread executor so the asyncio dialogue loop keeps running.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..camera.video_source import VideoFileSource, WebcamSource, open_camera_source
from ..matching.feature_matcher import ExhibitMatcher, TemplateLibrary
from .stations import Station


@dataclass
class CameraConfig:
    templates_dir: str = ""
    method: str = "orb"
    prefilter: str = "orb"
    max_side: int = 1200
    max_features: int = 1500
    device: str = "0"
    backend: Optional[str] = None
    width: int = 1280
    height: int = 720
    video_path: Optional[str] = None
    min_accept_confidence: float = 0.0
    image_topic: Optional[str] = None  # ROS 图像话题（优先于 /dev/video*，由导航/相机模块发布）
    flip: str = "none"  # G1 头部 RealSense 倒装: none | 180 | hflip | vflip
    fast_reject_features: int = 0  # >0 时对极低特征帧快速拒识（默认关闭，现场实测地面帧仍有 ~900 特征，效果有限）


class ExhibitCamera:
    """Template library + camera source + matcher (lazy start)."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self._library: Optional[TemplateLibrary] = None
        self._matcher: Optional[ExhibitMatcher] = None
        self._source = None
        self._template_exhibit: Dict[str, str] = {}
        self._template_station: Dict[str, str] = {}
        self.last_match_ms: float = 0.0
        self.last_template: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self, station_exhibit_map: Optional[Dict[str, List[str]]] = None, ros=None) -> None:
        root = self.config.templates_dir
        if not root or not Path(root).is_dir():
            raise ValueError("templates dir is required (--templates or GDPS_TOURISM_TEMPLATES)")
        self._library = TemplateLibrary.from_directory(
            Path(root),
            method=self.config.method,
            max_side=self.config.max_side,
            max_features=self.config.max_features,
        )
        self._matcher = ExhibitMatcher(
            self._library,
            max_side=self.config.max_side,
            prefilter=self.config.prefilter,
            fast_reject_features=self.config.fast_reject_features,
        )
        for info in self._library.templates:
            self._template_exhibit[info.template_id] = info.exhibit_id or info.template_id
        for station_id, exhibit_ids in (station_exhibit_map or {}).items():
            for exhibit_id in exhibit_ids:
                self._template_station[exhibit_id] = station_id
        self._open_source(ros)

    def _open_source(self, ros=None) -> None:
        """Pick the frame source: ROS image topic > video file > camera device."""

        if self.config.image_topic:
            if ros is None:
                raise RuntimeError("--image-topic 需要 ROS 模式（不要同时用 --no-ros）")
            self._source = ros.make_image_source(self.config.image_topic)
            self._source.start()
        elif self.config.video_path:
            self._source = VideoFileSource(self.config.video_path)
        else:
            self._source = open_camera_source(
                index=self.config.device,
                width=self.config.width,
                height=self.config.height,
                backend=self.config.backend,
            )

    def close(self) -> None:
        if self._source is not None:
            self._source.release()
            self._source = None

    # -- capture / match ---------------------------------------------------
    def _grab(self):
        if self._source is None:
            raise RuntimeError("camera not started")
        frame = self._source.read()
        if frame is None:
            return None
        flip = (self.config.flip or "none").strip().lower()
        if flip == "180":
            return frame[::-1, ::-1].copy()
        if flip == "hflip":
            return frame[:, ::-1].copy()
        if flip == "vflip":
            return frame[::-1].copy()
        return frame

    def _match_frame(self, frame) -> Tuple[Optional[str], float, Optional[str]]:
        if self._matcher is None:
            return None, 0.0, None
        result = self._matcher.match(frame)
        best = result.best
        if best is None:
            return None, 0.0, None
        self.last_match_ms = float(result.diagnostics.get("match_ms", 0.0)) if result.diagnostics else 0.0
        self.last_template = best.template_id
        if not result.accepted or best.confidence < self.config.min_accept_confidence:
            return None, float(best.confidence), best.template_id
        exhibit_id = self._template_exhibit.get(best.template_id, best.template_id)
        return exhibit_id, float(best.confidence), best.template_id

    async def scan_exhibit(self) -> Tuple[Optional[str], float]:
        """Unfiltered exhibit match (vision-triggered navigation)."""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._scan_exhibit_sync)

    def _scan_exhibit_sync(self) -> Tuple[Optional[str], float]:
        frame = self._grab()
        if frame is None:
            return None, 0.0
        exhibit_id, confidence, _template_id = self._match_frame(frame)
        return exhibit_id, confidence

    async def observe(self, station: Station) -> Tuple[Optional[str], float]:
        """One synchronous capture+match hop, executed off the asyncio loop."""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._observe_sync, station)

    def _observe_sync(self, station: Station) -> Tuple[Optional[str], float]:
        frame = self._grab()
        if frame is None:
            return None, 0.0
        exhibit_id, confidence, template_id = self._match_frame(frame)
        if exhibit_id is None:
            return None, confidence
        # Prefer exhibits configured for this station; otherwise report the match.
        if station.exhibit_ids and exhibit_id not in station.exhibit_ids:
            return None, confidence
        return exhibit_id, confidence

    async def scan_route(self) -> Optional[str]:
        """P3: one low-duty landmark scan while navigating."""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._scan_route_sync)

    def _scan_route_sync(self) -> Optional[str]:
        frame = self._grab()
        if frame is None:
            return None
        exhibit_id, confidence, template_id = self._match_frame(frame)
        if exhibit_id is None:
            return None
        station_id = self._template_station.get(exhibit_id)
        if station_id is None:
            return None
        self.last_station_seen = station_id
        return station_id


__all__ = ["CameraConfig", "ExhibitCamera"]
