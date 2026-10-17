#!/usr/bin/env python3
"""Bounded native LowState subscription only. Never enables teaching or free drive."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from shared.robot_control.g1.teach_trajectory import ARM_IDS, WAIST_IDS, finite_number, parse_observation


def observe(msg, now, monotonic=None):
    """Wall/monotonic times are receipt times; native tick has no assumed scale."""
    row = dict(record_type='arm_observation', source='rt/lowstate', data_source='REAL_SENSOR',
               timestamp_s=finite_number(now),
               received_monotonic_s=finite_number(time.monotonic() if monotonic is None else monotonic),
               mode_machine=msg.mode_machine, tick=msg.tick, joints=list(ARM_IDS),
               waist={str(j): {k: finite_number(getattr(msg.motor_state[j],k))
                              for k in ('q','dq','tau_est')} for j in WAIST_IDS},
               imu_rpy=[finite_number(x) for x in msg.imu_state.rpy],
               timestamp_basis='host_receipt_unix_and_monotonic; native_tick_not_seconds',
               motor_write_allowed=False, field_verified=False)
    for k in ('q','dq','tau_est'):
        row[k] = [finite_number(getattr(msg.motor_state[j],k)) for j in ARM_IDS]
    if len(row['imu_rpy']) != 3:
        raise ValueError('invalid_imu')
    parse_observation(row)
    return row


class ObservationBuffer:
    """Keep one sample, reject repeated/backward counter and unhealthy callbacks."""
    def __init__(self):
        self.lock = Lock()
        self.record = None
        self.last_tick = None
        self.counts = dict(received=0, invalid=0, nonadvancing_tick=0, stale=0, saved=0)
        self.last_error = ''

    def ingest(self, msg, now=None, monotonic=None):
        with self.lock:
            self.counts['received'] += 1
            try:
                row = observe(msg, time.time() if now is None else now, monotonic)
                if self.last_tick is not None and row['tick'] <= self.last_tick:
                    self.counts['nonadvancing_tick'] += 1
                    self.record = None
                    self.last_error = 'nonadvancing_tick_restart_session_after_reset_or_wrap'
                    return
                self.last_tick = row['tick']
                self.record = row
            except (ValueError, TypeError, AttributeError, IndexError, OverflowError) as exc:
                self.record = None
                self.counts['invalid'] += 1
                self.last_error = type(exc).__name__ + ':' + str(exc)

    def take(self, now):
        with self.lock:
            row, self.record = self.record, None
            if row is not None and not 0 <= now-row['received_monotonic_s'] <= .25:
                self.counts['stale'] += 1
                return None
            return row


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--iface', default='eth0')
    p.add_argument('--seconds', type=float, default=10.)
    p.add_argument('--hz', type=float, default=20.)
    p.add_argument('--out', required=True)
    args = p.parse_args(argv)
    if not (0 < args.seconds <= 120 and 0 < args.hz <= 50) or not args.iface.strip():
        p.error('seconds in (0,120], Hz in (0,50], verified iface required')
    path = Path(args.out).expanduser().resolve()
    report = path.with_suffix(path.suffix + '.report.json')
    if path.exists() or report.exists():
        p.error('refusing to overwrite existing evidence')
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = ObservationBuffer()
    subscriber = None
    error = ''
    interrupted = False
    try:
        # No SDK import at module import; Windows analysis requires no DDS.
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
        ChannelFactoryInitialize(0, args.iface)
        subscriber = ChannelSubscriber('rt/lowstate', LowState_)
        subscriber.Init(holder.ingest, 10)
        started = time.monotonic()
        with path.open('x', encoding='utf-8') as stream:
            while time.monotonic()-started < args.seconds:
                row = holder.take(time.monotonic())
                if row is not None:
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
                    stream.flush()
                    holder.counts['saved'] += 1
                time.sleep(1/args.hz)
    except KeyboardInterrupt:
        interrupted = True
    except Exception as exc:
        error = type(exc).__name__+':'+str(exc)
    finally:
        if subscriber is not None:
            try:
                subscriber.Close()
            except Exception as exc:
                error += ';close:'+str(exc)
        with holder.lock:
            counts = dict(holder.counts)
            last_error = holder.last_error
        healthy = counts['saved'] and not error and not counts['invalid'] and not counts['nonadvancing_tick']
        status = dict(status='READ_ONLY_CAPTURE' if healthy else 'DEGRADED' if counts['saved'] else 'UNKNOWN',
                      data_source='REAL_SENSOR', data_present=bool(counts['saved']),
                      counts=counts, error=error, last_callback_error=last_error,
                      interrupted=interrupted, motor_write_allowed=False, field_verified=False,
                      iface=args.iface, domain_id=0, requested_hz=args.hz, seconds=args.seconds)
        with report.open('x', encoding='utf-8') as stream:
            json.dump(status, stream, ensure_ascii=False, indent=2)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if counts['saved'] and not error and not counts['invalid'] and not counts['nonadvancing_tick'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
