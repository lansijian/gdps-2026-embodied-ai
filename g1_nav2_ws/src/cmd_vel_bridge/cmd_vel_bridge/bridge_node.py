"""Reference: Unitree g1_loco_client.py; rawatprashant.com G1 robot-side control."""
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


def shape(vx, vy, wz, p):
    if not all(math.isfinite(v) for v in (vx, vy, wz)):
        return 0.0, 0.0, 0.0
    if abs(vx) < p['deadband_x'] and abs(vy) < p['deadband_y'] and abs(wz) < p['deadband_w']:
        return 0.0, 0.0, 0.0
    return (max(p['min_vx'], min(p['max_vx'], vx)),
            max(-p['max_vy'], min(p['max_vy'], vy)),
            max(-p['max_w'], min(p['max_w'], wz)))


class Bridge(Node):
    def __init__(self):
        super().__init__('cmd_vel_bridge')
        defaults = dict(deadband_x=0.05, deadband_y=0.05, deadband_w=0.1,
                        min_vx=-0.3, max_vx=0.5, max_vy=0.2, max_w=0.5,
                        timeout_sec=0.5, duration=0.1, dry_run=True, interface='eth0')
        self.p = {k: self.declare_parameter(k, v).value for k, v in defaults.items()}
        self.velocity, self.received, self.client = (0.0, 0.0, 0.0), None, None
        if not self.p['dry_run']:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
            ChannelFactoryInitialize(0, self.p['interface'])
            self.client = LocoClient()
            self.client.SetTimeout(10.0)
            self.client.Init()
            code, self.initial_fsm = self.client.GetFsmId()
            if code != 0 or self.initial_fsm is None:
                raise RuntimeError('Cannot read the initial SDK FSM; no motion mode was selected')
            try:
                for method, value in ((self.client.SetFsmId, 501), (self.client.SetBalanceMode, 1)):
                    result = method(value)
                    if result != 0:
                        raise RuntimeError('SDK mode selection failed: {}'.format(result))
            except Exception:
                self.release()
                raise
        self.create_subscription(Twist, '/cmd_vel', self.receive, 10)
        self.create_timer(0.02, self.send)
        self.get_logger().info('50 Hz command bridge; dry_run={}'.format(self.p['dry_run']))

    def receive(self, msg):
        self.velocity = shape(msg.linear.x, msg.linear.y, msg.angular.z, self.p)
        self.received = time.monotonic()

    def send(self):
        velocity = self.velocity
        if self.received is None or time.monotonic() - self.received >= self.p['timeout_sec']:
            velocity = (0.0, 0.0, 0.0)
        if self.client is not None:
            try:
                result = self.client.SetVelocity(*velocity, self.p['duration'])
            except Exception as error:
                self.get_logger().error('SetVelocity raised {!r}; timer keeps running and the timeout still sends zero velocity'.format(error))
            else:
                if result != 0:
                    self.get_logger().error('SetVelocity returned {}'.format(result))

    def release(self):
        if self.client is not None:
            try:
                self.client.SetVelocity(0.0, 0.0, 0.0, self.p['duration'])
            finally:
                try:
                    self.client.SetBalanceMode(0)
                finally:
                    self.client.SetFsmId(self.initial_fsm)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = Bridge()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            try:
                node.release()
            finally:
                node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
