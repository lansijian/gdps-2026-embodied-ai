from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import numpy as np


@dataclass
class ImageDecodeResult:
    rgb: Optional[np.ndarray]
    depth_m: Optional[np.ndarray]
    encoding: str
    ok: bool
    message: str
    width: int = 0
    height: int = 0
    step: int = 0
    is_bigendian: bool = False
    frame_id: str = ""
    stamp_sec: Optional[float] = None
    depth_scale_confirmed: bool = False


def _header_fields(msg: Any) -> Tuple[str, Optional[float]]:
    header = getattr(msg, "header", None)
    if header is None:
        return "", None
    frame_id = str(getattr(header, "frame_id", "") or "")
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return frame_id, None
    sec = getattr(stamp, "sec", None)
    nsec = getattr(stamp, "nanosec", 0)
    if sec is None:
        return frame_id, None
    return frame_id, float(sec) + float(nsec) * 1e-9


def _reshape_with_step(
    raw: np.ndarray, height: int, width: int, step: int, channels: int, dtype: np.dtype
) -> Tuple[Optional[np.ndarray], str]:
    elem = np.dtype(dtype).itemsize
    row_bytes = width * channels * elem
    if step <= 0:
        step = row_bytes
    if step < row_bytes:
        return None, "step_smaller_than_row"
    total_bytes = step * height
    if raw.nbytes < total_bytes:
        return None, "buffer_too_small"
    flat = raw.ravel()
    if step == row_bytes:
        need_elems = height * width * channels
        return flat[:need_elems].reshape(height, width, channels) if channels > 1 else flat[: height * width].reshape(height, width), "ok"
    elems_per_row = step // elem
    padded = flat[: (total_bytes // elem)].reshape(height, elems_per_row)
    slim = padded[:, : (row_bytes // elem)]
    if channels > 1:
        return slim.reshape(height, width, channels), "ok"
    return slim.reshape(height, width), "ok"


def decode_sensor_image(
    msg: Any,
    depth_scale_m: Optional[float] = None,
    allow_16uc1_depth: bool = False,
    treat_mono16_as_depth: bool = False,
) -> ImageDecodeResult:
    """Decode sensor_msgs/Image. Depth requires explicit depth_scale_m (meters per raw unit)."""
    if not hasattr(msg, "data") or not hasattr(msg, "encoding"):
        return ImageDecodeResult(None, None, "", False, "not_image_msg")
    h, w = int(msg.height), int(msg.width)
    enc = str(msg.encoding)
    enc_l = enc.lower()
    step = int(getattr(msg, "step", 0) or 0)
    big = bool(getattr(msg, "is_bigendian", False))
    frame_id, stamp_sec = _header_fields(msg)
    buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)

    if enc_l in ("rgb8",):
        raw, err = _reshape_with_step(buf, h, w, step, 3, np.uint8)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        return ImageDecodeResult(raw, None, enc, True, "rgb8", w, h, step, big, frame_id, stamp_sec)

    if enc_l in ("bgr8",):
        raw, err = _reshape_with_step(buf, h, w, step, 3, np.uint8)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        rgb = raw[:, :, ::-1].copy()
        return ImageDecodeResult(rgb, None, enc, True, "bgr8", w, h, step, big, frame_id, stamp_sec)

    if enc_l in ("mono8",):
        raw, err = _reshape_with_step(buf, h, w, step, 1, np.uint8)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        rgb = np.stack([raw, raw, raw], axis=2)
        return ImageDecodeResult(rgb, None, enc, True, "mono8", w, h, step, big, frame_id, stamp_sec)

    if enc_l == "mono16":
        dtype = np.dtype(np.uint16)
        if big:
            dtype = dtype.newbyteorder(">")
        else:
            dtype = dtype.newbyteorder("<")
        raw16 = np.frombuffer(bytes(msg.data), dtype=dtype)
        raw, err = _reshape_with_step(raw16, h, w, step, 1, dtype)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        if not treat_mono16_as_depth:
            return ImageDecodeResult(
                None,
                None,
                enc,
                False,
                "mono16_not_depth_without_config",
                w,
                h,
                step,
                big,
                frame_id,
                stamp_sec,
            )
        if depth_scale_m is None:
            return ImageDecodeResult(
                None,
                None,
                enc,
                False,
                "depth_scale_unknown",
                w,
                h,
                step,
                big,
                frame_id,
                stamp_sec,
            )
        depth_m = raw.astype(np.float32) * float(depth_scale_m)
        return ImageDecodeResult(
            None,
            depth_m,
            enc,
            True,
            "mono16_depth",
            w,
            h,
            step,
            big,
            frame_id,
            stamp_sec,
            depth_scale_confirmed=True,
        )

    if enc_l == "16uc1":
        if not allow_16uc1_depth:
            return ImageDecodeResult(
                None,
                None,
                enc,
                False,
                "16uc1_depth_disabled_in_config",
                w,
                h,
                step,
                big,
                frame_id,
                stamp_sec,
            )
        dtype = np.dtype(np.uint16)
        if big:
            dtype = dtype.newbyteorder(">")
        else:
            dtype = dtype.newbyteorder("<")
        raw16 = np.frombuffer(bytes(msg.data), dtype=dtype)
        raw, err = _reshape_with_step(raw16, h, w, step, 1, dtype)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        if depth_scale_m is None:
            return ImageDecodeResult(
                None,
                None,
                enc,
                False,
                "depth_scale_unknown",
                w,
                h,
                step,
                big,
                frame_id,
                stamp_sec,
            )
        depth_m = raw.astype(np.float32) * float(depth_scale_m)
        return ImageDecodeResult(
            None,
            depth_m,
            enc,
            True,
            "16uc1_depth",
            w,
            h,
            step,
            big,
            frame_id,
            stamp_sec,
            depth_scale_confirmed=True,
        )

    if enc_l == "32fc1":
        dtype = np.dtype(np.float32)
        if big:
            dtype = dtype.newbyteorder(">")
        else:
            dtype = dtype.newbyteorder("<")
        rawf = np.frombuffer(bytes(msg.data), dtype=dtype)
        raw, err = _reshape_with_step(rawf, h, w, step, 1, dtype)
        if raw is None:
            return ImageDecodeResult(None, None, enc, False, err, w, h, step, big, frame_id, stamp_sec)
        return ImageDecodeResult(
            None,
            raw.astype(np.float32),
            enc,
            True,
            "32fc1_depth",
            w,
            h,
            step,
            big,
            frame_id,
            stamp_sec,
            depth_scale_confirmed=True,
        )

    return ImageDecodeResult(None, None, enc, False, f"unsupported_encoding:{enc}", w, h, step, big, frame_id, stamp_sec)
