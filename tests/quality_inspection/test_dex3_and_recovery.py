from __future__ import annotations

import unittest

from gdps_qi.adapters.dex3_hand import (
    DEX3_JOINT_COUNT,
    Dex3HandAdapter,
    GRASP_TABLET_PINCH,
    HandCommand,
)
from gdps_qi.skills.p2_tube import P2State, register_p2_skills
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.mission.mission_controller import MissionController
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillRequest


class Dex3Tests(unittest.TestCase):
    def test_grasp_template_joint_count(self) -> None:
        self.assertEqual(len(GRASP_TABLET_PINCH), DEX3_JOINT_COUNT)

    def test_hand_dry_run_command(self) -> None:
        hand = Dex3HandAdapter()
        hand.connect()
        ok, msg = hand.send_command(
            HandCommand(side="left", joint_targets=GRASP_TABLET_PINCH), allow_live=False
        )
        self.assertTrue(ok)
        self.assertEqual(len(hand.command_log), 1)


class RecoveryTests(unittest.TestCase):
    def test_cap_stuck_recovery(self) -> None:
        mc = MissionController.build_offline()
        register_p2_skills(mc.executor, mc.p2_state)
        ctx = SafetyContext(calibration_ok=True)
        res = mc.executor.run(
            SkillRequest(
                skill_name="P2_PREP_SAMPLE",
                sample_id="01",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"cap_stuck": True, "unscrew_steps": 3},
            ),
            ctx,
        )
        self.assertEqual(res.status, "RECOVER")


if __name__ == "__main__":
    unittest.main()
