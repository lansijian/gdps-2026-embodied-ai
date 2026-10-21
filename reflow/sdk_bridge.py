#!/usr/bin/env python3
"""G1 实机具身数据桥：unitree_sdk2py → 导览事件 JSONL（只读，不发任何控制指令）。

订阅：
  rt/lowstate      unitree_hg/LowState      关节 q/dq/tau、IMU
  rt/lf/bmsstate   unitree_hg/BmsState      电量 soc（百分比）

产出事件（供 reflow/agent.py 合并上报）：
  {"type": "embodied_sample", "sample_seq", "timestamp", "mode",
   "joint_positions", "joint_velocities", "joint_efforts", "battery_pct",
   "sensors": {...}, "joint_names": [...]}

安全：本脚本只创建 ChannelSubscriber，不创建任何 Publisher，不会让机器人运动。

用法（机器人上，需先确认 eth0 是 DDS 网口）：
  python3 reflow/sdk_bridge.py --duration 15 --out logs/robot.events.jsonl
  python3 reflow/sdk_bridge.py --embodied-hz 5 --mode autonomous     # 正式场次
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TZ = timezone(timedelta(hours=8))


def iso_now() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def die(msg: str, code: int = 2) -> None:
    print("[FAIL] " + str(msg), file=sys.stderr)
    raise SystemExit(code)


def scalar(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return float(value[0]) if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Latest:
    """线程安全地保存最新一条消息。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._msg = None
        self._ts = 0.0
        self.count = 0

    def set(self, msg: Any) -> None:
        with self._lock:
            self._msg = msg
            self._ts = time.time()
            self.count += 1

    def get(self):
        with self._lock:
            return self._msg, self._ts


class EventWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.handle = path.open("w", encoding="utf-8", buffering=1)
        self.seq = 0
        self.count = 0

    def emit(self, event_type: str, **fields: Any) -> None:
        self.seq += 1
        record = {
            "schema_version": "1.0",
            "seq": self.seq,
            "ts": iso_now(),
            "type": event_type,
        }
        record.update(fields)
        try:
            self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.count += 1
        except Exception as exc:  # pragma: no cover
            print("[events] 写入失败：%r" % (exc,), file=sys.stderr, flush=True)

    def close(self) -> None:
        try:
            self.handle.close()
        except Exception:
            pass


def generic_joint_names(count: int, override: Optional[List[str]] = None) -> List[str]:
    if override:
        if len(override) != count:
            die("--joint-names 数量 %d 与电机数 %d 不一致" % (len(override), count))
        return list(override)
    # LowState.motor_state 的顺序即真机关节顺序；名称仅用于对齐，不改变语义
    return ["motor_%02d" % i for i in range(count)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="G1 具身数据桥（只读订阅）")
    parser.add_argument("--out", default="logs/robot.events.jsonl")
    parser.add_argument("--interface", default="eth0", help="DDS 网口（G1 默认 eth0）")
    parser.add_argument("--duration", type=float, default=0.0, help="运行秒数，0=直到 Ctrl+C")
    parser.add_argument("--embodied-hz", type=float, default=5.0, help="具身采样写事件频率（默认 5Hz）")
    parser.add_argument("--mode", default="unknown", choices=("autonomous", "teleoperation", "assisted", "unknown"))
    parser.add_argument("--joint-names", default="", help="逗号分隔的关节名（默认 motor_00..）")
    parser.add_argument("--max-samples", type=int, default=0, help="最多写多少条样本（0=不限）")
    parser.add_argument("--robot-note", default="", help="写入事件文件的备注字段")
    args = parser.parse_args(argv)

    if args.embodied_hz <= 0:
        die("--embodied-hz 必须 > 0")
    override = [n.strip() for n in args.joint_names.split(",") if n.strip()] if args.joint_names else None

    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_, BmsState_
    except Exception as exc:
        die("unitree_sdk2py 不可用：%r（需在机器人上运行并安装 SDK）" % (exc,))

    ChannelFactoryInitialize(0, args.interface)
    low = Latest()
    bms = Latest()
    low_sub = ChannelSubscriber("rt/lowstate", LowState_)
    low_sub.Init(low.set, 10)
    bms_sub = ChannelSubscriber("rt/lf/bmsstate", BmsState_)
    bms_sub.Init(bms.set, 10)

    # 等首帧 lowstate（最多 5s）
    t0 = time.time()
    while low.get()[0] is None and time.time() - t0 < 5.0:
        time.sleep(0.05)
    if low.get()[0] is None:
        die("5s 内未收到 rt/lowstate：检查网口（--interface）与 DDS 配置")

    names: List[str] = []
    writer = EventWriter(Path(args.out))
    stop = threading.Event()

    def _on_signal(signum, frame):  # pragma: no cover
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    started = time.time()
    next_at = started
    interval = 1.0 / args.embodied_hz
    written = 0
    missing_since: Optional[float] = None

    try:
        while not stop.is_set():
            now = time.time()
            if args.duration and now - started >= args.duration:
                break
            if args.max_samples and written >= args.max_samples:
                break
            if now < next_at:
                time.sleep(min(0.05, next_at - now))
                continue
            next_at = now + interval

            msg, msg_ts = low.get()
            if msg is None:
                continue
            if now - msg_ts > 2.0:
                if missing_since is None:
                    missing_since = now
                if now - missing_since > 3.0:
                    print("[warn] lowstate 已中断 >3s", file=sys.stderr, flush=True)
                    missing_since = now
            else:
                missing_since = None

            motors = list(msg.motor_state)
            if not names:
                names = generic_joint_names(len(motors), override)
            q = [round(scalar(m.q) or 0.0, 5) for m in motors]
            dq = [round(scalar(m.dq) or 0.0, 5) for m in motors]
            tau = [round(scalar(m.tau_est) or 0.0, 5) for m in motors]

            imu = msg.imu_state
            sensors: Dict[str, Any] = {
                "imu_rpy": [round(scalar(v) or 0.0, 4) for v in imu.rpy],
                "imu_gyro": [round(scalar(v) or 0.0, 4) for v in imu.gyroscope],
                "imu_acc": [round(scalar(v) or 0.0, 4) for v in imu.accelerometer],
                "motor_temp_max_c": round(max((scalar(m.temperature) or 0.0) for m in motors), 1),
                "motor_vol_min_v": round(min((scalar(m.vol) or 0.0) for m in motors), 2),
            }
            bms_msg, _ = bms.get()
            soc = scalar(getattr(bms_msg, "soc", None)) if bms_msg is not None else None
            if soc is not None:
                sensors["battery_soc_raw"] = soc

            writer.emit(
                "embodied_sample",
                sample_seq=written,
                timestamp=iso_now(),
                mode=args.mode,
                joint_positions=q,
                joint_velocities=dq,
                joint_efforts=tau,
                battery_pct=round(soc, 2) if soc is not None else None,
                sensors=sensors,
                joint_names=names,
            )
            written += 1
    finally:
        writer.close()

    elapsed = max(1e-6, time.time() - started)
    print(
        "[done] samples=%d duration=%.1fs rate=%.2fHz lowstate=%d bms=%d out=%s"
        % (written, elapsed, written / elapsed, low.count, bms.count, writer.path),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
