from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np


def decode_sensor_image(msg: Any) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
    """Decode sensor_msgs/Image to RGB uint8 HxWx3 and optional depth float32."""
    if not hasattr(msg, "data") or not hasattr(msg, "encoding"):
        return None, None, "not_image_msg"
    h, w = int(msg.height), int(msg.width)
    enc = str(msg.encoding).lower()
    buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    if enc in ("rgb8",):
        rgb = buf.reshape(h, w, 3)
        return rgb, None, "rgb8"
    if enc in ("bgr8",):
        bgr = buf.reshape(h, w, 3)
        rgb = bgr[:, :, ::-1].copy()
        return rgb, None, "bgr8"
    if enc in ("mono8",):
        gray = buf.reshape(h, w)
        rgb = np.stack([gray, gray, gray], axis=2)
        return rgb, None, "mono8"
    if enc in ("16uc1", "mono16"):
        raw = np.frombuffer(bytes(msg.data), dtype=np.uint16).reshape(h, w)
        depth_m = raw.astype(np.float32) * 0.001
        return None, depth_m, enc
    if enc in ("32fc1",):
        depth_m = np.frombuffer(bytes(msg.data), dtype=np.float32).reshape(h, w)
        return None, depth_m, "32fc1"
    return None, None, f"unsupported_encoding:{enc}"
