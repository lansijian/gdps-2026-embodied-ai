from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel
from gdps_qi.mission.mission_controller import MissionController
from gdps_qi.types import SkillRequest


class Phase3DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_dry_run_json(self) -> None:
        script = ROOT / "scripts/g1/qi_hardware_diagnostics.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertIn("devices", data)
        self.assertEqual(data["mode"], "dry_run_schema")
        self.assertIn("head_camera", data["devices"])

    def test_p1_localize_01_simulation(self) -> None:
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        mc = MissionController.build_offline()
        mc.register_simulation_workstation()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[100:380, 120:520] = 210
        mc.executor.camera.set_mock_frame(rgb)
        res = mc.executor.run(
            SkillRequest(
                skill_name="P1_LOCALIZE_01",
                sample_id="01",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"use_mock_detections": True, "allow_relative_table": True},
            ),
            mc._safety_context(),
        )
        self.assertEqual(res.status, "PLAN_READONLY_OK")
        self.assertEqual(res.verification.get("tier"), "RELATIVE_TABLE")
        self.assertFalse(res.verification.get("executable_plan"))


class UrdfPinocchioTests(unittest.TestCase):
    def test_minimal_urdf_fk_if_pinocchio(self) -> None:
        try:
            import pinocchio  # noqa: F401
        except ImportError:
            self.skipTest("pinocchio not installed")
        urdf = ROOT / "tests/fixtures/minimal_2link.urdf"
        m = G1UrdfModel(str(urdf), base_frame="pelvis")
        self.assertTrue(m.load())
        q = m.set_named_joints({"waist_yaw_joint": 0.1, "left_shoulder_pitch_joint": -0.2})
        t = m.frame_placement("left_wrist_yaw_link", q)
        self.assertAlmostEqual(float(t[2, 3]), 0.3, places=2)


if __name__ == "__main__":
    unittest.main()
