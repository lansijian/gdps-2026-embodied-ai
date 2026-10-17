from __future__ import annotations

import unittest

from gdps_qi.mission.mission_flow import FlowNode, MissionFlowState, default_specs


class MissionFlowTests(unittest.TestCase):
    def test_happy_path_advances(self) -> None:
        specs = default_specs()
        st = MissionFlowState()
        self.assertEqual(st.current, FlowNode.NAVIGATE_TO_STATION)
        node, phase = st.transition(True, specs)
        self.assertEqual(node, FlowNode.STABILIZE_BODY)
        self.assertEqual(phase, "execute")

    def test_failure_retries_then_safe_hold(self) -> None:
        specs = default_specs()
        st = MissionFlowState()
        st.transition(False, specs)
        self.assertEqual(st.retries[FlowNode.NAVIGATE_TO_STATION], 1)
        _, phase = st.transition(False, specs)
        self.assertEqual(phase, "safe_hold")
        self.assertTrue(st.safe_hold)

    def test_repeat_six_loops_p1(self) -> None:
        specs = default_specs()
        st = MissionFlowState(current=FlowNode.REPEAT_6, sample_index=1)
        st.transition(True, specs)
        self.assertEqual(st.sample_index, 2)
        self.assertEqual(st.current, FlowNode.P1_PICK_AND_WEIGH)


if __name__ == "__main__":
    unittest.main()
