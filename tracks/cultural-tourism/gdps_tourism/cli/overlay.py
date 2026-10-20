"""Frame overlays shared by the live and offline CLIs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .._cv2 import require_cv2
from ..matching.types import MatchCandidate, MatchResult, StableMatch

_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Ubuntu 20.04 / Unitree G1 (apt install fonts-noto-cjk / fonts-wqy-microhei)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)


class ChineseTextRenderer:
    """Render CJK names with Pillow and cache each text strip.

    ``cv2.putText`` cannot render Chinese, so the HUD keeps ASCII metrics and
    draws the exhibit name through this renderer.
    """

    def __init__(self, font_size: int = 26) -> None:
        self._font = None
        self._cache = {}
        try:
            from PIL import ImageFont
        except ImportError:  # pragma: no cover - Pillow is present in dev envs
            return
        for candidate in _FONT_CANDIDATES:
            if not Path(candidate).is_file():
                continue
            try:
                self._font = ImageFont.truetype(candidate, font_size)
                break
            except OSError:
                continue

    @property
    def available(self) -> bool:
        return self._font is not None

    def draw(
        self,
        frame: np.ndarray,
        text: Optional[str],
        x: int,
        y: int,
        color: Tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        if not text or self._font is None:
            return
        key = (text, tuple(color))
        strip = self._cache.get(key)
        if strip is None:
            from PIL import Image, ImageDraw

            bbox = self._font.getbbox(text)
            width = max(1, bbox[2] - bbox[0] + 8)
            height = max(1, bbox[3] - bbox[1] + 8)
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            drawer = ImageDraw.Draw(image)
            rgb = (int(color[2]), int(color[1]), int(color[0]), 255)
            drawer.text((4 - bbox[0], 4 - bbox[1]), text, font=self._font, fill=rgb)
            arr = np.array(image)
            bgr = arr[:, :, :3][:, :, ::-1].copy()
            alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
            strip = (bgr, alpha)
            self._cache[key] = strip

        bgr, alpha = strip
        height, width = bgr.shape[:2]
        y0, y1 = max(0, y), min(frame.shape[0], y + height)
        x0, x1 = max(0, x), min(frame.shape[1], x + width)
        if y1 <= y0 or x1 <= x0:
            return
        strip_bgr = bgr[y0 - y:y1 - y, x0 - x:x1 - x]
        strip_alpha = alpha[y0 - y:y1 - y, x0 - x:x1 - x]
        region = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (
            region * (1.0 - strip_alpha) + strip_bgr.astype(np.float32) * strip_alpha
        ).astype(np.uint8)


def draw_hud(
    frame: np.ndarray,
    stable: Optional[StableMatch],
    result: Optional[MatchResult],
    renderer: ChineseTextRenderer,
    progress_text: Optional[str] = None,
    top_n: int = 3,
) -> np.ndarray:
    cv2 = require_cv2()
    height, width = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (width, 132), (0, 0, 0), -1)

    if stable is not None and stable.template_id is not None:
        cv2.putText(
            frame,
            "STABLE  #%02d  conf=%.2f" % ((stable.template_index or 0) + 1, stable.confidence),
            (12, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    else:
        cv2.putText(
            frame,
            "STABLE  ---",
            (12, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    if result is not None and result.best is not None:
        best = result.best
        color = (255, 255, 255) if result.accepted else (0, 165, 255)
        margin = 0.0
        if result.diagnostics:
            margin = float(result.diagnostics.get("margin", 0.0))
        cv2.putText(
            frame,
            "RAW #%02d conf=%.2f inl=%d ratio=%.2f margin=%.2f"
            % (best.info.index + 1, best.confidence, best.inliers, best.inlier_ratio, margin),
            (12, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
            cv2.LINE_AA,
        )
        for rank, candidate in enumerate(result.candidates[:top_n]):
            cv2.putText(
                frame,
                "  %d. #%02d  inl=%d  r=%.2f  conf=%.2f"
                % (
                    rank + 1,
                    candidate.info.index + 1,
                    candidate.inliers,
                    candidate.inlier_ratio,
                    candidate.confidence,
                ),
                (12, 82 + rank * 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (205, 205, 205),
                1,
                cv2.LINE_AA,
            )
        name = stable.display_name if stable is not None and stable.display_name else best.display_name
        renderer.draw(frame, name, 12, 142)
    elif stable is not None and stable.display_name:
        renderer.draw(frame, stable.display_name, 12, 142)

    if progress_text:
        cv2.putText(
            frame,
            progress_text,
            (12, height - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return frame


def draw_homography_quad(frame: np.ndarray, candidate: Optional[MatchCandidate]) -> None:
    if candidate is None or candidate.homography is None or not candidate.geometry_valid:
        return
    cv2 = require_cv2()
    width = candidate.info.width
    height = candidate.info.height
    corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
    try:
        projected = cv2.perspectiveTransform(corners, candidate.homography).reshape(-1, 2)
    except cv2.error:
        return
    if not np.all(np.isfinite(projected)) or float(np.max(np.abs(projected))) > 10000:
        return
    cv2.polylines(frame, [projected.astype(np.int32)], True, (0, 255, 0), 3, cv2.LINE_AA)


__all__ = ["ChineseTextRenderer", "draw_hud", "draw_homography_quad"]
