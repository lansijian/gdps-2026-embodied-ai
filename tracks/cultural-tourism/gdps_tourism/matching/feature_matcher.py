"""SIFT/ORB template matching with RANSAC homography verification."""

from __future__ import annotations

import hashlib
import json
import math
import time
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .._cv2 import require_cv2
from .prefilter import CoarsePrefilter
from .types import MatchCandidate, MatchResult, TemplateInfo

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")
_MIN_TEMPLATE_FEATURES = 10


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


def _unique_name(name: str, used: set) -> str:
    candidate = name
    suffix = 2
    while candidate in used:
        candidate = "%s__%d" % (name, suffix)
        suffix += 1
    used.add(candidate)
    return candidate


def _create_detector(cv2, method: str, max_features: int):
    requested = (method or "sift").strip().lower()
    if requested == "sift":
        if hasattr(cv2, "SIFT_create"):
            return cv2.SIFT_create(nfeatures=max_features), "sift", cv2.NORM_L2
        warnings.warn(
            "SIFT is unavailable in this OpenCV build; falling back to ORB.",
            RuntimeWarning,
            stacklevel=3,
        )
        requested = "orb"
    if requested == "orb":
        return cv2.ORB_create(nfeatures=max_features), "orb", cv2.NORM_HAMMING
    raise ValueError("method must be 'sift' or 'orb', got %r" % (method,))


def _read_image_bgr(cv2, path: Path) -> Optional[np.ndarray]:
    """Read an image via bytes so Windows CJK paths work reliably."""

    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not payload:
        return None
    buffer = np.frombuffer(payload, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _load_knowledge_maps(root: Path) -> Tuple[Dict[str, str], Dict[str, Tuple[str, str]]]:
    """Read knowledge_base.json when present.

    Returns stem -> display_name and stem -> (exhibit_id, exhibit_name) so
    several template images can be grouped into one exhibit.  Missing or
    broken files are silently ignored: the library still works with plain
    template ids.
    """

    name_map: Dict[str, str] = {}
    exhibit_map: Dict[str, Tuple[str, str]] = {}
    for candidate in (root / "knowledge_base.json", root.parent / "knowledge_base.json"):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            break
        for item in list(payload.get("exhibits", [])) + list(payload.get("composite_boards", [])):
            exhibit_id = str(item.get("id") or item.get("name") or "")
            exhibit_name = str(item.get("name") or exhibit_id)
            if not exhibit_id:
                continue
            stems = [Path(entry).stem for entry in item.get("associated_images", [])]
            if item.get("primary_image"):
                stems.append(Path(item["primary_image"]).stem)
            for stem in stems:
                name_map[stem] = exhibit_name
                exhibit_map[stem] = (exhibit_id, exhibit_name)
        break
    return name_map, exhibit_map


class TemplateLibrary:
    """Reference images plus their precomputed keypoints and descriptors."""

    def __init__(
        self,
        templates: Sequence[TemplateInfo],
        keypoints: Sequence[Sequence],
        descriptors: Sequence[Optional[np.ndarray]],
        method_used: str,
        detector,
    ) -> None:
        if not templates:
            raise ValueError("template library is empty")
        self.templates = list(templates)
        self.keypoints = list(keypoints)
        self.descriptors = list(descriptors)
        self.method_used = method_used
        self.detector = detector

    def __len__(self) -> int:
        return len(self.templates)

    @property
    def ids(self) -> List[str]:
        return [item.template_id for item in self.templates]

    def describe(self) -> List[Dict[str, object]]:
        return [
            {
                "index": item.index,
                "template_id": item.template_id,
                "display_name": item.display_name,
                "source_path": str(item.source_path),
                "width": item.width,
                "height": item.height,
                "keypoint_count": item.keypoint_count,
                "exhibit_id": item.exhibit_id or item.template_id,
                "exhibit_name": item.exhibit_name or item.display_name,
            }
            for item in self.templates
        ]

    @classmethod
    def from_directory(
        cls,
        directory,
        method: str = "sift",
        max_side: int = 1200,
        max_features: int = 1500,
    ) -> "TemplateLibrary":
        cv2 = require_cv2()
        root = Path(directory)
        if not root.is_dir():
            raise ValueError("template directory does not exist: %s" % root)
        files = sorted(
            (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES),
            key=lambda p: p.name,
        )
        if not files:
            raise ValueError("no template images found in %s" % root)

        # 尝试自动从 knowledge_base.json 加载展品标准中文名与展品组 ID
        name_map, exhibit_map = _load_knowledge_maps(root)

        detector, method_used, _norm = _create_detector(cv2, method, max_features)
        templates: List[TemplateInfo] = []
        keypoints: List[Sequence] = []
        descriptors: List[Optional[np.ndarray]] = []
        used_ids: set = set()

        for path in files:
            image = _read_image_bgr(cv2, path)
            if image is None:
                warnings.warn("cannot read template image: %s" % path, RuntimeWarning)
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = _resize_max_side(cv2, gray, max_side)
            kp, des = detector.detectAndCompute(gray, None)
            if des is None or len(des) < _MIN_TEMPLATE_FEATURES:
                warnings.warn(
                    "skipping template with too few features: %s (%d keypoints)"
                    % (path, 0 if des is None else len(des)),
                    RuntimeWarning,
                )
                continue
            template_id = _unique_name(path.stem, used_ids)
            display_name = name_map.get(path.stem, template_id)
            exhibit_id, exhibit_name = exhibit_map.get(path.stem, (template_id, display_name))
            info = TemplateInfo(
                index=len(templates),
                template_id=template_id,
                display_name=display_name,
                source_path=path,
                width=int(gray.shape[1]),
                height=int(gray.shape[0]),
                keypoint_count=len(kp),
                exhibit_id=exhibit_id,
                exhibit_name=exhibit_name,
            )
            templates.append(info)
            keypoints.append(kp)
            descriptors.append(des)

        if not templates:
            raise ValueError("no usable templates found in %s" % root)
        return cls(templates, keypoints, descriptors, method_used, detector)

    @classmethod
    def from_arrays(
        cls,
        images: Dict[str, np.ndarray],
        method: str = "sift",
        max_side: int = 1200,
        max_features: int = 1500,
    ) -> "TemplateLibrary":
        """Build a library from in-memory BGR/gray images (used by tests)."""

        cv2 = require_cv2()
        if not images:
            raise ValueError("images mapping is empty")
        detector, method_used, _norm = _create_detector(cv2, method, max_features)
        templates: List[TemplateInfo] = []
        keypoints: List[Sequence] = []
        descriptors: List[Optional[np.ndarray]] = []
        used_ids: set = set()

        for name, image in images.items():
            if image is None or getattr(image, "size", 0) == 0:
                warnings.warn("skipping empty template: %s" % name, RuntimeWarning)
                continue
            gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = _resize_max_side(cv2, gray, max_side)
            kp, des = detector.detectAndCompute(gray, None)
            if des is None or len(des) < _MIN_TEMPLATE_FEATURES:
                warnings.warn(
                    "skipping template with too few features: %s" % name, RuntimeWarning
                )
                continue
            template_id = _unique_name(str(name), used_ids)
            info = TemplateInfo(
                index=len(templates),
                template_id=template_id,
                display_name=template_id,
                source_path=Path(template_id),
                width=int(gray.shape[1]),
                height=int(gray.shape[0]),
                keypoint_count=len(kp),
                exhibit_id=template_id,
                exhibit_name=template_id,
            )
            templates.append(info)
            keypoints.append(kp)
            descriptors.append(des)

        if not templates:
            raise ValueError("no usable templates in the provided images")
        return cls(templates, keypoints, descriptors, method_used, detector)


class ExhibitMatcher:
    """Match a camera frame against a :class:`TemplateLibrary`."""

    def __init__(
        self,
        library: TemplateLibrary,
        *,
        method: Optional[str] = None,
        max_side: int = 1200,
        ratio: float = 0.70,
        ransac_reproj_px: float = 5.0,
        min_inliers: int = 20,
        min_inlier_ratio: float = 0.40,
        min_confidence: float = 0.50,
        min_margin: float = 0.15,
        confidence_full_inliers: float = 120.0,
        confidence_full_ratio: float = 0.60,
        confidence_full_margin: float = 0.50,
        top_k: int = 3,
        min_query_features: int = 10,
        prefilter: str = "orb",
        prefilter_top_k: int = 3,
        prefilter_size: int = 640,
        prefilter_min_score: float = 0.05,
        prefilter_min_margin: float = 0.05,
        dedupe: bool = True,
        group_by_exhibit: bool = True,
    ) -> None:
        if library is None or len(library) == 0:
            raise ValueError("template library is empty")
        if method is not None and method.strip().lower() != library.method_used:
            raise ValueError(
                "matcher method %r does not match library method %r"
                % (method, library.method_used)
            )
        if not 0.0 < ratio < 1.0:
            raise ValueError("ratio must be between 0 and 1")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        requested_prefilter = (prefilter or "off").strip().lower()
        if requested_prefilter not in ("orb", "off"):
            raise ValueError("prefilter must be 'orb' or 'off', got %r" % (prefilter,))
        if prefilter_top_k < 1:
            raise ValueError("prefilter_top_k must be at least 1")
        if prefilter_size < 64:
            raise ValueError("prefilter_size must be at least 64")

        self.library = library
        self.max_side = int(max_side)
        self.ratio = float(ratio)
        self.ransac_reproj_px = float(ransac_reproj_px)
        self.min_inliers = int(min_inliers)
        self.min_inlier_ratio = float(min_inlier_ratio)
        self.min_confidence = float(min_confidence)
        self.min_margin = float(min_margin)
        self.confidence_full_inliers = float(confidence_full_inliers)
        self.confidence_full_ratio = float(confidence_full_ratio)
        self.confidence_full_margin = float(confidence_full_margin)
        self.top_k = int(top_k)
        self.min_query_features = int(min_query_features)
        # A shortlist-only answer must clear these to skip the exhaustive scan
        # when the coarse vote was uncertain (see _decisive).  The bar is high on
        # purpose: on the low-texture silver rubbing (EXH_014) the coarse vote is
        # unreliable and a related composite board (011) can reach ~76 inliers, so
        # only a support-saturating match is allowed to bypass the full scan.
        self._decisive_inliers = max(int(self.min_inliers) * 3, 120)
        self._decisive_confidence = max(float(self.min_confidence), 0.70)

        self._cv2 = require_cv2()
        norm = self._cv2.NORM_L2 if library.method_used == "sift" else self._cv2.NORM_HAMMING
        self._bf = self._cv2.BFMatcher(norm)

        self.prefilter = requested_prefilter
        self.prefilter_top_k = int(prefilter_top_k)
        self.prefilter_size = int(prefilter_size)
        self.dedupe = bool(dedupe)
        self.group_by_exhibit = bool(group_by_exhibit)

        # 模板去重：内容完全相同的模板（如 25.jpg / 025.jpg）只扫描第一张。
        self._scan_indices: List[int] = []
        self._duplicate_of: Dict[int, int] = {}
        self._build_scan_plan()

        self._prefilter: Optional[CoarsePrefilter] = None
        if self.prefilter == "orb":
            self._prefilter = CoarsePrefilter(
                library,
                size=self.prefilter_size,
                top_k=self.prefilter_top_k,
                min_score=float(prefilter_min_score),
                min_margin=float(prefilter_min_margin),
            )

    @property
    def method_used(self) -> str:
        return self.library.method_used

    def _build_scan_plan(self) -> None:
        """Precompute which template indices the exact stage may scan."""

        self._scan_indices = []
        self._duplicate_of = {}
        if not self.dedupe:
            self._scan_indices = list(range(len(self.library)))
            return
        seen: Dict[bytes, int] = {}
        for index, descriptor in enumerate(self.library.descriptors):
            if descriptor is None or len(descriptor) == 0:
                self._scan_indices.append(index)
                continue
            fingerprint = hashlib.md5(
                np.ascontiguousarray(descriptor).tobytes()
            ).digest()
            kept = seen.get(fingerprint)
            if kept is None:
                seen[fingerprint] = index
                self._scan_indices.append(index)
            else:
                self._duplicate_of[index] = kept

    def _resolve_shortlist(self, indices: Sequence[int]) -> List[int]:
        """Map shortlisted indices onto the kept templates, dropping repeats."""

        resolved: List[int] = []
        seen = set()
        for index in indices:
            canonical = self._duplicate_of.get(int(index), int(index))
            if canonical in seen:
                continue
            seen.add(canonical)
            resolved.append(canonical)
        return resolved

    def _group_key(self, info: TemplateInfo) -> str:
        if self.group_by_exhibit and info.exhibit_id:
            return info.exhibit_id
        return info.template_id

    def _group_candidates(self, scored: List[MatchCandidate]) -> List[MatchCandidate]:
        """Keep the best candidate per exhibit group; groups stay inliers-sorted."""

        if not self.group_by_exhibit:
            return scored
        best_by_group: Dict[str, MatchCandidate] = {}
        for candidate in scored:
            key = self._group_key(candidate.info)
            if key not in best_by_group:
                best_by_group[key] = candidate
        return sorted(
            best_by_group.values(),
            key=lambda candidate: (candidate.inliers, candidate.inlier_ratio),
            reverse=True,
        )

    def _diagnostics(
        self,
        *,
        query_features: int,
        scanned_templates: int,
        full_scan_used: bool,
        prefilter_ms: float,
        prefilter_reason: Optional[str],
        margin: float,
        started: float,
    ) -> Dict[str, object]:
        return {
            "method": self.method_used,
            "query_features": int(query_features),
            "template_count": len(self.library),
            "scanned_templates": int(scanned_templates),
            "full_scan_used": bool(full_scan_used),
            "prefilter_ms": round(float(prefilter_ms), 2),
            "prefilter_reason": prefilter_reason,
            "margin": round(float(margin), 4),
            "match_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }

    def _scan(
        self,
        indices: Sequence[int],
        query_des: np.ndarray,
        keypoints,
        query_width: int,
        query_height: int,
    ) -> List[MatchCandidate]:
        """Exact-match one query frame against the given template indices."""

        cv2 = self._cv2
        scored: List[MatchCandidate] = []
        for index in indices:
            info = self.library.templates[index]
            template_kp = self.library.keypoints[index]
            template_des = self.library.descriptors[index]
            if template_des is None:
                continue
            good = self._ratio_matches(query_des, template_des)
            if len(good) < 4:
                scored.append(
                    MatchCandidate(
                        info=info,
                        inliers=0,
                        good_matches=len(good),
                        inlier_ratio=0.0,
                        confidence=0.0,
                        homography=None,
                        geometry_valid=False,
                    )
                )
                continue

            template_pts = np.float32([template_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            query_pts = np.float32([keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            try:
                homography, mask = cv2.findHomography(
                    template_pts, query_pts, cv2.RANSAC, self.ransac_reproj_px
                )
            except cv2.error:
                homography, mask = None, None
            inliers = int(mask.sum()) if mask is not None else 0
            inlier_ratio = float(inliers) / float(len(good)) if good else 0.0
            geometry_valid = self._homography_valid(
                homography, info.width, info.height, query_width, query_height
            )
            support = min(1.0, float(inliers) / max(1.0, self.confidence_full_inliers))
            ratio_score = min(1.0, inlier_ratio / max(1e-6, self.confidence_full_ratio))
            base_confidence = 0.55 * support + 0.25 * ratio_score
            scored.append(
                MatchCandidate(
                    info=info,
                    inliers=inliers,
                    good_matches=len(good),
                    inlier_ratio=inlier_ratio,
                    confidence=base_confidence,
                    homography=homography,
                    geometry_valid=geometry_valid,
                )
            )
        return scored

    def _evaluate(self, scored: List[MatchCandidate]):
        """Sort, apply the exhibit-group margin rule and decide accept/reject."""

        if not scored:
            return None, [], False, "no_templates", 0.0
        scored.sort(key=lambda candidate: (candidate.inliers, candidate.inlier_ratio), reverse=True)
        # 同一展品组内多张模板不互相竞争：margin 用不同展品组的最佳候选计算。
        grouped = self._group_candidates(scored)
        best = grouped[0]
        second = grouped[1] if len(grouped) > 1 else None
        second_inliers = second.inliers if second is not None else 0
        margin = float(best.inliers - second_inliers) / float(max(1, best.inliers))
        margin_score = min(1.0, margin / max(1e-6, self.confidence_full_margin))
        best = replace(best, confidence=min(1.0, best.confidence + 0.20 * margin_score))
        grouped[0] = best
        reason = self._rejection_reason(best, margin)
        return best, grouped[: max(1, self.top_k)], reason is None, reason, margin

    def _decisive(self, best: Optional[MatchCandidate], accepted: bool) -> bool:
        """True when a shortlist-only result is strong enough to skip the full scan.

        Only consulted when the coarse vote was uncertain (full_scan requested): a
        borderline shortlist hit still triggers the exhaustive scan so a missing
        competitor cannot silently turn into a false accept.
        """

        if not accepted or best is None:
            return False
        return (
            best.inliers >= self._decisive_inliers
            and best.confidence >= self._decisive_confidence
            and best.geometry_valid
        )

    def match(self, frame_bgr: np.ndarray) -> MatchResult:
        cv2 = self._cv2
        started = time.perf_counter()
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            raise ValueError("frame is empty")
        gray = frame_bgr if frame_bgr.ndim == 2 else cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = _resize_max_side(cv2, gray, self.max_side)
        query_height, query_width = gray.shape[:2]
        keypoints, query_des = self.library.detector.detectAndCompute(gray, None)
        query_count = 0 if keypoints is None else len(keypoints)

        if query_des is None or query_count < self.min_query_features:
            return MatchResult(
                best=None,
                candidates=[],
                accepted=False,
                unknown_reason="too_few_features",
                diagnostics=self._diagnostics(
                    query_features=query_count,
                    scanned_templates=0,
                    full_scan_used=False,
                    prefilter_ms=0.0,
                    prefilter_reason="disabled" if self._prefilter is None else None,
                    margin=0.0,
                    started=started,
                ),
            )

        # 粗筛：用 ORB 投票先缩小候选集；投票弱/领先不明显时标记 full_scan。
        proposal = None
        prefilter_ms = 0.0
        prefilter_reason: Optional[str] = "disabled" if self._prefilter is None else None
        if self._prefilter is None:
            scan_indices = list(self._scan_indices)
            full_scan_used = True
        else:
            prefilter_started = time.perf_counter()
            proposal = self._prefilter.shortlist(gray)
            prefilter_ms = (time.perf_counter() - prefilter_started) * 1000.0
            prefilter_reason = proposal.reason
            if proposal.indices:
                scan_indices = self._resolve_shortlist(proposal.indices)
                full_scan_used = False
            else:
                scan_indices = list(self._scan_indices)
                full_scan_used = True

        scored = self._scan(scan_indices, query_des, keypoints, query_width, query_height)
        best, candidates, accepted, reason, margin = self._evaluate(scored)

        # 先便宜后兜底：粗筛不可靠时先用短名单的精确结果判断，只有结果不够决定性
        # 时才补扫剩余模板。低纹理展品仍然正确，又不必每次不确定都全量扫描。
        if (
            proposal is not None
            and proposal.full_scan
            and proposal.indices
            and not full_scan_used
            and not self._decisive(best, accepted)
        ):
            scanned = set(scan_indices)
            remainder = [index for index in self._scan_indices if index not in scanned]
            scored.extend(self._scan(remainder, query_des, keypoints, query_width, query_height))
            full_scan_used = True
            scan_indices = list(self._scan_indices)
            best, candidates, accepted, reason, margin = self._evaluate(scored)

        return MatchResult(
            best=best,
            candidates=candidates,
            accepted=accepted,
            unknown_reason=reason,
            diagnostics=self._diagnostics(
                query_features=query_count,
                scanned_templates=len(scan_indices),
                full_scan_used=full_scan_used,
                prefilter_ms=prefilter_ms,
                prefilter_reason=prefilter_reason,
                margin=margin,
                started=started,
            ),
        )

    def _ratio_matches(self, query_des: np.ndarray, template_des: np.ndarray) -> List:
        good = []
        try:
            pairs = self._bf.knnMatch(query_des, template_des, k=2)
        except Exception:
            return good
        for pair in pairs:
            if len(pair) == 2 and pair[0].distance < self.ratio * pair[1].distance:
                good.append(pair[0])
        return good

    def _rejection_reason(self, best: MatchCandidate, margin: float) -> Optional[str]:
        if best.inliers < self.min_inliers:
            return "below_threshold"
        if best.inlier_ratio < self.min_inlier_ratio:
            return "below_threshold"
        if best.confidence < self.min_confidence:
            return "below_threshold"
        if not best.geometry_valid:
            return "invalid_geometry"
        if margin < self.min_margin:
            return "ambiguous"
        return None

    def _homography_valid(
        self,
        homography: Optional[np.ndarray],
        template_width: int,
        template_height: int,
        query_width: int,
        query_height: int,
    ) -> bool:
        if homography is None or homography.shape != (3, 3):
            return False
        if not np.all(np.isfinite(homography)):
            return False
        determinant = float(np.linalg.det(homography))
        if not math.isfinite(determinant) or abs(determinant) < 1e-12:
            return False
        corners = np.float32(
            [[0, 0], [template_width, 0], [template_width, template_height], [0, template_height]]
        ).reshape(-1, 1, 2)
        try:
            projected = self._cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        except self._cv2.error:
            return False
        if not np.all(np.isfinite(projected)):
            return False
        if float(np.max(np.abs(projected))) > 1e6:
            return False
        area = abs(float(self._cv2.contourArea(projected.astype(np.float32))))
        query_area = float(query_width * query_height)
        if query_area <= 0:
            return False
        area_ratio = area / query_area
        # A partially visible template can project its far corners well outside
        # the frame, so only reject a collapsed quad; the inlier/confidence
        # checks already guard against spurious matches.
        return area_ratio >= 0.002


__all__ = ["ExhibitMatcher", "TemplateLibrary"]