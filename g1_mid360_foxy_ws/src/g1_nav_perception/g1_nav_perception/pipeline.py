"""Read original sources without modifying them; strict shared timestamp policy."""
import copy
import json
import math
import struct
import time
from pathlib import Path

import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from sensor_msgs.msg import PointCloud2, PointField, Imu, LaserScan
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from .core import Stream, Blocked, finite, quaternion, rotate, points_xyz, stamp_seconds, validate_site


def load_site(node):
    node.declare_parameter('site', '')
    if node.get_parameter('use_sim_time').value:
        raise Blocked('use_sim_time must be false; replay must use wall-time stamps')
    path = node.get_parameter('site').value
    if not path or not Path(path).is_file():
        raise Blocked('site file missing; copy and calibrate site.example.yaml')
    return validate_site(yaml.safe_load(Path(path).read_text()), full=False)


class Pipeline(Node):
    def __init__(self):
        super().__init__('g1_nav_pipeline')
        self.site = load_site(self)
        self.calibrated = True
        try:
            validate_site(self.site)
        except (Blocked, KeyError, TypeError) as exc:
            self.calibrated = False
            self.get_logger().error(str(exc))
        t = self.site['timing']
        self.streams = {k: Stream(t['max_age_s'], t['max_future_s'], t['jump_s'])
                        for k in ('cloud', 'odom', 'imu', 'scan')}
        self.started = time.monotonic()
        self.last_odom_publish = 0.
        self.frame_errors = {}
        self.edges = {}
        self.tf_conflict = ''
        self.tf_observable = True
        self.authority_received = None
        self.authority_ok = False
        self.cloud_pub = self.create_publisher(PointCloud2, '/g1_nav/cloud_timed', qos_profile_sensor_data)
        self.obstacles = self.create_publisher(PointCloud2, '/g1_nav/cloud_obstacles', qos_profile_sensor_data)
        self.odom_pub = self.create_publisher(Odometry, '/g1_nav/odom', qos_profile_sensor_data)
        self.imu_pub = self.create_publisher(Imu, '/g1_nav/imu', qos_profile_sensor_data)
        self.status = self.create_publisher(String, '/g1_nav/health', 10)
        self.diagnostics = self.create_publisher(DiagnosticArray, '/diagnostics', 10)
        self.create_subscription(PointCloud2, '/utlidar/cloud_livox_mid360', self.cloud, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/dog_odom', self.odom, qos_profile_sensor_data)
        self.create_subscription(Imu, '/utlidar/imu_livox_mid360', self.imu, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.scan, qos_profile_sensor_data)
        # Explicit scan subscription also activates Foxy cloud_to_scan's lazy input subscriber.
        self.create_subscription(TFMessage, '/tf', self.tf, 100)
        qos_static = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(TFMessage, '/tf_static', self.tf, qos_static)
        self.create_subscription(String, '/g1_nav/tf_authority', self.authority, 10)
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.scan_ratio = 0.
        self.clearance = 0.
        self.filter_stats = {}
        self.create_timer(.1, self.health)

    def accept(self, name, msg, expected):
        self.frame_errors[name] = '' if msg.header.frame_id == expected else 'WRONG_FRAME_'+name
        valid = self.streams[name].observe(stamp_seconds(msg.header.stamp), time.time(), time.monotonic())
        return valid and not self.frame_errors[name]

    def cloud(self, msg):
        ok = self.accept('cloud', msg, 'livox_frame')
        if not ok or not self.calibrated:
            return
        self.cloud_pub.publish(msg)  # original stamp is preserved, never a fixed clock offset
        c, f = self.site['calibration'], self.site['filter']
        kept, finite_count, ground_count = [], 0, 0
        try:
            for p in points_xyz(msg):
                finite_count += 1
                v = rotate(c['quaternion_xyzw'], p)
                v = tuple(v[i]+c['translation_xyz'][i] for i in range(3))
                if v[2] < f['min_height']:
                    ground_count += 1
                if f['min_height'] <= v[2] <= f['max_height']:
                    kept.append(v)
        except Blocked as exc:
            self.frame_errors['cloud'] = str(exc)
            return
        out = PointCloud2()
        out.header = copy.deepcopy(msg.header)
        out.header.frame_id = 'robot_center'
        out.height, out.width, out.point_step = 1, len(kept), 12
        out.row_step = out.width*12
        out.is_dense = True
        out.fields = [PointField(name=n, offset=i*4, datatype=PointField.FLOAT32, count=1)
                      for i, n in enumerate(('x', 'y', 'z'))]
        out.data = b''.join(struct.pack('<fff', *v) for v in kept)
        self.obstacles.publish(out)
        self.filter_stats = {'finite_points': finite_count, 'retained': len(kept),
                             'below_height': ground_count,
                             'retention_ratio': len(kept)/max(1, finite_count),
                             'ground_candidate_ratio': ground_count/max(1, finite_count)}

    def odom(self, msg):
        ok = self.accept('odom', msg, 'odom')
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        try:
            quaternion((q.x, q.y, q.z, q.w))
            if not finite((p.x, p.y, p.z)) or msg.child_frame_id != 'robot_center':
                raise Blocked('WRONG_ODOM_CHILD_OR_POSE')
        except Blocked as exc:
            self.frame_errors['odom'] = str(exc)
            return
        # Audit every raw sample but bound ROS TF/normalized odom load to <=50 Hz.
        now = time.monotonic()
        if ok and self.site['timing']['verified'] and now-self.last_odom_publish >= .02:
            self.odom_pub.publish(msg)
            self.last_odom_publish = now

    def imu(self, msg):
        # IMU is audited and preserved; no unverified frame conversion or fusion.
        ok = self.streams['imu'].observe(stamp_seconds(msg.header.stamp), time.time(), time.monotonic())
        if ok and self.site['timing']['verified']:
            self.imu_pub.publish(msg)

    def scan(self, msg):
        self.accept('scan', msg, 'robot_center')
        good = [v for v in msg.ranges if math.isfinite(v) and msg.range_min <= v <= msg.range_max]
        self.scan_ratio = len(good)/max(1, len(msg.ranges))
        self.clearance = min(good) if good else 0.

    def authority(self, msg):
        self.authority_received = time.monotonic()
        self.authority_ok = msg.data == 'OK'
        if not self.authority_ok:
            self.tf_conflict = msg.data

    def tf(self, msg):
        # Foxy rclpy has no MessageInfo callback: actual GID audit is in rclcpp.
        for t in msg.transforms:
            parent, child = t.header.frame_id, t.child_frame_id
            old = self.edges.get(child)
            if old and old[0] != parent:
                self.tf_conflict = 'TF_CONFLICT_'+child
            if parent == child:
                self.tf_conflict = 'TF_SELF_CYCLE_'+child
            self.edges[child] = (parent, 'rclcpp_audited')
            seen, cursor = set(), child
            while cursor in self.edges:
                if cursor in seen:
                    self.tf_conflict = 'TF_CYCLE_'+cursor
                    break
                seen.add(cursor)
                cursor = self.edges[cursor][0]

    def health(self):
        now = time.monotonic()
        reasons = []
        if not self.calibrated:
            reasons.append('BLOCKED_NEEDS_CALIBRATION')
        if self.count_publishers('/clock'):
            reasons.append('UNEXPECTED_CLOCK_TOPIC')
        for name in ('cloud', 'odom', 'imu', 'scan'):
            if not self.streams[name].healthy(now):
                reasons.append(name+':'+(self.streams[name].reason or 'TIMEOUT'))
        reasons.extend(v for v in self.frame_errors.values() if v)
        for topic in ('/utlidar/cloud_livox_mid360', '/dog_odom', '/scan', '/g1_nav/cloud_timed', '/g1_nav/odom'):
            if self.count_publishers(topic) != 1:
                reasons.append('PUBLISHER_COUNT:'+topic)
        for child, parent in (('robot_center', 'odom'), ('livox_frame', 'robot_center')):
            if child not in self.edges or self.edges[child][0] != parent:
                reasons.append('TF_EDGE:'+child)
        if self.tf_conflict or not self.tf_observable:
            reasons.append(self.tf_conflict or 'TF_AUTHORITY_UNOBSERVABLE')
        if (self.authority_received is None or now-self.authority_received > .4
                or not self.authority_ok or self.count_publishers('/g1_nav/tf_authority') != 1):
            reasons.append('TF_AUTHORITY_INHIBIT')
        try:
            tf = self.buffer.lookup_transform('odom', 'robot_center', Time())
            age = time.time()-stamp_seconds(tf.header.stamp)
            if not -self.site['timing']['max_future_s'] <= age <= self.site['timing']['max_age_s']:
                reasons.append('TF_STALE_OR_FUTURE')
            sensor_tf = self.buffer.lookup_transform('robot_center', 'livox_frame', Time())
            if self.calibrated:
                c = self.site['calibration']
                p = sensor_tf.transform.translation
                q = sensor_tf.transform.rotation
                actual_q = (q.x, q.y, q.z, q.w)
                dot = abs(sum(a*b for a, b in zip(actual_q, c['quaternion_xyzw'])))
                if max(abs(a-b) for a, b in zip((p.x, p.y, p.z), c['translation_xyz'])) > .001 or abs(dot-1.) > .001:
                    reasons.append('TF_CALIBRATION_MISMATCH')
        except Exception:
            reasons.append('TF_LOOKUP_FAILED')
        if self.scan_ratio < self.site['diagnostics']['minimum_scan_finite_ratio']:
            reasons.append('SCAN_INVALID_RATIO')
        stats = {k: v.report() for k, v in self.streams.items()}
        map_ready = False
        try:
            map_tf = self.buffer.lookup_transform('map', 'odom', Time())
            map_age = time.time()-stamp_seconds(map_tf.header.stamp)
            map_ready = -.2 <= map_age <= .3 and 'odom' in self.edges and self.edges['odom'][0] == 'map'
        except Exception:
            pass
        radius = max((math.hypot(*p) for p in (self.site['robot']['footprint'] or [])), default=1.)
        l = self.site['limits']
        stop_distance = radius+.2+l['vx']*.4+l['vx']**2/(2*l['accel_x'])
        clear = self.clearance > stop_distance
        payload = {'schema_version': 1, 'data_source': self.site['data_source'],
                   'healthy': not reasons, 'reasons': sorted(set(reasons)),
                   'map_ready': map_ready,
                   'realtime': time.time(), 'uptime_s': now-self.started,
                   'streams': stats, 'scan_finite_ratio': self.scan_ratio,
                   'clearance_m': self.clearance, 'stop_distance_m': stop_distance,
                   'obstacle_stop': not clear, 'filter': self.filter_stats,
                   'tf_edges': self.edges, 'live': 'DISABLED'}
        s = String(); s.data = json.dumps(payload, allow_nan=False)
        self.status.publish(s)
        d = DiagnosticStatus()
        d.name, d.hardware_id = 'g1_nav/read_only_pipeline', 'G1_MID360_UNVERIFIED'
        d.level = DiagnosticStatus.OK if not reasons else DiagnosticStatus.ERROR
        d.message = 'DRY_RUN_READY' if not reasons else ';'.join(sorted(set(reasons)))
        d.values = [KeyValue(key='report', value=s.data)]
        arr = DiagnosticArray(); arr.header.stamp = self.get_clock().now().to_msg(); arr.status = [d]
        self.diagnostics.publish(arr)


def main(args=None):
    rclpy.init(args=args)
    node = Pipeline()
    from .runtime import spin
    spin(node)
