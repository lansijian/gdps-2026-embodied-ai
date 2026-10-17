#!/usr/bin/env python3
"""Independent read-only gates over real ROS messages or derived rosbag2 evidence."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tracks/quality-inspection')]
from field_evidence import add_capture_arguments, capture_live, series_stats, odom_delta, target_pixel
from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.perception.rgbd_target_geometry import assess_rgbd_sync, estimate_target_range
from gdps_qi.perception.camera_geometry import choose_lateral_direction_by_reprojection


def load_frame(root, row):
    info = CameraInfo(**row['info']) if row.get('info') else None
    return CameraFrame(rgb=np.load(root / row['rgb_file'], allow_pickle=False),
        depth_m=np.load(root / row['depth_file'], allow_pickle=False) if row['depth_file'] else None,
        stamp=row['stamp'], info=info,
        **{k: row[k] for k in ('rgb_stamp_sec','depth_stamp_sec','camera_info_stamp_sec',
            'rgb_frame_id','depth_frame_id','intrinsics_trusted','depth_scale_confirmed','depth_aligned_to_rgb')})


def analyze(e, root, gate):
    source = e.get('data_source', 'SYNTHETIC_TEST')
    if source not in ('REAL_SENSOR', 'RECORDED_REPLAY', 'SYNTHETIC_TEST'):
        raise ValueError('invalid_data_source')
    out = {'gate': gate, 'data_source': source, 'field_verified': False,
           'status': 'UNKNOWN', 'errors': [], 'live_motion': False}
    rows = e.get('rows', {})
    if gate == 'A':
        frames = []
        for row in rows.get('frames', []):
            frame = load_frame(root, row)
            sync = assess_rgbd_sync(frame)
            frames.append({'stamp': row['stamp'], 'sync': sync.__dict__,
                'rgb_file': row['rgb_file'], 'depth_file': row['depth_file'],
                'finite_depth_fraction': float((np.isfinite(frame.depth_m) & (frame.depth_m > .05) & (frame.depth_m < 4)).mean()) if frame.depth_m is not None else None})
        out.update(frames=frames, statistics=series_stats(rows.get('frames', [])),
                   discovery=e.get('discovery'), qos=e.get('qos'), valid_frames=sum(x['sync']['ok'] for x in frames))
        out['status'] = 'OK' if out['valid_frames'] else 'UNKNOWN'
    elif gate == 'B':
        out['streams'] = {k: {'statistics': series_stats(rows.get(k, [])), 'samples': rows.get(k, [])}
                          for k in ('pc', 'scan', 'odom')}
        reference = e.get('time_reference')
        for k, stream in out['streams'].items():
            last = stream['statistics']['last_stamp']
            age = reference-last if reference is not None and last is not None else None
            stream['age_s'] = age
            if age is not None and (age < -.05 or age > .5):
                out['errors'].append('stale_or_future:' + k)
        missing = [k for k in ('pc','scan','odom') if not rows.get(k)]
        out['errors'].extend(['missing:' + k for k in missing])
        valid = all(rows.get(k) and any(x.get('valid_points', 0) > 0 for x in rows[k]) for k in ('pc','scan'))
        if not valid: out['errors'].append('no_valid_obstacle_returns')
        if any(out['streams'][k]['statistics']['non_monotonic'] for k in out['streams']):
            out['errors'].append('non_monotonic_sensor_time')
        if len(rows.get('odom', [])) >= 2:
            a,b = rows['odom'][0],rows['odom'][-1]
            out['odom_delta'] = odom_delta(a,b)
            if a['frame_id'] != b['frame_id'] or a['child'] != b['child']:
                out['errors'].append('odom_frame_changed')
        else: out['errors'].append('insufficient_odom_for_delta')
        out['status'] = 'OK' if not out['errors'] else 'UNKNOWN'
        out['direction_frame'] = 'sensor frame; robot directions require separately verified extrinsics'
    elif gate in ('C', 'D'):
        measurements = []
        for row in rows.get('frames', []):
            frame = load_frame(root, row)
            if frame.info is None or not frame.intrinsics_trusted:
                measurements.append({'stamp': row['stamp'], 'status': 'UNKNOWN', 'reason': 'camera_info_missing_or_untrusted'})
                continue
            uv = target_pixel(frame.rgb)
            if uv is None:
                measurements.append({'stamp': row['stamp'], 'status': 'UNKNOWN', 'reason': 'no_unique_circle_candidate'})
                continue
            t = np.asarray(row['tf']) if row.get('tf') is not None else None
            saved = row.get("target_candidate")
            ray = saved["ray_camera"] if saved and np.allclose(saved["uv"], uv, atol=0.01) else None
            est = estimate_target_range(frame, *uv, t, camera_ray=ray)
            m = {'stamp': row['stamp'], 'status': 'OK' if est.valid else 'UNKNOWN',
                 'target_identity': 'UNVERIFIED_circle_candidate', 'pixel_du': uv[0]-frame.info.cx,
                 'pixel_dv': uv[1]-frame.info.cy, 'range': est.__dict__}
            if gate == 'D':
                if est.valid and est.p_base is not None and not row.get('tf_error'):
                    lat, before, after = choose_lateral_direction_by_reprojection(est.p_base, t, frame.info)
                    m['plan'] = {'recommended_lateral': lat, 'du_before': before, 'du_candidate': after,
                                 'trial_dy_m': 0.05 if lat == 'left' else -0.05 if lat == 'right' else 0,
                                 'dry_run_command': {'vx': 0, 'vy': 0.02 if lat == 'left' else -0.02 if lat == 'right' else 0, 'wz': 0},
                                 'execute_allowed': False, 'obstacle_clearance': 'NOT_AUTHORIZED'}
                else:
                    m.update(status='UNKNOWN', reason='reliable_depth_and_tf_required')
            # Match odom by message time, never by row index or host time.
            odom = rows.get('odom', [])
            near = min(odom, key=lambda x: abs(x['stamp']-row['stamp'])) if odom else None
            m['odom'] = near if near and abs(near['stamp']-row['stamp']) <= 0.1 else None
            measurements.append(m)
        out['measurements'] = measurements
        zs = [m['range']['depth_axis_m'] for m in measurements if m['status']=='OK']
        out['depth_repeatability'] = {'n': len(zs), 'std_m': float(np.std(zs, ddof=1)) if len(zs)>1 else None,
            'condition': 'operator must confirm same target and static capture before interpreting repeatability'}
        matched = [m for m in measurements if m.get('odom') and m['status']=='OK']
        if len(matched) >= 2:
            a,b = matched[0], matched[-1]
            out['before_after'] = {'du_before': a['pixel_du'], 'du_after': b['pixel_du'],
                'abs_error_improvement_px': abs(a['pixel_du'])-abs(b['pixel_du']),
                'odom_delta': odom_delta(a['odom'],b['odom']),
                'target_consistency': 'UNVERIFIED; review saved images before causal interpretation'}
        out['status'] = 'OK' if any(m['status']=='OK' for m in measurements) else 'UNKNOWN'
    elif gate == 'E':
        lookups = e.get('tf_lookups', [])
        out.update(lookups=lookups, edges=rows.get('tf_edges', []),
            missing=[x for x in lookups if not x['ok']], stale=[x for x in lookups if x.get('stale')],
            camera_frame_queries=len(rows.get('frames', [])),
            camera_tf_available=sum(x.get('tf') is not None for x in rows.get('frames', [])))
        n = out['camera_frame_queries']
        out['camera_tf_availability'] = out['camera_tf_available']/n if n else None
        out['status'] = 'OK' if lookups and not out['missing'] and not out['stale'] else 'UNKNOWN'
    if source == 'SYNTHETIC_TEST':
        out['errors'].append('synthetic_not_field_evidence')
    # Always retain acquisition errors, but each gate is evaluated independently.
    out['acquisition_errors'] = e.get('errors', [])
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='read sensor subscriptions only; no robot motion')
    mode.add_argument('--evidence', type=Path, help='derived evidence.json from G1 extractor')
    p.add_argument('--recorded-replay', action='store_true', help='label live subscriptions fed by ros2 bag play')
    p.add_argument('--gate', default='all')
    add_capture_arguments(p)
    args = p.parse_args()
    if not 1 <= args.max_frames <= 200: p.error('max-frames must be 1..200')
    wanted = ['A','B','C','D','E'] if args.gate.lower()=='all' else args.gate.upper().split(',')
    if any(g not in 'ABCDE' or len(g)!=1 for g in wanted): p.error('gate must be A..E or all')
    root = Path(args.out_dir)
    if args.live and root.exists() and any(root.iterdir()):
        p.error('out-dir must be new or empty; preserve earlier sensor evidence')
    acquisition_error = None
    try:
        if args.live:
            e = capture_live(args, 'RECORDED_REPLAY' if args.recorded_replay else 'REAL_SENSOR')
        elif args.evidence:
            root = args.evidence.parent
            e = json.loads(args.evidence.read_text(encoding='utf-8'))
        else:
            e = {'data_source': 'SYNTHETIC_TEST', 'rows': {}}
    except Exception as exc:
        acquisition_error = str(exc)
        e = {'data_source': 'RECORDED_REPLAY' if args.recorded_replay or args.evidence else 'REAL_SENSOR' if args.live else 'SYNTHETIC_TEST',
             'rows': {}, 'errors': [acquisition_error]}
    output = {'gates': {}, 'independent_failures': True, 'live_motion': False}
    for gate in wanted:
        try:
            result = analyze(e, root, gate)
            if acquisition_error:
                result.update(status='FAIL', errors=[acquisition_error])
        except Exception as exc:
            result = {'gate': gate, 'data_source': e['data_source'], 'status': 'FAIL',
                      'errors': [str(exc)], 'field_verified': False}
        output['gates'][gate] = result
    root.mkdir(parents=True, exist_ok=True)
    content = json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False)
    (root / 'gates.json').write_text(content, encoding='utf-8')
    print(content)
    return 0 if all(x['status']=='OK' for x in output['gates'].values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
