"""Reference: Python unittest; SDK replaced only here, never in deployed packages."""
import math
import sys
import time
import types
import unittest
from unittest.mock import patch

import rclpy
from geometry_msgs.msg import Twist
from cmd_vel_bridge.bridge_node import Bridge, shape


class Client:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            return (0, 777) if name == 'GetFsmId' else 0
        return call


class Tests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        modules = {}
        for name in ('unitree_sdk2py', 'unitree_sdk2py.core', 'unitree_sdk2py.core.channel',
                     'unitree_sdk2py.g1', 'unitree_sdk2py.g1.loco', 'unitree_sdk2py.g1.loco.g1_loco_client'):
            modules[name] = types.ModuleType(name)
        modules['unitree_sdk2py.core.channel'].ChannelFactoryInitialize = lambda *args: None
        modules['unitree_sdk2py.g1.loco.g1_loco_client'].LocoClient = lambda: self.client
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        rclpy.init(args=['--ros-args', '-p', 'dry_run:=false'])
        self.node = Bridge()

    def tearDown(self):
        self.node.release()
        self.node.destroy_node()
        rclpy.shutdown()
        self.modules.stop()

    def test_deadband_then_saturation(self):
        p = self.node.p
        self.assertEqual(shape(0.049, -0.049, 0.099, p), (0., 0., 0.))
        self.assertEqual(shape(8., -8., 9., p), (0.5, -0.2, 0.5))
        self.assertEqual(shape(-8., 8., -9., p), (-0.3, 0.2, -0.5))
        self.assertEqual(shape(0.05, 0., 0., p), (0.05, 0., 0.))
        self.assertEqual(shape(math.nan, 0., 0., p), (0., 0., 0.))

    def test_four_arguments_and_timeout(self):
        msg = Twist()
        msg.linear.x = 0.2
        self.node.receive(msg)
        self.node.send()
        self.assertEqual(self.client.calls[-1], ('SetVelocity', (0.2, 0., 0., 0.1)))
        with patch('cmd_vel_bridge.bridge_node.time.monotonic', return_value=self.node.received + 0.5):
            self.node.send()
        self.assertEqual(self.client.calls[-1], ('SetVelocity', (0., 0., 0., 0.1)))

    def test_modes_release_and_50hz_timer(self):
        self.assertIn(('SetFsmId', (501,)), self.client.calls)
        self.assertIn(('SetBalanceMode', (1,)), self.client.calls)
        self.assertEqual(list(self.node.timers)[0].timer_period_ns, 20000000)
        self.node.release()
        self.assertEqual(self.client.calls[-2:], [('SetBalanceMode', (0,)), ('SetFsmId', (777,))])

    def test_dry_run_has_no_sdk_calls(self):
        self.node.destroy_node()
        rclpy.shutdown()
        rclpy.init(args=[])
        self.node = Bridge()
        self.assertIsNone(self.node.client)
        before = len(self.client.calls)
        self.node.send()
        self.assertEqual(len(self.client.calls), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
