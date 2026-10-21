"""Mission budget and narration-timeout tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACK_ROOT = REPO_ROOT / "tracks" / "cultural-tourism"
for entry in (str(REPO_ROOT), str(TRACK_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from gdps_tourism.guide.budget import Budget  # noqa: E402
from gdps_tourism.guide.flow import (  # noqa: E402
    ActionKind,
    FlowConfig,
    GuideState,
    TourFlow,
)
from gdps_tourism.guide.stations import StationBook  # noqa: E402

STATIONS = TRACK_ROOT / "configs" / "stations.example.yaml"


class BudgetTest(unittest.TestCase):
    def test_remaining_and_narration_cap(self) -> None:
        budget = Budget(total_s=1800.0, reserve_s=180.0, max_narration_s=90.0)
        budget.start(now=0.0)
        self.assertEqual(budget.remaining_s(now=100.0), 1700.0)
        self.assertEqual(budget.remaining_work_s(now=100.0), 1520.0)
        # 8 stations left, plenty of time -> capped by max_narration_s
        self.assertEqual(budget.narration_cap_s(8, now=100.0), 90.0)
        # near the end: only 300s left, 2 stations -> tight cap
        self.assertLess(budget.narration_cap_s(2, now=1500.0), 40.0)
        self.assertGreaterEqual(budget.narration_cap_s(2, now=1500.0), 20.0)

    def test_station_accounting(self) -> None:
        budget = Budget(total_s=1800.0)
        budget.start(now=0.0)
        budget.start_station("S01", now=10.0)
        self.assertAlmostEqual(budget.station_elapsed_s(now=70.0), 60.0)
        spent = budget.finish_station(now=100.0)
        self.assertAlmostEqual(spent, 90.0)
        self.assertEqual(budget.per_station_s["S01"], 90.0)
        self.assertFalse(budget.station_overrun(now=100.0))
        budget.start_station("S02", now=0.0)
        self.assertTrue(budget.station_overrun(now=200.0))

    def test_mission_overrun(self) -> None:
        budget = Budget(total_s=600.0, reserve_s=180.0)
        budget.start(now=0.0)
        self.assertFalse(budget.mission_overrun(now=300.0))
        self.assertTrue(budget.mission_overrun(now=450.0))


class NarrationTimeoutTest(unittest.TestCase):
    def test_budget_timeout_advances_station(self) -> None:
        flow = TourFlow(StationBook.load(STATIONS), FlowConfig(narration_max_s=30.0))
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        started = flow.narration_started_at
        self.assertIsNotNone(started)
        self.assertEqual(flow.on_budget_check(now=started + 10.0), [])
        actions = flow.on_budget_check(now=started + 31.0)
        kinds = [action.kind for action in actions]
        self.assertIn(ActionKind.END_SIGNAL, kinds)
        self.assertIn(ActionKind.CANCEL_SPEECH, kinds)
        self.assertIn(ActionKind.NAVIGATE, kinds)
        end = [action for action in actions if action.kind is ActionKind.END_SIGNAL][0]
        self.assertEqual(end.payload["reason"], "narration_budget_timeout")
        self.assertEqual(end.payload["next_station_id"], "S02")
        self.assertEqual(flow.state, GuideState.NAVIGATING)
        self.assertEqual(flow.current_station_id, "S02")

    def test_no_timeout_when_listening(self) -> None:
        flow = TourFlow(StationBook.load(STATIONS), FlowConfig(narration_max_s=1.0))
        flow.start()
        flow.on_nav_arrived("S01")
        flow.on_observation(None)
        flow.on_speech_finished()
        self.assertEqual(flow.on_budget_check(now=(flow.last_action_at + 100.0)), [])


if __name__ == "__main__":
    unittest.main()
