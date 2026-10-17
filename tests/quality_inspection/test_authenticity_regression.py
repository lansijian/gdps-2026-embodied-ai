from __future__ import annotations

import os
import time
import unittest

import numpy as np

from gdps_qi.evidence.report_uploader import ReportUploader
from gdps_qi.mission.mission_controller import MissionController
from gdps_qi.skills.p3_centrifuge import CentrifugeState, register_p3_skills
from gdps_qi.planning.motion_safety_gate import MotionSafetyGate, SafetyContext
from gdps_qi.transforms.calibration_manager import CalibrationManager
from gdps_qi.transforms.transform_manager import TransformError, TransformManager
from gdps_qi.types import SkillPhase, SkillRequest, UploadServerStatus


class AuthenticityRegressionTests(unittest.TestCase):
    def test_p1_dry_run_never_pickup_confirmed(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()
        mc.register_simulation_workstation()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[200:280, 300:380] = 200
        mc.executor.camera.set_mock_frame(rgb)
        res = mc.executor.run(
            SkillRequest(
                skill_name="P1_PICK_TABLET_01",
                sample_id="01",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"use_mock_detections": True},
            ),
            mc._safety_context(),
        )
        self.assertNotEqual(res.verification.get("pickup_confirmed"), True)

    def test_p2_simulation_does_not_commit_without_verification(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()
        res = mc.executor.run(
            SkillRequest(
                skill_name="P2_PREP_SAMPLE",
                sample_id="01",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"allow_simulation_unscrew": True, "unscrew_steps": 2},
            ),
            mc._safety_context(),
        )
        self.assertEqual(res.status, "SAFE_HOLD")
        self.assertFalse(mc.p2_state.records["01"].committed)

    def test_p3_failure_does_not_pollute_slots(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()
        state = CentrifugeState()
        register_p3_skills(mc.executor, state)
        res = mc.executor.run(
            SkillRequest(
                skill_name="P3_LOAD_AND_ARM",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={
                    "load_order": ["01", "02", "03", "04", "05", "06"],
                    "masses_g": {"01": 10.0},
                    "all_sealed": True,
                    "lid_closed": True,
                },
            ),
            mc._safety_context(),
        )
        self.assertNotEqual(res.status, "COMMIT")
        self.assertEqual(len(state.loaded_slots), 0)

    def test_p3_missing_mass_not_treated_as_zero(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()
        state = CentrifugeState()
        register_p3_skills(mc.executor, state)
        order = ["01", "02", "03", "04", "05", "06"]
        res = mc.executor.run(
            SkillRequest(
                skill_name="P3_LOAD_AND_ARM",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={
                    "load_order": order,
                    "masses_g": {"01": 10.0, "04": 10.0},
                    "all_sealed": True,
                    "lid_closed": True,
                },
            ),
            mc._safety_context(),
        )
        self.assertIn("missing_mass", res.errors[0])

    def test_p4_force_stopped_blocked_in_field_mode(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "field"
        from gdps_qi.runtime.execution_mode import ExecutionMode

        mc = MissionController.build(execution_mode=ExecutionMode.FIELD)
        res = mc.executor.run(
            SkillRequest(
                skill_name="P4_UNLOAD",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"simulation_centrifuge_stopped": True},
            ),
            mc._safety_context(),
        )
        self.assertEqual(res.status, "SAFE_HOLD")

    def test_calibration_missing_blocks_contact(self) -> None:
        gate = MotionSafetyGate(calibration=CalibrationManager())
        ctx = SafetyContext(live_motion_authorized=True, calibration_ok=False)
        ok, _ = gate.authorize_phase(SkillPhase.EXECUTE, ctx, requires_contact=True)
        self.assertFalse(ok)

    def test_centrifuge_unknown_blocks_start(self) -> None:
        gate = MotionSafetyGate(calibration=CalibrationManager())
        ctx = SafetyContext(
            live_motion_authorized=True,
            calibration_ok=True,
            centrifuge_start_allowed=False,
        )
        ok, _ = gate.authorize_centrifuge_start(
            ctx, {"six_tubes_sealed": True, "ids_unique": True, "slots_ordered": True, "rotor_balanced": True, "lid_closed": True}
        )
        self.assertFalse(ok)

    def test_upload_pending_not_ack(self) -> None:
        up = ReportUploader(endpoint="")
        r = up.upload_batch([{"sample_id": "01"}], "k1")
        self.assertTrue(r.local_write_ok)
        self.assertEqual(r.server_status, UploadServerStatus.PENDING)
        self.assertFalse(r.ack)

    def test_tf_conflict_rejected(self) -> None:
        tf = TransformManager()
        t1 = np.eye(4)
        t2 = np.eye(4)
        t2[0, 3] = 1.0
        now = time.time()
        tf.set_transform("a", "b", t1, now, "c")
        with self.assertRaises(TransformError):
            tf.set_transform("a", "b", t2, now, "c")

    def test_skill_executor_releases_owner_on_exception(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()

        def boom(req, ctx):
            raise RuntimeError("x")

        mc.executor.register("BOOM", boom)
        mc.executor.run(
            SkillRequest("BOOM", "", {}, [], False, {}),
            mc._safety_context(),
        )
        ok, _ = mc.executor.safety.acquire_owner(mc.executor.robot.owner)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
