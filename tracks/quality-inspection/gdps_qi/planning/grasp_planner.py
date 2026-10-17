from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple

import numpy as np

from gdps_qi.kinematics.arm_kinematics import ArmKinematics
from gdps_qi.math_se3 import compose_transform, invert_transform, transform_from_pose
from gdps_qi.registry.object_registry import GraspTemplate, ObjectRegistry
from gdps_qi.types import PoseRecord, Uncertainty


HandChoice = Literal["left", "right"]


@dataclass
class GraspPlan:
    hand: HandChoice
    pregrasp: PoseRecord
    grasp: PoseRecord
    lift: PoseRecord
    joint_seed: Tuple[float, ...]
    reachable: bool
    message: str = ""


@dataclass
class GraspPlanner:
    registry: ObjectRegistry
    kinematics: ArmKinematics
    max_uncertainty_m: float = 0.004

    def choose_hand(self, object_position_base: Tuple[float, float, float]) -> HandChoice:
        return "left" if object_position_base[1] >= 0.0 else "right"

    def plan_tablet_grasp(
        self,
        tablet_pose_base: PoseRecord,
        template_name: str = "tablet_edge_pinch",
        t_wrist_tcp: Optional[np.ndarray] = None,
    ) -> GraspPlan:
        template = self.registry.grasp_templates[template_name]
        if tablet_pose_base.uncertainty and tablet_pose_base.uncertainty.position_m > self.max_uncertainty_m:
            return GraspPlan(
                hand="left",
                pregrasp=tablet_pose_base,
                grasp=tablet_pose_base,
                lift=tablet_pose_base,
                joint_seed=tuple(0.0 for _ in range(7)),
                reachable=False,
                message="uncertainty_too_high",
            )
        t_base_object = transform_from_pose(tablet_pose_base.position, tablet_pose_base.orientation_xyzw)
        t_object_grasp = transform_from_pose(
            template.t_object_grasp_position,
            template.t_object_grasp_orientation_xyzw,
        )
        t_base_grasp = compose_transform(t_base_object, t_object_grasp)
        approach = np.array(template.approach_offset_table_m)
        t_base_pre = t_base_grasp.copy()
        t_base_pre[:3, 3] += approach
        lift = t_base_grasp.copy()
        lift[:3, 3] += np.array([0.0, 0.0, 0.05])
        hand = template.hand if template.hand != "auto" else self.choose_hand(tablet_pose_base.position)
        wrist_tcp = t_wrist_tcp if t_wrist_tcp is not None else np.eye(4)
        t_base_wrist_grasp = compose_transform(t_base_grasp, invert_transform(wrist_tcp))
        t_base_wrist_pre = compose_transform(t_base_pre, invert_transform(wrist_tcp))
        t_base_wrist_lift = compose_transform(lift, invert_transform(wrist_tcp))
        seed = tuple(0.0 for _ in range(7))
        ik = self.kinematics.ik(t_base_wrist_grasp, seed)
        pre_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_pre, tablet_pose_base)
        grasp_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_grasp, tablet_pose_base)
        lift_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_lift, tablet_pose_base)
        return GraspPlan(
            hand=hand,
            pregrasp=pre_pose,
            grasp=grasp_pose,
            lift=lift_pose,
            joint_seed=ik.joint_positions if ik.success else seed,
            reachable=ik.success,
            message=ik.message if ik.success else f"ik_failed:{ik.message}",
        )

    def _pose_from_transform(
        self, frame_id: str, t: np.ndarray, ref: PoseRecord
    ) -> PoseRecord:
        from gdps_qi.math_se3 import rot_to_quat

        q = rot_to_quat(t[:3, :3])
        p = t[:3, 3]
        return PoseRecord(
            frame_id=frame_id,
            stamp=ref.stamp,
            position=(float(p[0]), float(p[1]), float(p[2])),
            orientation_xyzw=(float(q[0]), float(q[1]), float(q[2]), float(q[3])),
            object_id=ref.object_id,
            calibration_id=ref.calibration_id,
            uncertainty=ref.uncertainty,
            confidence=ref.confidence,
            source="grasp_planner",
        )
