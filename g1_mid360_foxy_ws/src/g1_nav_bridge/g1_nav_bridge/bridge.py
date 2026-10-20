"""Observes Nav2 /cmd_vel; isolated safe preview only, no SDK transport exists."""
import json
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from g1_nav_perception.pipeline import load_site
from g1_nav_perception.core import DryGate
from .motion_lock import MotionLock


class Bridge(Node):
    def __init__(self):
        super().__init__('g1_nav_dry_bridge')
        site = load_site(self)
        self.declare_parameter('allow_live', False)
        self.declare_parameter('dry_run', True)
        self.gate = DryGate(site['limits'], allow_live=self.get_parameter('allow_live').value,
                            dry_run=self.get_parameter('dry_run').value)
        self.lock = MotionLock.acquire('g1_nav_dry_bridge')
        self.health = None
        self.health_received = None
        self.safe = self.create_publisher(Twist, '/g1_nav/cmd_vel_safe', 10)
        self.observer = self.create_publisher(String, '/g1_nav/command_observer', 10)
        self.create_subscription(Twist, '/cmd_vel', self.command, 10)
        self.create_subscription(String, '/g1_nav/health', self.status, 10)
        self.create_timer(.05, self.tick)

    def command(self, m):
        self.gate.command((m.linear.x, m.linear.y, m.linear.z, m.angular.x, m.angular.y, m.angular.z), time.monotonic())

    def status(self, m):
        try:
            data = json.loads(m.data)
            if not isinstance(data, dict) or data.get('schema_version') != 1:
                raise ValueError('health schema')
            self.health = data
            self.health_received = time.monotonic()
        except (ValueError, TypeError):
            self.health = None

    def tick(self):
        now = time.monotonic()
        h = self.health or {}
        fresh = self.health_received is not None and now-self.health_received <= .3
        unique = self.count_publishers('/g1_nav/health') == 1 and self.count_publishers('/cmd_vel') == 1
        ready = (fresh and unique and h.get('healthy') is True and h.get('obstacle_stop') is False
                 and h.get('map_ready') is True)
        reason = 'OBSTACLE_STOP' if h.get('obstacle_stop') else 'HEALTH_TIMEOUT_OR_INHIBIT'
        vx, vy, wz = self.gate.tick(now, ready, reason)
        m = Twist(); m.linear.x, m.linear.y, m.angular.z = vx, vy, wz
        self.safe.publish(m)
        s = String(); s.data = json.dumps({'live': 'DISABLED', 'sdk_write_calls': 0,
            'health_age_s': now-self.health_received if self.health_received is not None else None,
            'reason': self.gate.reason, 'safe_preview': [vx, vy, wz], 'health_reasons': h.get('reasons', [])})
        self.observer.publish(s)

    def destroy_node(self):
        self.lock.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args); node = Bridge()
    from g1_nav_perception.runtime import spin
    spin(node)
