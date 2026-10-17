from __future__ import annotations

from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.perception.p1_tablet_localize import localize_tablet_01
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


def register_p1_localize_skills(executor: SkillExecutor, g1_tf: object) -> None:
    def localize_01(request: SkillRequest, ctx: SafetyContext) -> SkillResult:
        frame = executor.camera.grab()
        if frame is None:
            return SkillResult(status="RETRY", phase=SkillPhase.OBSERVE, errors=["no_camera_frame"])
        if request.safety_context.get("use_mock_detections"):
            detections = executor.pose_estimator.detect_tablet_ids_from_mock(frame)
            executor.pose_estimator.validate_detections_for_target(detections, "01")
        result = localize_tablet_01(
            sample_id="01",
            frame=frame,
            pose_estimator=executor.pose_estimator,
            grasp_planner=executor.grasp_planner,
            g1_tf=g1_tf,
            require_calibrated_table=not request.safety_context.get("allow_relative_table", False),
        )
        return SkillResult(
            status=result.status,
            phase=SkillPhase.PLAN if result.status == "PLAN_OK" else SkillPhase.SAFE_HOLD,
            estimated_pose=result.pose,
            planned_waypoints=(
                [result.grasp_plan.pregrasp, result.grasp_plan.grasp, result.grasp_plan.lift]
                if result.grasp_plan
                else []
            ),
            verification={
                "tier": result.tier.value,
                "diagnostics": result.diagnostics,
                "hardware_joint_targets_allowed": (
                    result.grasp_plan.hardware_joint_targets_allowed if result.grasp_plan else False
                ),
            },
            errors=result.errors,
            observations={"detection_label": result.detection.label if result.detection else ""},
        )

    executor.register("P1_LOCALIZE_01", localize_01)
