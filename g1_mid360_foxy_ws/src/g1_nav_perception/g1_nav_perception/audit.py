"""Read-only clock evidence, runtime gate and active scan smoke subscriptions."""
import argparse
import inspect
import json
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, Imu
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from .core import Stream, stamp_seconds


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=30.)
    parser.add_argument('--output', required=True)
    options = parser.parse_args(args)
    if options.duration < 30:
        parser.error('at least 30 seconds required')
    rclpy.init(args=[]); node = Node('g1_clock_preflight')
    streams = {k: Stream() for k in ('cloud', 'odom', 'imu')}
    topics = {'cloud': ('/utlidar/cloud_livox_mid360', PointCloud2),
              'odom': ('/dog_odom', Odometry), 'imu': ('/utlidar/imu_livox_mid360', Imu)}
    for key, (topic, cls) in topics.items():
        def receive(m, k=key):
            streams[k].observe(stamp_seconds(m.header.stamp), time.time(), time.monotonic())
        node.create_subscription(cls, topic, receive, qos_profile_sensor_data)
    start = time.monotonic(); clock_seen = False
    while time.monotonic()-start < options.duration:
        rclpy.spin_once(node, timeout_sec=.1)
        clock_seen = clock_seen or node.count_publishers('/clock') > 0
    qos = {}
    for key, (topic, _) in topics.items():
        qos[key] = [{'node': p.node_name, 'namespace': p.node_namespace,
                     'qos': str(p.qos_profile), 'gid': list(p.endpoint_gid)}
                    for p in node.get_publishers_info_by_topic(topic)]
    report = {'data_source': 'REAL_SENSOR_OR_EXTERNAL_REPLAY_UNVERIFIED',
              'clock_realtime': time.time(), 'use_sim_time': False, 'clock_topic_seen': clock_seen,
              'streams': {k: s.report() for k, s in streams.items()}, 'publishers': qos,
              'interpretation': 'Offsets alone do not identify clock origin or distinguish transport delay. No system clock changes made.'}
    path = Path(options.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    node.destroy_node(); rclpy.shutdown()
    good = not clock_seen and all(s.report()['count'] > 0 and s.report()['invalid'] == 0 for s in streams.values())
    raise SystemExit(0 if good else 2)


class Gate(Node):
    def __init__(self):
        super().__init__('g1_nav_runtime_preflight')
        self.declare_parameter('duration_s', 30.)
        self.declare_parameter('timeout_s', 45.)
        self.declare_parameter('minimum_cloud_hz', 7.)
        self.declare_parameter('minimum_odom_hz', 20.)
        self.last = None
        self.received = None
        self.since = None
        self.create_subscription(String, '/g1_nav/health', self.receive, 10)

    def receive(self, msg):
        try:
            self.last = json.loads(msg.data)
            self.received = time.monotonic()
        except ValueError:
            self.last = None

    def ready(self):
        h = self.last or {}; now = time.monotonic()
        good = (h.get('healthy') is True and self.received is not None and
                now-self.received < .3 and self.count_publishers('/g1_nav/health') == 1)
        streams = h.get('streams', {})
        for name, hz in (('cloud', self.get_parameter('minimum_cloud_hz').value),
                         ('odom', self.get_parameter('minimum_odom_hz').value), ('scan', 5.), ('imu', 20.)):
            s = streams.get(name, {})
            good = good and s.get('hz', 0) >= hz and s.get('invalid_window', 1) == 0
        if not good:
            self.since = None
        elif self.since is None:
            self.since = now
        return self.since is not None and now-self.since >= self.get_parameter('duration_s').value


def gate_main(args=None):
    rclpy.init(args=args); node = Gate(); start = time.monotonic(); passed = False
    while rclpy.ok() and time.monotonic()-start < node.get_parameter('timeout_s').value:
        rclpy.spin_once(node, timeout_sec=.1)
        if node.ready():
            passed = True
            break
    node.get_logger().info(json.dumps({'passed': passed, 'latest_health': node.last}, default=str))
    node.destroy_node(); rclpy.shutdown(); raise SystemExit(0 if passed else 2)


def smoke_main(args=None):
    # Same strict gate; active /scan subscription is owned by the pipeline.
    gate_main(args)
