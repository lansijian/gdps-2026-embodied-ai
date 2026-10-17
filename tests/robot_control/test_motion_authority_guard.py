"""Offline regression tests. NEVER sends commands to G1 hardware."""
import math
import os
import tempfile
import unittest
from pathlib import Path

from shared.robot_control.g1.adapter import G1MotionAdapter, MotionMode
from shared.robot_control.g1.command import VelocityCommand
from shared.robot_control.g1.loco_backend import UnitreeLocoBackend
from shared.robot_control.g1.mock_backend import MockLocoBackend


class FakeSdkClient:
    def __init__(self):
        self.answers = {7001: (0, '{"data":802}'), 7002: (0, '{"data":0}'),
                        7003: (7301, '{"data":0}')}
        self.commands = []
        self.stop_code = 0

    def _Call(self, api_id, parameter):
        return self.answers[api_id]

    def SetVelocity(self, *args):
        self.commands.append(args)
        return self.stop_code


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSdkClient()
        self.backend = UnitreeLocoBackend('eth0')
        self.backend._client = self.sdk

    def test_legacy_missing_public_get_fsm(self):
        self.assertEqual(self.backend.get_fsm_id(), (0, 802))

    def test_zero_is_valid_fsm(self):
        self.sdk.answers[7001] = (0, '{"data":0}')
        self.assertEqual(self.backend.get_fsm_id(), (0, 0))

    def test_read_fsm_mode(self):
        self.assertEqual(self.backend.get_fsm_mode(), (0, 0))

    def test_error_7301_never_parses_payload(self):
        self.assertEqual(self.backend.get_balance_mode(), (7301, None))

    def test_malformed_rpc_payload(self):
        self.sdk.answers[7001] = (0, '{"message":"no-data"}')
        self.assertEqual(self.backend.get_fsm_id(), (-15, None))

    def test_public_get_fsm_preferred(self):
        self.sdk.GetFsmId = lambda: (0, 501)
        self.assertEqual(self.backend.get_fsm_id(), (0, 501))

    def test_zero_velocity_ack_missing_is_error(self):
        self.sdk.stop_code = None
        self.assertEqual(self.backend.stop_move(), -17)

    def test_set_velocity_ack_success_not_physical_claim(self):
        self.assertEqual(self.backend.set_velocity(VelocityCommand(vx=0.05)), 0)
        self.assertEqual(len(self.sdk.commands), 1)

    def test_set_velocity_rejects_nan(self):
        self.assertEqual(self.backend.set_velocity(VelocityCommand(vx=float('nan'))), -16)


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.backend = MockLocoBackend()
        self.adapter = G1MotionAdapter(backend=self.backend,
            lock_path=str(Path(self.tempdir.name) / 'motion.lock'),
            owner='offline-test', live_token='test-token')
        self.assertEqual(self.adapter.connect(), 0)

    def tearDown(self):
        self.adapter.close()
        os.environ.pop('GDPS_G1_LIVE', None)
        self.tempdir.cleanup()

    def live(self):
        os.environ['GDPS_G1_LIVE'] = '1'
        self.adapter.enable_live('test-token', 'ENABLE LIVE MOTION')

    def authorize_mock(self, fsm=501):
        self.adapter.motion_authority_confirmed = True
        self.adapter.allowed_live_fsm_ids = (fsm,)

    def test_default_dry_run_never_sends_velocity(self):
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.1)), 0)
        self.assertEqual(self.backend.history, [])

    def test_live_802_denied_without_authority(self):
        self.live()
        self.backend.fsm_id = 802
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.06)), -40)
        self.assertEqual(self.backend.history, [])

    def test_mismatch_fsm_denied(self):
        self.live()
        self.authorize_mock(fsm=501)
        self.backend.fsm_id = 802
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.06)), -42)
        self.assertEqual(self.backend.history, [])

    def test_query_failure_denied(self):
        self.live()
        self.authorize_mock()
        self.backend.fsm_query_code = 3102
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.06)), -41)

    def test_explicit_auth_allows_mock_only_no_motion_claim(self):
        self.live()
        self.authorize_mock()
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.06)), 0)
        self.assertFalse(self.adapter.physical_motion_verified)
        self.assertEqual(len(self.backend.history), 1)

    def test_invalid_float_denied(self):
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=float('nan'))), -33)
        self.assertEqual(self.backend.history, [])

    def test_duration_too_long_denied(self):
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(duration_s=2.0)), -33)

    def test_watchdog_stops_exactly_once(self):
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.04)), 0)
        last = self.adapter.last_command_monotonic
        self.assertEqual(self.adapter.watchdog_tick(now=last+1.0), 0)
        self.assertIsNone(self.adapter.watchdog_tick(now=last+2.0))

    def test_live_backend_failure_stop_does_not_hide_failure(self):
        self.live()
        self.authorize_mock()
        self.backend.next_code = -12
        self.assertEqual(self.adapter.send_velocity(VelocityCommand(vx=0.05)), -12)
        self.assertEqual(self.adapter.last_return_code, -12)
        self.assertGreaterEqual(self.backend.stop_count, 1)

    def test_live_stop_not_fsm_change(self):
        self.live()
        self.assertEqual(self.adapter.stop('manual'), 0)
        self.assertEqual(self.backend.stop_count, 1)

    def test_exclusive_lock(self):
        other = G1MotionAdapter(backend=MockLocoBackend(),
            lock_path=self.adapter.lock_path,owner='other')
        self.assertEqual(other.connect(), -30)
        other.close()

    def test_move_once_dry_run_no_sleep_and_no_hw(self):
        self.assertEqual(self.adapter.move_once(VelocityCommand(vx=0.04)), 0)
        self.assertEqual(self.backend.history, [])


if __name__ == '__main__':
    unittest.main()
