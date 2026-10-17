import json
import math
import tempfile
import unittest
from pathlib import Path

from shared.robot_control.g1.teach_trajectory import (
    ARM_IDS, InvalidTeachingData, load_teaching_session,
    parse_observation, smooth_observed_angles, summarize_session,
)


def row(t, q=0.1, mode=5):
    return {"source": "rt/lowstate", "record_type": "arm_observation",
            "timestamp_s": t, "mode_machine": mode, "joints": list(ARM_IDS),
            "q": [q] * 14, "dq": [0.0] * 14, "tau_est": [0.0] * 14}


class TeachTrajectoryTest(unittest.TestCase):
    def test_valid_record(self):
        item = parse_observation(row(1.0))
        self.assertEqual(len(item.q), 14)

    def test_reject_unverified_mode(self):
        with self.assertRaises(InvalidTeachingData):
            parse_observation(row(1.0, mode=6))

    def test_reject_wrong_joint_map(self):
        bad = row(1.0)
        bad["joints"][0] = 12
        with self.assertRaises(InvalidTeachingData):
            parse_observation(bad)

    def test_reject_nonfinite(self):
        bad = row(1.0)
        bad["q"][3] = math.nan
        with self.assertRaises(InvalidTeachingData):
            parse_observation(bad)

    def test_monotonic_timestamps_and_gap(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "demo.jsonl"
            p.write_text("\n".join(json.dumps(row(t)) for t in [1., 1.05, 1.10]))
            self.assertEqual(len(load_teaching_session(str(p))), 3)
            p.write_text("\n".join(json.dumps(row(t)) for t in [1., 1.05, 1.4]))
            with self.assertRaises(InvalidTeachingData):
                load_teaching_session(str(p))

    def test_kalman_is_offline_bounded_by_observations(self):
        samples = [parse_observation(row(t, q)) for t, q in
                   [(1.0, 0.0), (1.05, 0.4), (1.10, 0.2)]]
        out = smooth_observed_angles(samples)
        self.assertEqual(len(out), 3)
        self.assertGreater(out[-1][0], 0.0)
        self.assertLess(out[-1][0], 0.4)
        meta = summarize_session(samples)
        self.assertFalse(meta["motor_write_allowed"])
        self.assertEqual(meta["status"], "OFFLINE_OBSERVATION_ONLY")

    def test_reject_malformed(self):
        with self.assertRaises(InvalidTeachingData):
            parse_observation({})
        with self.assertRaises(InvalidTeachingData):
            smooth_observed_angles([])


if __name__ == "__main__":
    unittest.main()
