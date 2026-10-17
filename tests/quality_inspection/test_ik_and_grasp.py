from __future__ import annotations

import unittest

import numpy as np

from gdps_qi.kinematics.arm_kinematics import ArmKinematics
from gdps_qi.math_se3 import compose_transform, transform_from_pose
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.types import PoseRecord, Uncertainty


class IkTests(unittest.TestCase):
    def test_fk_ik_roundtrip(self) -> None:
        kin = ArmKinematics()
        seed = (0.1, -0.2, 0.3, -0.1, 0.2, 0.0, 0.1)
        target = kin.fk(seed)
        ik = kin.ik(target, seed)
        self.assertTrue(ik.success, ik.message)
        pos2, _ = kin.fk_wrist_pose(ik.joint_positions)
        self.assertLess(ik.position_error_m, 0.01)

    def test_unreachable_rejected(self) -> None:
        kin = ArmKinematics()
        far = transform_from_pose((5.0, 5.0, 5.0), (0, 0, 0, 1))
        ik = kin.ik(far, tuple(0.0 for _ in range(7)))
        self.assertFalse(ik.success)


class GraspPlannerTests(unittest.TestCase):
    def test_high_uncertainty_rejected(self) -> None:
        reg = ObjectRegistry.default_six_sample_layout()
        planner = GraspPlanner(registry=reg, kinematics=ArmKinematics())
        pose = PoseRecord(
            frame_id="robot_center",
            stamp=0.0,
            position=(0.3, 0.0, 0.4),
            orientation_xyzw=(0, 0, 0, 1),
            uncertainty=Uncertainty(0.01, 0.1),
            confidence=0.9,
        )
        plan = planner.plan_tablet_grasp(pose, allow_executable=True)
        self.assertFalse(plan.reachable)
        self.assertIn("uncertainty", plan.message)


if __name__ == "__main__":
    unittest.main()
