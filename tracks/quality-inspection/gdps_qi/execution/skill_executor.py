from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from gdps_qi.adapters.camera import CameraAdapter
from gdps_qi.adapters.dex3_hand import DEX3_JOINT_COUNT, Dex3HandAdapter, HandCommand, GRASP_TABLET_PINCH
from gdps_qi.adapters.robot_hardware import RobotHardwareAdapter
from gdps_qi.evidence.evidence_recorder import EvidenceRecorder
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.planning.motion_safety_gate import MotionSafetyGate, SafetyContext
from gdps_qi.types import ActionEvidence, SkillPhase, SkillRequest, SkillResult


SkillFn = Callable[[SkillRequest, SafetyContext], SkillResult]


@dataclass
class SkillExecutor:
    robot: RobotHardwareAdapter
    hands: Dex3HandAdapter
    camera: CameraAdapter
    pose_estimator: PoseEstimator
    grasp_planner: GraspPlanner
    safety: MotionSafetyGate
    evidence: EvidenceRecorder
    _skills: Dict[str, SkillFn] = field(default_factory=dict)

    def register(self, name: str, fn: SkillFn) -> None:
        self._skills[name] = fn

    def run(self, request: SkillRequest, ctx: SafetyContext) -> SkillResult:
        ok_owner, msg = self.safety.acquire_owner(self.robot.owner)
        if not ok_owner:
            return SkillResult(status="ABORT", phase=SkillPhase.ABORT, errors=[msg])
        if request.skill_name not in self._skills:
            return SkillResult(
                status="ABORT",
                phase=SkillPhase.ABORT,
                errors=[f"unknown_skill:{request.skill_name}"],
            )
        started = time.time()
        result = self._skills[request.skill_name](request, ctx)
        ended = time.time()
        ev = ActionEvidence(
            task_id=ActionEvidence.new_task_id(),
            sample_id=request.sample_id,
            phase=result.phase.value,
            tf_version=ctx.tf_version,
            started_at=started,
            ended_at=ended,
            result=result.status,
            failure_reason=";".join(result.errors),
            payload={"skill": request.skill_name},
        )
        self.evidence.record(ev)
        result.evidence.append(ev)
        self.safety.release_owner(self.robot.owner)
        return result

    def dry_run_arm_and_hand(
        self,
        arm: str,
        joint_targets: tuple,
        hand_side: str,
        hand_targets: tuple,
        reason: str,
        allow_live: bool,
    ) -> tuple:
        ok_arm, msg_arm = self.robot.request_arm_joint_targets(
            arm, joint_targets, reason, allow_live
        )
        cmd = HandCommand(side=hand_side, joint_targets=hand_targets)
        ok_hand, msg_hand = self.hands.send_command(cmd, allow_live)
        return ok_arm and ok_hand, f"{msg_arm}|{msg_hand}"
