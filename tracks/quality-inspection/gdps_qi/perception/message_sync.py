from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple


@dataclass
class SyncPolicy:
    """Foxy ApproximateTimeSynchronizer queue/slop (seconds)."""

    queue_size: int = 8
    slop_s: float = 0.05


def foxy_message_filters_note() -> str:
    """On-robot ROS 2 Foxy: message_filters.ApproximateTimeSynchronizer.

    API (foxy): ApproximateTimeSynchronizer(fs, queue_size, slop)
    https://github.com/ros2/message_filters/blob/foxy/src/message_filters/__init__.py
    """
    try:
        import message_filters  # type: ignore

        return "REUSE:message_filters.ApproximateTimeSynchronizer:" + str(getattr(message_filters, "__file__", "pkg"))
    except ImportError:
        return "UNSUPPORTED_on_this_host:message_filters_not_installed"


def try_create_rgbd_synchronizer(
    rgb_sub: Any,
    depth_sub: Any,
    info_sub: Any,
    callback: Callable[..., None],
    policy: Optional[SyncPolicy] = None,
) -> Tuple[Optional[Any], str]:
    policy = policy or SyncPolicy()
    try:
        import message_filters  # type: ignore
    except ImportError:
        return None, "message_filters_unavailable"
    try:
        sync = message_filters.ApproximateTimeSynchronizer(
            [rgb_sub, depth_sub, info_sub],
            policy.queue_size,
            policy.slop_s,
        )
        sync.registerCallback(callback)
        return sync, "ok"
    except Exception as exc:
        return None, str(exc)
