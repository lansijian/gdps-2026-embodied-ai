from __future__ import annotations

from gdps_qi.adapters.dex3_hand import GRASP_TABLET_PINCH, HandCommand
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.runtime.execution_mode import allow_simulation_assets
from gdps_qi.types import DataProvenance, SkillPhase, SkillRequest, SkillResult


def register_p1_skills(executor: SkillExecutor) -> None:
    def pick_tablet_01(request: SkillRequest, ctx: SafetyContext) -> SkillResult:
        return _p1_pick_tablet(executor, request, ctx, sample_id="01")

    executor.register("P1_PICK_TABLET_01", pick_tablet_01)
    executor.register("P1_PICK_TABLET", _p1_pick_tablet_generic(executor))


def _p1_pick_tablet_generic(executor: SkillExecutor):
    def fn(request: SkillRequest, ctx: SafetyContext) -> SkillResult:
        return _p1_pick_tablet(executor, request, ctx, sample_id=request.sample_id)

    return fn


def _p1_pick_tablet(
    executor: SkillExecutor,
    request: SkillRequest,
    ctx: SafetyContext,
    sample_id: str,
) -> SkillResult:
    frame = executor.camera.grab()
    if frame is None:
        return SkillResult(status="RETRY", phase=SkillPhase.OBSERVE, errors=["no_camera_frame"])

    use_mock = allow_simulation_assets() and request.safety_context.get("use_mock_detections")
    if use_mock:
        detections = executor.pose_estimator.detect_tablet_ids_from_mock(frame)
        det_msg = "mock_detections"
    else:
        detections, det_msg = executor.pose_estimator.detect_tablets_from_rgb(frame)
        if det_msg != "ok":
            return SkillResult(
                status="REFINE",
                phase=SkillPhase.OBSERVE,
                errors=[det_msg],
                observations={"detection_count": len(detections)},
            )

    ok_ids, msg_ids = executor.pose_estimator.validate_detections_for_target(detections, sample_id)
    if not ok_ids:
        return SkillResult(status="REFINE", phase=SkillPhase.VALIDATE, errors=[msg_ids])

    target_det = next(d for d in detections if d.label == sample_id)
    tablet_pose, pose_msg = executor.pose_estimator.tablet_pose_from_detection(
        sample_id, frame, target_det
    )
    if pose_msg != "ok":
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.LOCALIZE,
            errors=[pose_msg],
            observations={"provenance": tablet_pose.provenance.value},
        )

    plan = executor.grasp_planner.plan_tablet_grasp(tablet_pose)
    if not plan.reachable:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.PLAN,
            estimated_pose=tablet_pose,
            errors=[plan.message],
        )

    ok_auth, msg_auth = executor.safety.authorize_phase(
        SkillPhase.EXECUTE, ctx, plan.grasp, requires_contact=True
    )
    if not ok_auth:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.SAFE_HOLD,
            planned_waypoints=[plan.pregrasp, plan.grasp, plan.lift],
            errors=[msg_auth],
        )

    allow = request.allowed_actuation and ctx.live_motion_authorized
    if allow and not plan.hardware_joint_targets_allowed:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.EXECUTE,
            errors=["hardware_joint_targets_not_allowed_without_verified_kinematics"],
        )

    ok, msg = executor.dry_run_arm_and_hand(
        plan.hand,
        plan.joint_seed,
        plan.hand,
        GRASP_TABLET_PINCH,
        reason=f"P1_pick_{sample_id}",
        allow_live=allow,
    )
    if not ok:
        return SkillResult(status="RETRY", phase=SkillPhase.EXECUTE, errors=[msg])

    pickup_confirmed = bool(
        request.safety_context.get("verified_pickup_visual")
        and request.safety_context.get("verified_pickup_visual") is True
    )
    verification = {
        "pickup_confirmed": pickup_confirmed,
        "mode": "dry_run" if not allow else "live_requested",
        "detection_source": det_msg,
        "pose_provenance": tablet_pose.provenance.value,
    }
    if not pickup_confirmed:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.VERIFY,
            estimated_pose=tablet_pose,
            planned_waypoints=[plan.pregrasp, plan.grasp, plan.lift],
            verification=verification,
            errors=["pickup_not_verified"],
        )

    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        estimated_pose=tablet_pose,
        planned_waypoints=[plan.pregrasp, plan.grasp, plan.lift],
        verification=verification,
        observations={"sample_id": sample_id, "confidence": target_det.confidence},
    )
