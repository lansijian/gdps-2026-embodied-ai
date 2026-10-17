from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple, Union

import numpy as np

from gdps_qi.kinematics.arm_kinematics import ArmKinematics, IkResult
from gdps_qi.kinematics.kinematics_backend import KinematicsBackend, SimplifiedTestKinematics
from gdps_qi.math_se3 import compose_transform, invert_transform, transform_from_pose
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.types import PoseRecord


HandChoice = Literal["left", "right"]
KinematicsModel = Union[ArmKinematics, KinematicsBackend]


@dataclass
class GraspPlan:
    hand: HandChoice
    pregrasp: PoseRecord
    grasp: PoseRecord
    lift: PoseRecord
    joint_seed: Tuple[float, ...]
    reachable: bool
    hardware_joint_targets_allowed: bool
    executable_plan: bool
    message: str = ""


@dataclass
class GraspPlanner:
    registry: ObjectRegistry
    kinematics: KinematicsModel
    max_uncertainty_m: float = 0.004

    def choose_hand(self, object_position_base: Tuple[float, float, float]) -> HandChoice:
        return "left" if object_position_base[1] >= 0.0 else "right"

    def _ik(self, target_t: np.ndarray, seed: Tuple[float, ...], side: str = "left") -> IkResult:
        if isinstance(self.kinematics, KinematicsBackend):
            return self.kinematics.ik(target_t, seed, side=side)
        return self.kinematics.ik(target_t, seed)

    def _hardware_allowed(self) -> bool:
        if isinstance(self.kinematics, KinematicsBackend):
            return self.kinematics.allow_hardware_joint_targets()
        return False

    def plan_tablet_grasp(
        self,
        tablet_pose_base: PoseRecord,
        template_name: str = "tablet_edge_pinch",
        t_wrist_tcp: Optional[np.ndarray] = None,
        allow_executable: bool = False,
    ) -> GraspPlan:
        template = self.registry.grasp_templates[template_name]
        uncertainty_high = (
            tablet_pose_base.uncertainty is not None
            and tablet_pose_base.uncertainty.position_m > self.max_uncertainty_m
        )
        if uncertainty_high and allow_executable:
            return GraspPlan(
                hand="left",
                pregrasp=tablet_pose_base,
                grasp=tablet_pose_base,
                lift=tablet_pose_base,
                joint_seed=tuple(0.0 for _ in range(7)),
                reachable=False,
                hardware_joint_targets_allowed=False,
                executable_plan=False,
                message="uncertainty_too_high",
            )
        if template.min_edge_gap_m < 0.0008:
            return GraspPlan(
                hand="left",
                pregrasp=tablet_pose_base,
                grasp=tablet_pose_base,
                lift=tablet_pose_base,
                joint_seed=tuple(0.0 for _ in range(7)),
                reachable=False,
                hardware_joint_targets_allowed=False,
                executable_plan=False,
                message="insufficient_edge_gap",
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
        wrist_tcp = t_wrist_tcp if (t_wrist_tcp is not None and allow_executable) else np.eye(4)
        t_base_wrist_grasp = compose_transform(t_base_grasp, invert_transform(wrist_tcp))
        t_base_wrist_pre = compose_transform(t_base_pre, invert_transform(wrist_tcp))
        t_base_wrist_lift = compose_transform(lift, invert_transform(wrist_tcp))
        seed = tuple(0.0 for _ in range(7))
        hw_ok = allow_executable and self._hardware_allowed()
        side = hand
        ok_pre, ik_pre = self._segment_ok(t_base_wrist_pre, seed, "pregrasp", side)
        ok_gr, ik_gr = self._segment_ok(
            t_base_wrist_grasp, ik_pre.joint_positions if ok_pre else seed, "grasp", side
        )
        ok_lift, ik_lift = self._segment_ok(
            t_base_wrist_lift, ik_gr.joint_positions if ok_gr else seed, "lift", side
        )
        reachable = ok_pre and ok_gr and ok_lift
        pre_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_pre, tablet_pose_base)
        grasp_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_grasp, tablet_pose_base)
        lift_pose = self._pose_from_transform(tablet_pose_base.frame_id, t_base_wrist_lift, tablet_pose_base)
        joint_seed = ik_gr.joint_positions if reachable else seed
        if reachable and not hw_ok:
            joint_seed = tuple(0.0 for _ in range(7))
        msg = "ok" if reachable else f"segment_failed:{ik_gr.message}"
        if uncertainty_high and reachable:
            msg = "uncertainty_high_readonly"
        return GraspPlan(
            hand=hand,
            pregrasp=pre_pose,
            grasp=grasp_pose,
            lift=lift_pose,
            joint_seed=joint_seed,
            reachable=reachable,
            hardware_joint_targets_allowed=hw_ok and reachable,
            executable_plan=hw_ok and reachable and allow_executable,
            message=msg,
        )

    def _segment_ok(
        self, target_t: np.ndarray, seed: Tuple[float, ...], label: str, side: str
    ) -> Tuple[bool, IkResult]:
        if isinstance(self.kinematics, KinematicsBackend):
            return self.kinematics.check_segment_reachable(seed, target_t, label, side=side)
        ik = self._ik(target_t, seed)
        return ik.success, ik

    def _pose_from_transform(self, frame_id: str, t: np.ndarray, ref: PoseRecord) -> PoseRecord:
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
            provenance=ref.provenance,
        )
