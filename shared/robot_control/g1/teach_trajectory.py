"""Read-only observations and offline Kalman estimates; never motor trajectories.

Python 3.8, standard library only. No DDS imports, command output or replay API.
Quality thresholds are analysis settings, not certified mechanical limits.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

ARM_IDS = tuple(range(15, 29))
WAIST_IDS = (12, 13, 14)


class InvalidTeachingData(ValueError):
    pass


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise InvalidTeachingData('non_finite_or_non_numeric_value')
    return float(value)


@dataclass(frozen=True)
class ArmObservation:
    timestamp_s: float
    mode_machine: int
    q: Tuple[float, ...]
    dq: Tuple[float, ...]
    tau_est: Tuple[float, ...]
    # Older arm-only records remain analyzable, never qualify as full teaching.
    waist: tuple = ()  # ((q,dq,tau_est), ...) ordered 12,13,14
    received_monotonic_s: object = None
    tick: object = None  # native counter, NOT seconds or FSM
    data_source: str = 'UNKNOWN'


def parse_observation(record):
    try:
        if record['source'] != 'rt/lowstate' or record['record_type'] != 'arm_observation':
            raise InvalidTeachingData('untrusted_record_source')
        if record['joints'] != list(ARM_IDS) or any(type(j) is not int for j in record['joints']):
            raise InvalidTeachingData('g1_29_arm_joint_map_mismatch')
        vectors = [tuple(finite_number(x) for x in record[key]) for key in ('q','dq','tau_est')]
        if any(len(v) != len(ARM_IDS) for v in vectors):
            raise InvalidTeachingData('invalid_joint_count')
        stamp = finite_number(record['timestamp_s'])
        if stamp <= 0:
            raise InvalidTeachingData('invalid_timestamp')
        mode = record['mode_machine']
        if type(mode) is not int or mode != 5:
            raise InvalidTeachingData('unverified_robot_variant')
        waist = ()
        if 'waist' in record:
            if set(record['waist']) != set(map(str, WAIST_IDS)):
                raise InvalidTeachingData('waist_joint_map_mismatch')
            waist = tuple(tuple(finite_number(record['waist'][str(j)][key])
                                for key in ('q','dq','tau_est')) for j in WAIST_IDS)
        mono = record.get('received_monotonic_s')
        if mono is not None and finite_number(mono) < 0:
            raise InvalidTeachingData('invalid_monotonic_timestamp')
        tick = record.get('tick')
        if tick is not None and (type(tick) is not int or not 0 <= tick < 2**32):
            raise InvalidTeachingData('invalid_tick')
        source = record.get('data_source', 'UNKNOWN')
        if source not in ('UNKNOWN','REAL_SENSOR','RECORDED_REPLAY','SYNTHETIC_TEST'):
            raise InvalidTeachingData('invalid_data_source')
        return ArmObservation(stamp, mode, *vectors, waist, mono, tick, source)
    except (KeyError, TypeError, OverflowError, ValueError) as exc:
        if isinstance(exc, InvalidTeachingData):
            raise
        raise InvalidTeachingData('invalid_record') from exc


def validate_session(samples, max_gap_s=.25, max_step_rad=.5, joint_limits=None,
                     max_waist_step_rad=.15):
    """Reject bad data before filtering; never smooth away a discontinuity.

    Optional joint_limits maps all 17 IDs to verified (min,max) radians. Without
    it mechanical limits remain UNKNOWN. Mode_machine=5 is identity, not authority.
    """
    for threshold in (max_gap_s, max_step_rad, max_waist_step_rad):
        if finite_number(threshold) <= 0:
            raise InvalidTeachingData('invalid_quality_threshold')
    if len(samples) < 3:
        raise InvalidTeachingData('too_few_samples')
    if joint_limits is not None:
        if set(joint_limits) != set(ARM_IDS + WAIST_IDS):
            raise InvalidTeachingData('incomplete_joint_limits')
        for lo, hi in joint_limits.values():
            if finite_number(lo) >= finite_number(hi):
                raise InvalidTeachingData('invalid_joint_limits')
    for i, sample in enumerate(samples):
        if (type(sample.mode_machine) is not int or sample.mode_machine != 5
                or finite_number(sample.timestamp_s) <= 0):
            raise InvalidTeachingData('invalid_sample_identity_or_time')
        if sample.data_source not in ('UNKNOWN','REAL_SENSOR','RECORDED_REPLAY','SYNTHETIC_TEST'):
            raise InvalidTeachingData('invalid_data_source')
        for vector in (sample.q, sample.dq, sample.tau_est):
            if len(vector) != 14:
                raise InvalidTeachingData('invalid_joint_count')
            for x in vector:
                finite_number(x)
        if sample.waist:
            if len(sample.waist) != 3 or any(len(v) != 3 for v in sample.waist):
                raise InvalidTeachingData('invalid_waist')
            for v in sample.waist:
                for x in v:
                    finite_number(x)
        if sample.received_monotonic_s is not None and finite_number(sample.received_monotonic_s) < 0:
            raise InvalidTeachingData('invalid_monotonic_timestamp')
        if sample.tick is not None and (type(sample.tick) is not int or not 0 <= sample.tick < 2**32):
            raise InvalidTeachingData('invalid_tick')
        if joint_limits is not None:
            if not sample.waist:
                raise InvalidTeachingData('waist_required_for_limits')
            for j, q in zip(ARM_IDS + WAIST_IDS, tuple(sample.q) + tuple(v[0] for v in sample.waist)):
                lo, hi = joint_limits[j]
                if not lo <= q <= hi:
                    raise InvalidTeachingData('joint_limit_exceeded:{}'.format(j))
        if not i:
            continue
        prev = samples[i-1]
        if (sample.mode_machine != prev.mode_machine or sample.data_source != prev.data_source
                or bool(sample.waist) != bool(prev.waist)):
            raise InvalidTeachingData('session_schema_or_source_changed')
        dt = sample.timestamp_s - prev.timestamp_s
        if not 0 < dt <= max_gap_s:
            raise InvalidTeachingData('non_monotonic_or_stale_joint_data')
        if (sample.received_monotonic_s is None) != (prev.received_monotonic_s is None):
            raise InvalidTeachingData('monotonic_clock_missing')
        if sample.received_monotonic_s is not None:
            dm = sample.received_monotonic_s - prev.received_monotonic_s
            if not 0 < dm <= max_gap_s or abs(dm-dt) > .05:
                raise InvalidTeachingData('clock_jump_or_stale_receipt')
        if (sample.tick is None) != (prev.tick is None):
            raise InvalidTeachingData('tick_missing')
        if sample.tick is not None and sample.tick <= prev.tick:
            raise InvalidTeachingData('duplicate_or_reversed_tick_split_session')
        if max(abs(a-b) for a,b in zip(sample.q,prev.q)) > max_step_rad:
            raise InvalidTeachingData('arm_angle_outlier')
        if sample.waist and max(abs(a[0]-b[0]) for a,b in zip(sample.waist,prev.waist)) > max_waist_step_rad:
            raise InvalidTeachingData('waist_angle_outlier')
    return samples


def load_teaching_session(path, **quality):
    samples = []
    with Path(path).open('r', encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    samples.append(parse_observation(json.loads(line)))
                except (ValueError, TypeError) as exc:
                    raise InvalidTeachingData('line {}: {}'.format(number, exc)) from exc
    return validate_session(samples, **quality)


def _kalman(samples, values, process_var, measure_var):
    estimate = list(values[0])
    covariance = [measure_var] * len(estimate)
    result = [tuple(estimate)]
    for i, row in enumerate(values[1:], 1):
        # Random-walk process variance per second; do not invent intermediate samples.
        dt = samples[i].timestamp_s - samples[i-1].timestamp_s
        for j, observed in enumerate(row):
            predicted = covariance[j] + process_var * dt
            gain = predicted / (predicted + measure_var)
            estimate[j] += gain * (observed-estimate[j])
            covariance[j] = (1-gain) * predicted
        result.append(tuple(estimate))
    return result


def smooth_observed_angles(samples, process_var=.0001, measure_var=.0009, **quality):
    """Causal scalar Kalman estimate of arm q only, not executable motion."""
    validate_session(samples, **quality)
    if not 0 < finite_number(process_var) < 1 or not 0 < finite_number(measure_var) < 1:
        raise InvalidTeachingData('invalid_filter_configuration')
    return _kalman(samples, [s.q for s in samples], process_var, measure_var)


def summarize_session(samples, **quality):
    validate_session(samples, **quality)
    complete = all(s.waist and s.received_monotonic_s is not None and s.tick is not None for s in samples)
    return dict(status='OFFLINE_OBSERVATION_ONLY', motor_write_allowed=False,
                samples=len(samples), duration_s=samples[-1].timestamp_s-samples[0].timestamp_s,
                arm_joint_ids=list(ARM_IDS), waist_joint_ids=list(WAIST_IDS),
                robot_variant=samples[0].mode_machine, data_source=samples[0].data_source,
                full_telemetry=complete, mechanical_limits='CHECKED' if quality.get('joint_limits') else 'UNKNOWN',
                urdf_fk='UNKNOWN', tcp='UNKNOWN', self_collision='UNKNOWN', simulation='NOT_RUN',
                replay_authorized=False, field_verified=False)
