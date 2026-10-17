from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from gdps_qi.adapters.dex3_hand import GRASP_CAP_TWIST, GRASP_TUBE_BODY, HandCommand
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


@dataclass
class TubePrepRecord:
    sample_id: str
    mass_g: Optional[float] = None
    mass_recorded: bool = False
    cap_open_verified: bool = False
    tablet_insert_verified: bool = False
    cap_closed_verified: bool = False
    committed: bool = False
    sim_unscrew_steps_done: int = 0


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
    sc = request.safety_context

    if sc.get("verified_mass_g") is not None:
        rec.mass_g = float(sc["verified_mass_g"])
        rec.mass_recorded = True
    elif sc.get("mock_mass_g") is not None and sc.get("allow_simulation_mass"):
        rec.mass_g = float(sc["mock_mass_g"])
        rec.mass_recorded = False

    allow = request.allowed_actuation and ctx.live_motion_authorized
    ok_body, _ = executor.hands.send_command(
        HandCommand(side="left", joint_targets=GRASP_TUBE_BODY), allow_live=allow
    )
    ok_cap, _ = executor.hands.send_command(
        HandCommand(side="right", joint_targets=GRASP_CAP_TWIST), allow_live=allow
    )
    if not (ok_body and ok_cap):
        return SkillResult(status="RETRY", phase=SkillPhase.EXECUTE, errors=["hand_command_failed"])

    if sc.get("verified_cap_open"):
        rec.cap_open_verified = True
    if sc.get("verified_tablet_inserted"):
        rec.tablet_insert_verified = True
    if sc.get("verified_cap_closed"):
        rec.cap_closed_verified = True

    if sc.get("allow_simulation_unscrew"):
        steps = int(sc.get("unscrew_steps", 0))
        for i in range(steps):
            if sc.get("cap_stuck", False) and i > 0:
                return SkillResult(
                    status="RECOVER",
                    phase=SkillPhase.RECOVER,
                    errors=["cap_stuck_detected"],
                    verification={"step": i, "ledger_committed": False},
                )
        rec.sim_unscrew_steps_done = steps

    if not (rec.cap_open_verified and rec.tablet_insert_verified and rec.cap_closed_verified):
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.VERIFY,
            verification={
                "cap_open_verified": rec.cap_open_verified,
                "tablet_insert_verified": rec.tablet_insert_verified,
                "cap_closed_verified": rec.cap_closed_verified,
                "mass_recorded": rec.mass_recorded,
                "sim_unscrew_steps_done": rec.sim_unscrew_steps_done,
            },
            errors=["prep_not_verified"],
        )

    rec.committed = True
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        verification={
            "mass_g": rec.mass_g,
            "mass_recorded": rec.mass_recorded,
            "cap_open_verified": True,
            "tablet_insert_verified": True,
            "cap_closed_verified": True,
            "committed": True,
        },
        observations={"sim_unscrew_steps_done": rec.sim_unscrew_steps_done},
    )
