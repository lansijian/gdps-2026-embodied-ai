import unittest

from shared.robot_control.g1.loco_backend import UnitreeLocoBackend


class OlderSdk:
    def _Call(self, api_id, parameter):
        assert api_id == 7001 and parameter == "{}"
        return 0, '{"data":501}'


class GetterSdk:
    def GetFsmId(self):
        return 0, 802


class RejectedSdk:
    def _Call(self, api_id, parameter):
        return 7301, '{"data":0}'


class MalformedSdk:
    def _Call(self, api_id, parameter):
        return 0, '{"data":null}'


class LocoBackendStateTest(unittest.TestCase):
    def setUp(self):
        self.backend = UnitreeLocoBackend("eth0")

    def test_field_sdk_api_7001(self):
        self.backend._client = OlderSdk()
        self.assertEqual(self.backend.get_fsm_id(), (0, 501))

    def test_public_getter(self):
        self.backend._client = GetterSdk()
        self.assertEqual(self.backend.get_fsm_id(), (0, 802))

    def test_error_data_zero_not_success(self):
        self.backend._client = RejectedSdk()
        self.assertEqual(self.backend.get_fsm_id(), (7301, None))

    def test_malformed_fails_closed(self):
        self.backend._client = MalformedSdk()
        self.assertEqual(self.backend.get_fsm_id(), (-15, None))

    def test_no_client(self):
        self.assertEqual(self.backend.get_fsm_id(), (-2, None))


if __name__ == "__main__":
    unittest.main()
