from __future__ import annotations

from gdps_qi.adapters.dex3_hand import GRASP_OPEN, GRASP_TABLET_PINCH, HandCommand
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


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
    detections = executor.pose_estimator.detect_tablet_ids_from_mock(frame)
    ok_ids, msg_ids = executor.pose_estimator.validate_detections_unique(detections)
    if not ok_ids:
        return SkillResult(status="REFINE", phase=SkillPhase.VALIDATE, errors=[msg_ids])
    tablet_pose = executor.pose_estimator.tablet_pose_in_base(sample_id)
    plan = executor.grasp_planner.plan_tablet_grasp(tablet_pose)
    if not plan.reachable:
        return SkillResult(
            status="ABORT",
            phase=SkillPhase.ABORT,
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
    executor.hands.send_command(HandCommand(side=plan.hand, joint_targets=GRASP_OPEN), allow_live=False)
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        estimated_pose=tablet_pose,
        planned_waypoints=[plan.pregrasp, plan.grasp, plan.lift],
        verification={"pickup_confirmed": not allow, "mode": "dry_run_stub"},
        observations={"detections": len(detections), "sample_id": sample_id},
    )
