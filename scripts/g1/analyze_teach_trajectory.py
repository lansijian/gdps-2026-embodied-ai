#!/usr/bin/env python3
"""Offline JSONL quality gate and Kalman observation export. No SDK or replay."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.robot_control.g1.teach_trajectory import (
    InvalidTeachingData, load_teaching_session, smooth_observed_angles, summarize_session,
)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('--out', required=True)
    args = p.parse_args(argv)
    source, output = Path(args.input).resolve(), Path(args.out).resolve()
    if output.exists():
        p.error('refusing to overwrite evidence')
    try:
        samples = load_teaching_session(source)
        result = summarize_session(samples)
        angles = smooth_observed_angles(samples)
        result['estimated_arm_q'] = [dict(timestamp_s=s.timestamp_s, q=q) for s,q in zip(samples,angles)]
        result['filter'] = 'causal_scalar_Kalman_process_variance_per_second'
        result['max_raw_to_estimate_rad'] = max(abs(a-b) for s,q in zip(samples,angles) for a,b in zip(s.q,q))
        code = 0
    except (OSError, InvalidTeachingData) as exc:
        result = dict(status='REJECTED', reason=str(exc), motor_write_allowed=False, replay_authorized=False)
        code = 1
    result['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(result['status'])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
