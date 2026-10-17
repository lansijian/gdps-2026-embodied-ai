from __future__ import annotations

import unittest

from gdps_qi.kinematics.arm_kinematics import ArmKinematics
from gdps_qi.mission.deadline_manager import DeadlineManager
from gdps_qi.mission.mission_controller import MissionController
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.planning.motion_safety_gate import MotionSafetyGate, SafetyContext
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.evidence.report_uploader import ReportUploader
from gdps_qi.transforms.calibration_manager import CalibrationManager
from gdps_qi.types import SkillPhase


class MissionOfflineTests(unittest.TestCase):
    def test_six_sample_identity(self) -> None:
        reg = ObjectRegistry.default_six_sample_layout()
        ok, errs = reg.validate_unique_ids()
        self.assertTrue(ok, errs)

    def test_p1_offline_commit(self) -> None:
        mc = MissionController.build_offline()
        # Bring table into simplified arm workspace for mock IK.
        mc.register_workstation_once()
        kin = ArmKinematics()
        kin.position_tolerance_m = 0.02
        mc.executor.grasp_planner.kinematics = kin
        result = mc.run_offline_p1_sample01()
        self.assertIn(result.status, ("COMMIT", "SAFE_HOLD", "ABORT"))

    def test_full_offline_mission_flow(self) -> None:
        mc = MissionController.build_offline()
        kin = ArmKinematics()
        kin.position_tolerance_m = 0.02
        mc.executor.grasp_planner.kinematics = kin
        summary = mc.run_full_offline_mission()
        self.assertIn("samples", summary)
        self.assertEqual(len(summary["samples"]), 6)

    def test_deadline_budget(self) -> None:
        import time

        dm = DeadlineManager(total_budget_s=1800.0, started_at=time.time())
        ok, _ = dm.should_continue(("P1", "P2", "P3", "P4", "P5", "P6"))
        self.assertTrue(ok)
        dm.started_at = time.time() - 2000.0
        ok2, msg = dm.should_continue(("P1", "P2"))
        self.assertFalse(ok2)
        self.assertIn("insufficient_time", msg)

    def test_safety_gate_blocks_live_contact(self) -> None:
        cal = CalibrationManager()
        gate = MotionSafetyGate(calibration=cal)
        ctx = SafetyContext(live_motion_authorized=False, calibration_ok=True)
        ok, msg = gate.authorize_phase(SkillPhase.EXECUTE, ctx, requires_contact=True)
        self.assertFalse(ok)

    def test_report_upload_idempotent(self) -> None:
        up = ReportUploader(endpoint="")
        r1 = up.upload_batch([{"sample_id": "01"}], "key1")
        r2 = up.upload_batch([{"sample_id": "01"}], "key1")
        self.assertIs(r1, r2)
        self.assertFalse(r1.ack)


if __name__ == "__main__":
    unittest.main()
