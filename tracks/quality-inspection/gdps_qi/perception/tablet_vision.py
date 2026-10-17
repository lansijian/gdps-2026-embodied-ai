from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.perception.detection_types import Detection


@dataclass
class TabletVisionConfig:
    min_disk_radius_px: int = 8
    max_disk_radius_px: int = 80
    min_image_variance: float = 15.0
    min_detections: int = 1


def _image_variance(rgb: np.ndarray) -> float:
    gray = rgb.mean(axis=2) if rgb.ndim == 3 else rgb.astype(float)
    return float(np.var(gray))


def _find_disks(rgb: np.ndarray, cfg: TabletVisionConfig) -> List[Tuple[float, float, float, int]]:
    """Return list of (u, v, radius_px, circularity_score). Uses OpenCV if present."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return _find_disks_numpy(rgb, cfg)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=30,
        param1=80,
        param2=28,
        minRadius=cfg.min_disk_radius_px,
        maxRadius=cfg.max_disk_radius_px,
    )
    out: List[Tuple[float, float, float, int]] = []
    if circles is None:
        return out
    for c in circles[0]:
        u, v, r = float(c[0]), float(c[1]), float(c[2])
        out.append((u, v, r, 90))
    return out


def _find_disks_numpy(rgb: np.ndarray, cfg: TabletVisionConfig) -> List[Tuple[float, float, float, int]]:
    gray = rgb.mean(axis=2)
    thresh = gray > (gray.mean() + 0.25 * gray.std())
    ys, xs = np.where(thresh)
    if xs.size < 20:
        return []
    u = float(xs.mean())
    v = float(ys.mean())
    r = float(max(np.sqrt(xs.size / np.pi), cfg.min_disk_radius_px))
    return [(u, v, r, 50)]


def _ocr_label_stub(roi: np.ndarray) -> Optional[str]:
    """Placeholder for field OCR; returns None when pytesseract unavailable."""
    try:
        import pytesseract  # type: ignore
        import cv2  # type: ignore

        text = pytesseract.image_to_string(roi, config="--psm 7 digits").strip()
        m = re.search(r"\d{2}", text)
        return m.group(0) if m else None
    except Exception:
        return None


def detect_tablets_in_rgb(
    rgb: np.ndarray,
    cfg: Optional[TabletVisionConfig] = None,
    slot_hints: Optional[List[str]] = None,
) -> Tuple[List[Detection], str]:
    cfg = cfg or TabletVisionConfig()
    if rgb is None or rgb.size == 0:
        return [], "empty_image"
    if _image_variance(rgb) < cfg.min_image_variance:
        return [], "low_variance_reject_blank_frame"
    disks = _find_disks(rgb, cfg)
    if not disks:
        disks = _find_disks_numpy(rgb, cfg)
    if not disks:
        return [], "no_disk_candidates"
    detections: List[Detection] = []
    h, w = rgb.shape[:2]
    for idx, (u, v, r, score) in enumerate(sorted(disks, key=lambda d: d[0])):
        label = None
        if slot_hints and idx < len(slot_hints):
            label = slot_hints[idx]
        x0 = max(0, int(u - r))
        y0 = max(0, int(v - r))
        x1 = min(w, int(u + r))
        y1 = min(h, int(v + r))
        roi = rgb[y0:y1, x0:x1]
        if label is None and roi.size > 0:
            label = _ocr_label_stub(roi)
        if label is None:
            label = f"UNREAD_{idx+1:02d}"
        conf = min(0.99, 0.45 + score / 200.0)
        if label.startswith("UNREAD"):
            conf = 0.35
        detections.append(
            Detection(
                object_id=f"tablet_{label}",
                label=label,
                confidence=conf,
                bbox_xywh=(x0, y0, x1 - x0, y1 - y0),
                center_uv=(u, v),
            )
        )
    if len(detections) < cfg.min_detections:
        return detections, "insufficient_detections"
    return detections, "ok"
