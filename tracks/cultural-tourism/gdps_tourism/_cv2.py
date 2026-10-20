"""Lazy OpenCV import shared by the tourism modules."""

from __future__ import annotations


class OpenCVUnavailableError(RuntimeError):
    """Raised when a module needs OpenCV but it is not installed."""


def require_cv2():
    """Return the ``cv2`` module or raise a clear, actionable error."""

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - exercised on minimal installs
        raise OpenCVUnavailableError(
            "OpenCV is required for exhibit target matching. "
            "Install it with `pip install opencv-python`."
        ) from exc
    return cv2
