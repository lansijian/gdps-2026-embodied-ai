from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from gdps_qi.adapters.dex3_hand import GRASP_CAP_TWIST, GRASP_TUBE_BODY, HandCommand
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


@dataclass
class TubePrepRecord:
    sample_id: str
    mass_g: float = 0.0
    cap_open: bool = False
    tablet_inserted: bool = False
    cap_closed: bool = False
    committed: bool = False


@dataclass
class P2State:
    records: Dict[str, TubePrepRecord] = field(default_factory=dict)


def register_p2_skills(executor: SkillExecutor, state: P2State) -> None:
    executor.register("P2_PREP_SAMPLE", lambda req, ctx: _p2_prep_sample(executor, state, req, ctx))


def _p2_prep_sample(
    executor: SkillExecutor,
    state: P2State,
    request: SkillRequest,
    ctx: SafetyContext,
) -> SkillResult:
    sid = request.sample_id
    if sid not in executor.pose_estimator.registry.samples:
        return SkillResult(status="ABORT", phase=SkillPhase.ABORT, errors=["unknown_sample"])
    rec = state.records.setdefault(sid, TubePrepRecord(sample_id=sid))
    mass = float(request.safety_context.get("mock_mass_g", 12.3))
    rec.mass_g = mass
    allow = request.allowed_actuation and ctx.live_motion_authorized
    ok_body, _ = executor.hands.send_command(
        HandCommand(side="left", joint_targets=GRASP_TUBE_BODY), allow_live=allow
    )
    ok_cap, _ = executor.hands.send_command(
        HandCommand(side="right", joint_targets=GRASP_CAP_TWIST), allow_live=allow
    )
    if not (ok_body and ok_cap):
        return SkillResult(status="RETRY", phase=SkillPhase.EXECUTE, errors=["hand_command_failed"])
    # Conservative incremental unscrew simulation (no unbounded rotation).
    steps = int(request.safety_context.get("unscrew_steps", 3))
    for i in range(steps):
        if request.safety_context.get("cap_stuck", False) and i > 0:
            return SkillResult(
                status="RECOVER",
                phase=SkillPhase.RECOVER,
                errors=["cap_stuck_detected"],
                verification={"step": i},
            )
    rec.cap_open = True
    rec.tablet_inserted = True
    rec.cap_closed = True
    rec.committed = True
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        verification={
            "mass_g": rec.mass_g,
            "cap_open": rec.cap_open,
            "tablet_inserted": rec.tablet_inserted,
            "cap_closed": rec.cap_closed,
        },
        observations={"unscrew_steps": steps},
    )
