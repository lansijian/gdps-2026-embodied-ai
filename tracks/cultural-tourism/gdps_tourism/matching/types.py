"""Value objects returned by the exhibit matcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class TemplateInfo:
    """One reference image in the template library."""

    index: int
    template_id: str
    display_name: str
    source_path: Path
    width: int
    height: int
    keypoint_count: int
    # 展品组：同一展品的多张模板（如正面/背面、原图/拓本）共享 exhibit_id。
    # 空值表示旧数据源未提供，组键回退到 template_id。
    exhibit_id: str = ""
    exhibit_name: str = ""


@dataclass(frozen=True)
class MatchCandidate:
    """A single template compared against one query frame."""

    info: TemplateInfo
    inliers: int
    good_matches: int
    inlier_ratio: float
    confidence: float
    homography: Optional[np.ndarray]
    geometry_valid: bool

    @property
    def template_id(self) -> str:
        return self.info.template_id

    @property
    def display_name(self) -> str:
        return self.info.display_name

    @property
    def exhibit_id(self) -> str:
        return self.info.exhibit_id or self.info.template_id

    @property
    def exhibit_name(self) -> str:
        return self.info.exhibit_name or self.info.display_name


@dataclass(frozen=True)
class MatchResult:
    """Raw per-frame matching result before temporal voting."""

    best: Optional[MatchCandidate]
    candidates: List[MatchCandidate]
    accepted: bool
    unknown_reason: Optional[str]
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class StableMatch:
    """Result after applying the sliding-window vote."""

    template_id: Optional[str]
    display_name: Optional[str]
    confidence: float
    raw_accepted: bool
    reason: Optional[str]
    template_index: Optional[int] = None
