from __future__ import annotations

import math
import os
import tempfile
import time
import unittest
from pathlib import Path

from shared.navigation.api.navigator import MotionIntent, NavState, SharedNavigator
from shared.navigation.api.types import Pose2D
from shared.navigation.factory import build_navigator, load_nav_config
from shared.navigation.perception.obstacle_monitor import (
    AvoidDecision,
    ObstacleMonitor,
    ScanFrame,
)
from shared.navigation.safety.supervisor import SafetyHalt, SafetySupervisor
from shared.robot_control.g1.adapter import AdapterLimits, G1MotionAdapter, MotionMode
from shared.robot_control.g1.command import VelocityCommand
from shared.robot_control.g1.mock_backend import MockLocoBackend
from shared.robot_control.g1.motion_lock import MotionLock, MotionLockError


def _scan(forward_range: float, n: int = 21) -> ScanFrame:
    mid = n // 2
    ranges = [10.0] * n
    ranges[mid] = forward_range
    return ScanFrame(
        ranges=tuple(ranges),
        angle_min=-0.5,
        angle_increment=1.0 / (n - 1),
        range_min=0.05,
        range_max=20.0,
        frame_id="mock",
    )


class ObstacleTests(unittest.TestCase):
    def test_stop_when_close(self) -> None:
        mon = ObstacleMonitor(stop_distance_m=0.6, slow_distance_m=1.2)
        # 0.5 m is above the 0.40 m blind zone but within stop distance.
        self.assertEqual(mon.update(_scan(0.5)), AvoidDecision.STOP)

    def test_clear_when_far(self) -> None:
        mon = ObstacleMonitor()
        self.assertEqual(mon.update(_scan(5.0)), AvoidDecision.CLEAR)

    def test_detour_when_one_side_clearer(self) -> None:
        mon = ObstacleMonitor(stop_distance_m=0.4, slow_distance_m=2.0)
        n = 21
        ranges = [0.9] * n
        for i in range(n):
            angle = -0.5 + i * (1.0 / (n - 1))
            if angle > 0.15:
                ranges[i] = 8.0
        scan = ScanFrame(
            ranges=tuple(ranges),
            angle_min=-0.5,
            angle_increment=1.0 / (n - 1),
        )
        self.assertEqual(mon.update(scan), AvoidDecision.DETOUR_LEFT)

    def test_no_sensor_without_valid_ranges(self) -> None:
        mon = ObstacleMonitor()
        empty = ScanFrame(ranges=(float("nan"),), angle_min=0.0, angle_increment=0.1)
        self.assertEqual(mon.update(empty), AvoidDecision.NO_SENSOR)


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock_path = tempfile.mktemp(prefix="gdps_lock_")
        self.backend = MockLocoBackend()
        self.adapter = G1MotionAdapter(
            backend=self.backend,
            owner="test",
            lock_path=self.lock_path,
            limits=AdapterLimits(max_vx=0.10, max_wz=0.15, command_timeout_s=0.05),
        )
        self.assertEqual(self.adapter.connect(), 0)

    def tearDown(self) -> None:
        self.adapter.close()

    def test_dry_run_does_not_touch_backend_velocity(self) -> None:
        code = self.adapter.send_velocity(VelocityCommand(vx=1.0, wz=2.0, source="t"))
        self.assertEqual(code, 0)
        self.assertEqual(self.backend.history, [])
        last = self.adapter.last_command
        assert last is not None
        self.assertAlmostEqual(last.vx, 0.10)
        self.assertAlmostEqual(last.wz, 0.15)

    def test_watchdog_zeroes_command(self) -> None:
        self.adapter.send_velocity(VelocityCommand(vx=0.05, source="t"))
        time.sleep(0.07)
        self.adapter.watchdog_tick()
        last = self.adapter.last_command
        assert last is not None
        self.assertTrue(last.is_zero())
        self.assertTrue(last.source.startswith("stop:command_timeout"))

    def test_live_requires_env_and_phrase(self) -> None:
        os.environ.pop("GDPS_G1_LIVE", None)
        self.adapter.live_token = "secret"
        with self.assertRaises(PermissionError):
            self.adapter.enable_live("secret", "ENABLE LIVE MOTION")
        os.environ["GDPS_G1_LIVE"] = "1"
        with self.assertRaises(PermissionError):
            self.adapter.enable_live("wrong", "ENABLE LIVE MOTION")
        with self.assertRaises(PermissionError):
            self.adapter.enable_live("secret", "yes")
        self.adapter.enable_live("secret", "ENABLE LIVE MOTION")
        self.assertEqual(self.adapter.mode, MotionMode.LIVE)
        os.environ.pop("GDPS_G1_LIVE", None)

    def test_live_stop_uses_stop_move_not_zero_torque(self) -> None:
        os.environ["GDPS_G1_LIVE"] = "1"
        self.adapter.live_token = "secret"
        self.adapter.enable_live("secret", "ENABLE LIVE MOTION")
        self.adapter.motion_authority_confirmed = True  # mock-only synthetic authorization
        self.adapter.allowed_live_fsm_ids = (501,)
        self.adapter.send_velocity(VelocityCommand(vx=0.05, source="t"))
        self.assertEqual(len(self.backend.history), 1)
        self.adapter.stop("unit_test")
        self.assertGreaterEqual(self.backend.stop_count, 1)
        os.environ.pop("GDPS_G1_LIVE", None)

    def test_exclusive_lock(self) -> None:
        other = G1MotionAdapter(
            backend=MockLocoBackend(),
            owner="other",
            lock_path=self.lock_path,
        )
        self.assertEqual(other.connect(), -30)
        other.close()

    def test_live_backend_error_stops(self) -> None:
        os.environ["GDPS_G1_LIVE"] = "1"
        self.adapter.live_token = "secret"
        self.adapter.enable_live("secret", "ENABLE LIVE MOTION")
        self.adapter.motion_authority_confirmed = True  # mock-only synthetic authorization
        self.adapter.allowed_live_fsm_ids = (501,)
        self.backend.next_code = -12
        code = self.adapter.send_velocity(VelocityCommand(vx=0.05, source="t"))
        self.assertEqual(code, -12)
        self.assertGreaterEqual(self.backend.stop_count, 1)
        os.environ.pop("GDPS_G1_LIVE", None)


class SafetyTests(unittest.TestCase):
    def test_stale_sensor_halts(self) -> None:
        sup = SafetySupervisor(sensor_timeout_s=0.05, require_sensor=True)
        now = time.monotonic()
        report = sup.evaluate(now)
        self.assertFalse(report.ok)
        self.assertEqual(report.halt, SafetyHalt.SENSOR_STALE)
        sup.mark_sensor()
        report = sup.evaluate(time.monotonic())
        self.assertTrue(report.ok)

    def test_manual_stop(self) -> None:
        sup = SafetySupervisor(require_sensor=False)
        sup.request_manual_stop()
        self.assertEqual(sup.evaluate().halt, SafetyHalt.MANUAL_STOP)

    def test_require_heartbeat_halts_before_first_pulse(self) -> None:
        sup = SafetySupervisor(require_sensor=False, require_heartbeat=True)
        report = sup.evaluate()
        self.assertFalse(report.ok)
        self.assertEqual(report.halt, SafetyHalt.HEARTBEAT_STALE)
        sup.mark_heartbeat()
        self.assertTrue(sup.evaluate().ok)


class NavigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nav = build_navigator()
        self.nav.safety.require_odom = False
        self.nav.safety.require_tf = False
        self.nav.safety.require_heartbeat = False

    def tearDown(self) -> None:
        self.nav.adapter.close()

    def _healthy_running(self) -> None:
        self.nav.on_scan(_scan(8.0))
        self.nav.on_pose(Pose2D(0.0, 0.0, 0.0, "odom"))
        self.nav.start()

    def test_config_loads_json(self) -> None:
        cfg = load_nav_config()
        self.assertEqual(cfg["mode"], "dry-run")
        self.assertLessEqual(cfg["max_vx"], 0.10)

    def test_obstacle_stop_zero_cmd(self) -> None:
        self._healthy_running()
        self.nav.on_scan(_scan(0.5))
        cmd = self.nav.step()
        self.assertTrue(cmd.is_zero())
        self.assertEqual(cmd.source, "obstacle_stop")

    def test_no_auto_forward_without_goal(self) -> None:
        self._healthy_running()
        cmd = self.nav.step()
        self.assertTrue(cmd.is_zero())
        self.assertIn("no_goal", cmd.source)

    def test_clear_forward_cruise_with_goal(self) -> None:
        self.nav.allow_auto_forward = True
        self._healthy_running()
        self.nav.set_goal(Pose2D(2.0, 0.0, 0.0, "odom"))
        cmd = self.nav.step()
        self.assertGreater(cmd.vx, 0.0)
        self.assertLessEqual(cmd.vx, 0.10)
        self.assertAlmostEqual(cmd.vy, 0.0)

    def test_goal_and_pause(self) -> None:
        self.nav.set_goal(Pose2D(1.0, 0.0, 0.0, "map"))
        self._healthy_running()
        self.nav.step()
        st = self.nav.pause()
        self.assertEqual(st.state, NavState.PAUSED)
        cmd = self.nav.step()
        self.assertTrue(cmd.is_zero())

    def test_unreachable_stops(self) -> None:
        self._healthy_running()
        self.nav.notify_path_unreachable()
        cmd = self.nav.step()
        self.assertTrue(cmd.is_zero())

    def test_no_sensor_fault(self) -> None:
        self.nav.on_pose(Pose2D(0, 0, 0, "odom"))
        self.nav.start()
        cmd = self.nav.step()
        self.assertTrue(cmd.is_zero())
        self.assertEqual(self.nav.state, NavState.FAULT)


class LateralDryRunTests(unittest.TestCase):
    def test_lateral_preview_not_rotation(self) -> None:
        nav = build_navigator()
        nav.safety.require_sensor = False
        nav.safety.require_heartbeat = False
        nav.safety.require_odom = False
        nav.safety.require_tf = False
        nav.on_scan(_scan(8.0))
        nav.on_pose(Pose2D(0, 0, 0, "odom"))
        nav.start()
        left = nav.preview_motion(MotionIntent.LATERAL_LEFT, speed_scale=1.0)
        rot = nav.preview_motion(MotionIntent.ROTATE_IN_PLACE, speed_scale=1.0)
        self.assertGreater(abs(left.vy), 0.0)
        self.assertAlmostEqual(left.wz, 0.0)
        self.assertGreater(abs(rot.wz), 0.0)
        self.assertAlmostEqual(rot.vy, 0.0)
        nav.adapter.close()


class MotionLockTests(unittest.TestCase):
    def test_second_lock_fails(self) -> None:
        path = Path(tempfile.mktemp(prefix="gdps_ml_"))
        a = MotionLock.acquire("a", path)
        with self.assertRaises(MotionLockError):
            MotionLock.acquire("b", path)
        a.release()


if __name__ == "__main__":
    unittest.main()
