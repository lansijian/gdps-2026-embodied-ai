"""ROS-independent fail-closed contracts. All times in seconds, quaternion xyzw."""
import math
import statistics
import struct
from collections import deque


class Blocked(ValueError):
    pass


def finite(values):
    return all(isinstance(x, (float, int)) and not isinstance(x, bool)
               and math.isfinite(x) for x in values)


def quaternion(q):
    if not isinstance(q, (list, tuple)) or len(q) != 4 or not finite(q) or abs(sum(x*x for x in q)-1.0) > 0.001:
        raise Blocked('invalid unit quaternion')
    return q


def rotate(q, p):
    x, y, z, w = quaternion(q)
    tx, ty, tz = 2*(y*p[2]-z*p[1]), 2*(z*p[0]-x*p[2]), 2*(x*p[1]-y*p[0])
    return (p[0]+w*tx+y*tz-z*ty, p[1]+w*ty+z*tx-x*tz,
            p[2]+w*tz+x*ty-y*tx)


def _strict_site(site, full=True):
    if not isinstance(site, dict):
        raise Blocked('SITE_INVALID: expected mapping; use installed example defaults')
    fields = {'live': ('allow_live', 'dry_run'), 'timing': ('strategy', 'max_age_s', 'max_future_s', 'jump_s', 'verified'),
              'limits': ('vx', 'vy', 'wz', 'accel_x', 'accel_wz', 'command_timeout_s')}
    if full:
        fields.update(calibration=('verified', 'evidence_id', 'translation_xyz', 'quaternion_xyzw'),
                      filter=('verified', 'evidence_id', 'ground_z', 'ground_margin', 'min_height', 'max_height', 'scan_time', 'range_min', 'range_max', 'angle_increment'),
                      robot=('footprint_verified', 'safe_environment_confirmed', 'blind_spots_reviewed', 'footprint'),
                      tf=('odom_owner', 'livox_owner'))
    for section, required in fields.items():
        if not isinstance(site.get(section), dict) or not set(required).issubset(site[section]):
            raise Blocked('SITE_INVALID: missing/malformed '+section+'; load through read_site to merge defaults')
    if 'data_source' not in site:
        raise Blocked('SITE_INVALID: missing data_source; load through read_site to merge defaults')
    if site['live'] != {'allow_live': False, 'dry_run': True}:
        raise Blocked('LIVE_DISABLED: this release has no SDK write transport')
    if site['data_source'] not in ('REAL_SENSOR', 'RECORDED_REPLAY', 'SYNTHETIC_TEST'):
        raise Blocked('unknown data source')
    t = site['timing']
    if t['strategy'] not in ('preserve', 'receive_time', 'offset'):
        raise Blocked('unsupported timestamp strategy')
    if t['strategy'] == 'receive_time' and t.get('receipt_time_acknowledged') is not True:
        raise Blocked('receive_time requires receipt_time_acknowledged=true; receipt time is not acquisition synchronization')
    if not finite([t['max_age_s'], t['max_future_s'], t['jump_s']]) or not (
            0 < t['max_age_s'] <= 0.5 and 0 < t['max_future_s'] <= 0.05 and 0 < t['jump_s'] <= 0.3):
        raise Blocked('unsafe timestamp tolerances')
    limits = site['limits']
    vals = [limits[k] for k in ('vx', 'vy', 'wz', 'accel_x', 'accel_wz', 'command_timeout_s')]
    if not finite(vals) or not (0 < vals[0] <= .1 and vals[1] == 0 and
            0 < vals[2] <= .15 and 0 < vals[3] <= .05 and 0 < vals[4] <= .1 and 0 < vals[5] <= .25):
        raise Blocked('unsafe dry-run limits')
    if not full:
        return site
    for section in ('calibration', 'timing', 'filter'):
        if (site[section]['verified'] is not True or not isinstance(site[section].get('evidence_id'), str)
                or not site[section]['evidence_id'].strip()):
            raise Blocked('BLOCKED_NEEDS_CALIBRATION: '+section)
    c, f = site['calibration'], site['filter']
    if not isinstance(c['translation_xyz'], (list, tuple)) or len(c['translation_xyz']) != 3 or not finite(c['translation_xyz']):
        raise Blocked('unknown sensor translation')
    quaternion(c['quaternion_xyzw'])
    if not finite([f['ground_z'], f['ground_margin'], f['min_height'], f['max_height'], f['scan_time'], f['range_min'], f['range_max'], f['angle_increment']]):
        raise Blocked('unknown scan filter/frequency')
    checks = {
        'ground_z must be within [-3,1] in robot_center': -3 <= f['ground_z'] <= 1,
        'ground_margin must be within [0.01,0.2]': .01 <= f['ground_margin'] <= .2,
        'height window must satisfy -3 <= min_height < max_height <= 3': -3 <= f['min_height'] < f['max_height'] <= 3,
        'min_height must be >= ground_z + ground_margin (robot_center coordinates)': f['min_height'] >= f['ground_z']+f['ground_margin'],
        'scan_time must be within [0.05,0.3] seconds': .05 <= f['scan_time'] <= .3,
        'range must satisfy 0 < range_min < range_max <= 20': 0 < f['range_min'] < f['range_max'] <= 20,
        'angle_increment must be within [0.003,0.05] radians': .003 <= f['angle_increment'] <= .05,
    }
    for reason, good in checks.items():
        if not good:
            raise Blocked('invalid height/range/scan filter: '+reason)
    r = site['robot']
    if not all(r[k] is True for k in ('footprint_verified', 'safe_environment_confirmed', 'blind_spots_reviewed')):
        raise Blocked('BLOCKED_ENVIRONMENT: footprint, blind spots, stairs/negative obstacles')
    fp = r['footprint']
    if not isinstance(fp, list) or len(fp) < 3 or any(not isinstance(p, (list, tuple)) or len(p) != 2 or not finite(p) for p in fp):
        raise Blocked('invalid footprint')
    if any(site['tf'][k] not in ('project', 'external') for k in ('odom_owner', 'livox_owner')):
        raise Blocked('unknown TF ownership')
    return site


def validate_site(site, full=True):
    """Stage 3: startup blocks only on command safety limits; other issues are health warnings."""
    if not isinstance(site, dict):
        raise Blocked('SITE_INVALID: expected mapping')
    limits = site.get('limits', {})
    vals = [limits.get(k) for k in ('vx', 'vy', 'wz', 'accel_x', 'accel_wz', 'command_timeout_s')]
    if not finite(vals) or not (0 < vals[0] <= .1 and vals[1] == 0 and 0 < vals[2] <= .15
            and 0 < vals[3] <= .05 and 0 < vals[4] <= .1 and 0 < vals[5] <= .25):
        raise Blocked('unsafe command limits: velocity/acceleration/timeout')
    return site


def site_warnings(site):
    reasons = []
    try:
        _strict_site(site)
    except (Blocked, TypeError, KeyError, AttributeError) as exc:
        reasons.append(str(exc))
    for section in ('calibration', 'filter'):
        if site.get(section, {}).get('verified') is not True:
            reasons.append('UNVERIFIED_'+section.upper())
    if site.get('timing', {}).get('strategy') == 'receive_time':
        reasons.append('DEPRECATED_RECEIVE_TIME')
    return sorted(set(reasons))


class OffsetCalibrator:
    """Session-local median, no fixed bias. 10 warm-up frames; 30-frame jitter audit."""
    def __init__(self, start, frames=10, timeout=30.):
        self.start, self.frames, self.timeout = start, frames, timeout
        self.deltas = deque(maxlen=30)
        self.offset = None
        self.jitter = 0.

    def observe(self, stamp, realtime, monotonic):
        if not finite((stamp, realtime, monotonic)) or stamp <= 0:
            return None
        if self.offset is None and monotonic-self.start >= self.timeout:
            raise Blocked('OFFSET_CALIBRATION_TIMEOUT: fewer than 10 valid frames within 30s')
        self.deltas.append(realtime-stamp)
        if self.offset is None:
            if len(self.deltas) >= self.frames:
                self.offset = statistics.median(self.deltas)
            return None  # All ten calibration frames are withheld.
        self.jitter = max(self.deltas)-min(self.deltas) if len(self.deltas) == 30 else 0.
        return stamp+self.offset

    def expired(self, now):
        return self.offset is None and now-self.start >= self.timeout


def assign_stamp(msg, seconds):
    whole = math.floor(seconds)
    nanos = round((seconds-whole)*1e9)
    if nanos == 1000000000:
        whole, nanos = whole+1, 0
    msg.header.stamp.sec, msg.header.stamp.nanosec = int(whole), int(nanos)


def stamp_seconds(msg):
    return msg.sec + msg.nanosec * 1e-9


class ReceiptClock:
    """Detect host clock steps; never claim to measure sensor transport delay."""
    def __init__(self, tolerance):
        self.last = None
        self.tolerance = tolerance
        self.failed = False

    def observe(self, realtime, monotonic):
        if not finite((realtime, monotonic)) or realtime <= 0:
            self.failed = True
        if self.last is not None:
            wall_delta = realtime-self.last[0]
            mono_delta = monotonic-self.last[1]
            if wall_delta < 0 or mono_delta < 0 or abs(wall_delta-mono_delta) > self.tolerance:
                self.failed = True
        self.last = (realtime, monotonic)
        return not self.failed


class Stream:
    def __init__(self, age=.3, future=.03, jump=.2):
        self.age, self.future, self.jump = age, future, jump
        self.last_stamp = self.last_recv = None
        self.samples = deque(maxlen=100000)
        self.reason = 'NO_DATA'
        self.out_of_order = self.jumps = self.invalid = 0

    def observe(self, stamp, realtime, monotonic):
        reason = ''
        if not finite([stamp, realtime, monotonic]) or stamp <= 0:
            reason = 'INVALID_STAMP'
        elif stamp-realtime > self.future:
            reason = 'FUTURE_STAMP'
        elif realtime-stamp > self.age:
            reason = 'STALE_STAMP'
        elif self.last_stamp is not None:
            if stamp <= self.last_stamp:
                self.out_of_order += 1
                reason = 'OUT_OF_ORDER'
            elif abs((stamp-self.last_stamp)-(monotonic-self.last_recv)) > self.jump:
                self.jumps += 1
                reason = 'CLOCK_JUMP'
        self.last_stamp, self.last_recv = stamp, monotonic
        self.reason = reason
        self.invalid += bool(reason)
        self.samples.append((monotonic, realtime-stamp, bool(reason)))
        while self.samples and monotonic-self.samples[0][0] > 30:
            self.samples.popleft()
        return not reason

    def healthy(self, now, timeout=.4):
        return self.last_recv is not None and 0 <= now-self.last_recv <= timeout and not self.reason

    def report(self):
        offsets = sorted(s[1] for s in self.samples)
        span = self.samples[-1][0]-self.samples[0][0] if len(offsets) > 1 else 0
        return {'count': len(offsets), 'window_s': span, 'hz': (len(offsets)-1)/span if span else 0,
                'offset_p50_s': statistics.median(offsets) if offsets else None,
                'offset_p95_s': offsets[min(len(offsets)-1, int(.95*len(offsets)))] if offsets else None,
                'offset_min_s': min(offsets) if offsets else None,
                'offset_max_s': max(offsets) if offsets else None,
                'invalid_window': sum(s[2] for s in self.samples),
                'out_of_order': self.out_of_order, 'jumps': self.jumps, 'invalid': self.invalid,
                'reason': self.reason}


def points_xyz(msg):
    """Respect PointCloud2 padding, organized rows, endianness and float32/64."""
    fields = {f.name: f for f in msg.fields}
    fmt = {7: 'f', 8: 'd'}
    if any(k not in fields or fields[k].datatype not in fmt or fields[k].count != 1 for k in ('x', 'y', 'z')):
        raise Blocked('unsupported PointCloud2 XYZ fields')
    if msg.row_step < msg.width*msg.point_step or len(msg.data) < msg.row_step*msg.height:
        raise Blocked('truncated PointCloud2')
    endian = '>' if msg.is_bigendian else '<'
    for row in range(msg.height):
        for col in range(msg.width):
            start = row*msg.row_step+col*msg.point_step
            xyz = []
            for k in ('x', 'y', 'z'):
                f = fields[k]
                size = struct.calcsize(fmt[f.datatype])
                if f.offset < 0 or f.offset+size > msg.point_step:
                    raise Blocked('invalid field offset')
                xyz.append(struct.unpack_from(endian+fmt[f.datatype], msg.data, start+f.offset)[0])
            if finite(xyz):
                yield xyz


class DryGate:
    """No SDK import or construction; backend argument is a test tripwire only."""
    def __init__(self, limits, backend=None, allow_live=False, dry_run=True):
        if allow_live or not dry_run:
            raise Blocked('LIVE_DISABLED; independent watchdog/SDK/FSM validation pending')
        self.limits = limits
        self.last_cmd = None
        self.target = self.previous = (0., 0., 0.)
        self.last_tick = None
        self.reason = 'STARTUP_INHIBIT'

    def command(self, values, now, frame='robot_center'):
        if frame != 'robot_center' or len(values) != 6 or not finite(values):
            self.target = (0., 0., 0.)
            self.last_cmd = None
            self.reason = 'INVALID_COMMAND_FRAME_OR_VALUES'
            return
        vx, vy, vz, wx, wy, wz = values
        if vz or wx or wy or vy or abs(vx) > self.limits['vx'] or abs(wz) > self.limits['wz']:
            self.target = (0., 0., 0.)
            self.last_cmd = None
            self.reason = 'OUT_OF_BOUNDS_COMMAND'
            return
        self.target = (vx, 0., wz)
        self.last_cmd = now

    def tick(self, now, healthy, reason='HEALTH_INHIBIT'):
        dt = min(.1, max(0., now-self.last_tick)) if self.last_tick is not None else 0.
        self.last_tick = now
        if not healthy or self.last_cmd is None or not 0 <= now-self.last_cmd <= self.limits['command_timeout_s']:
            self.previous = (0., 0., 0.)
            self.reason = reason if not healthy else 'COMMAND_TIMEOUT_OR_INVALID'
        else:
            acceleration = (self.limits['accel_x'], 0., self.limits['accel_wz'])
            self.previous = tuple(max(-limit, min(limit, old+max(-a*dt, min(a*dt, target-old))))
                                  for target, old, a, limit in zip(self.target, self.previous, acceleration,
                                                                (self.limits['vx'], 0., self.limits['wz'])))
            self.reason = 'DRY_RUN_ONLY'
        return self.previous
