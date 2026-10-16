#!/usr/bin/env python3
"""Offline dry-run: obstacle stop / cruise / watchdog without ROS 2."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.navigation.factory import build_navigator
from shared.navigation.perception.obstacle_monitor import ScanFrame


def scan(distance: float) -> ScanFrame:
    n = 21
    ranges = [8.0] * n
    ranges[n // 2] = distance
    return ScanFrame(
        ranges=tuple(ranges),
        angle_min=-0.5,
        angle_increment=0.05,
        frame_id="mock",
    )


def main() -> int:
    nav = build_navigator()
    try:
        nav.start()
        nav.on_scan(scan(8.0))
        clear = nav.step()
        nav.on_scan(scan(0.2))
        stop = nav.step()
        print(f"mode={nav.adapter.mode.value}")
        print(f"clear_cmd vx={clear.vx:.3f} wz={clear.wz:.3f} source={clear.source}")
        print(f"stop_cmd  vx={stop.vx:.3f} wz={stop.wz:.3f} source={stop.source}")
        print(f"backend_history_len={len(getattr(nav.adapter.backend, 'history', []))}")
        print("dry-run: mock backend received no live SetVelocity" if not getattr(nav.adapter.backend, "history", []) else "UNEXPECTED live history")
        return 0 if stop.is_zero() and clear.vx > 0 else 1
    finally:
        nav.adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
