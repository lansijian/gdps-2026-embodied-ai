"""ORB coarse prefilter: shortlist templates before the expensive exact match.

All template descriptors (computed once at a small working resolution) are
concatenated into a single database.  A frame needs just one BFMatcher order-2
pass over that database; the ratio test votes for template indices, and the
votes become normalised scores.  When the vote is weak or the winner has no
clear lead, the caller must fall back to a full scan so low-texture exhibits
are never lost to the shortcut.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import numpy as np

from .._cv2 import require_cv2

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .feature_matcher import TemplateLibrary


@dataclass(frozen=True)
class PrefilterResult:
    """Template indices proposed by the coarse stage.

    full_scan means the caller must ignore indices and compare every template;
    reason records why (None when the shortlist is usable).
    """

    indices: List[int]
    scores: List[float]
    full_scan: bool
    reason: Optional[str]


def _resize_max_side(cv2, image: np.ndarray, max_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("image has an empty shape")
    scale = float(max_side) / float(max(height, width))
    if scale >= 1.0:
        return image
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)


def _read_gray(cv2, path: Path) -> Optional[np.ndarray]:
    """Read a template as grayscale via bytes so CJK paths work everywhere."""

    try:
        payload = Path(path).read_bytes()
    except OSError:
        return None
    if not payload:
        return None
    buffer = np.frombuffer(payload, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)


class CoarsePrefilter:
    """Vote templates with one ORB BFMatcher pass over a shared descriptor DB.

    Thresholds were calibrated with tools/bench_camera.py (1280x720 synthetic
    scenes, 640px / 400-feature ORB, one BFMatcher k=2 pass over the shared
    descriptor DB): correct shortlists score >= 0.065 while the low-texture
    EXH_014 rubbing (25.jpg / 025.jpg) scores <= 0.007 and negative frames
    score <= 0.015, so min_score=0.05 forces exactly the known hard case and
    non-exhibit frames to a full scan.  Correct shortlists keep a
    first-to-second margin >= 0.27, so min_margin=0.05 only catches near ties.
    """

    def __init__(
        self,
        library: "TemplateLibrary",
        *,
        size: int = 640,
        max_features: int = 400,
        ratio: float = 0.75,
        top_k: int = 3,
        min_score: float = 0.05,
        min_margin: float = 0.05,
    ) -> None:
        if library is None or len(library) == 0:
            raise ValueError("template library is empty")
        if size < 64:
            raise ValueError("prefilter size must be at least 64")
        if max_features < 32:
            raise ValueError("prefilter max_features must be at least 32")
        if not 0.0 < ratio < 1.0:
            raise ValueError("prefilter ratio must be between 0 and 1")
        if top_k < 1:
            raise ValueError("prefilter top_k must be at least 1")
        if min_score < 0.0:
            raise ValueError("prefilter min_score must be non-negative")
        if min_margin < 0.0:
            raise ValueError("prefilter min_margin must be non-negative")

        self.library = library
        self.size = int(size)
        self.max_features = int(max_features)
        self.ratio = float(ratio)
        self.top_k = int(top_k)
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)

        cv2 = require_cv2()
        self._cv2 = cv2
        self._detector = cv2.ORB_create(nfeatures=self.max_features)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)

        descriptors: List[np.ndarray] = []
        owners: List[np.ndarray] = []
        for info in library.templates:
            gray = _read_gray(cv2, info.source_path)
            if gray is None:
                warnings.warn(
                    "prefilter cannot read template image: %s" % info.source_path,
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            gray = _resize_max_side(cv2, gray, self.size)
            keypoints, template_des = self._detector.detectAndCompute(gray, None)
            if template_des is None or len(template_des) == 0:
                continue
            descriptors.append(template_des)
            owners.append(np.full(len(template_des), info.index, dtype=np.int32))

        # 模板在粗筛层太少时直接退化到全量扫描，避免不可靠的短名单。
        self._degraded = len(descriptors) <= self.top_k
        if descriptors:
            self._db: Optional[np.ndarray] = np.ascontiguousarray(np.vstack(descriptors))
            self._db_owner: Optional[np.ndarray] = np.concatenate(owners)
        else:
            self._db = None
            self._db_owner = None
            warnings.warn("prefilter has no usable template descriptors", RuntimeWarning)

    @property
    def degraded(self) -> bool:
        return self._degraded

    @classmethod
    def disabled(cls) -> "PrefilterResult":
        """Result used when the prefilter is switched off entirely."""

        return PrefilterResult(indices=[], scores=[], full_scan=True, reason="disabled")

    def shortlist(self, frame_bgr: np.ndarray) -> PrefilterResult:
        """Rank templates by ORB ratio-test votes for one query frame."""

        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            raise ValueError("frame is empty")
        if self._degraded or self._db is None or self._db_owner is None:
            return PrefilterResult([], [], True, "too_few_templates")
        if len(self.library) <= self.top_k:
            return PrefilterResult([], [], True, "too_few_templates")

        cv2 = self._cv2
        gray = frame_bgr if frame_bgr.ndim == 2 else cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = _resize_max_side(cv2, gray, self.size)
        keypoints, query_des = self._detector.detectAndCompute(gray, None)
        if query_des is None or len(query_des) == 0:
            # 没有可用 ORB 特征时投票分视为 0，按低分处理并回退全量扫描。
            return PrefilterResult([], [], True, "low_score")

        try:
            pairs = self._bf.knnMatch(query_des, self._db, k=2)
        except cv2.error:
            warnings.warn("prefilter BFMatcher failed; using full scan", RuntimeWarning)
            return PrefilterResult([], [], True, "low_score")
        # 收集落入 ratio-test 的模板 index，再一次 bincount 完成投票。
        winners = np.fromiter(
            (
                int(self._db_owner[pair[0].trainIdx])
                for pair in pairs
                if len(pair) == 2 and pair[0].distance < self.ratio * pair[1].distance
            ),
            dtype=np.int32,
        )
        if winners.size:
            votes = np.bincount(winners, minlength=len(self.library)).astype(np.float32)
        else:
            votes = np.zeros(len(self.library), dtype=np.float32)

        scores = votes / float(len(query_des))
        order = np.argsort(-scores)[: self.top_k]
        indices: List[int] = []
        ranked: List[float] = []
        for raw_index in order:
            score = float(scores[int(raw_index)])
            if score <= 0.0:
                continue
            indices.append(int(raw_index))
            ranked.append(score)
        if not indices:
            return PrefilterResult([], [], True, "low_score")

        if ranked[0] < self.min_score:
            return PrefilterResult(indices, ranked, True, "low_score")
        margin = self._relative_margin(ranked)
        if margin < self.min_margin:
            return PrefilterResult(indices, ranked, True, "low_margin")
        return PrefilterResult(indices, ranked, False, None)

    @staticmethod
    def _relative_margin(scores: List[float]) -> float:
        if len(scores) < 2:
            return 1.0
        top = scores[0]
        if top <= 0.0:
            return 0.0
        return (top - scores[1]) / top


__all__ = ["CoarsePrefilter", "PrefilterResult"]
