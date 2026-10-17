from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


@dataclass
class CentrifugeState:
    loaded_slots: Dict[int, str] = field(default_factory=dict)
    masses_g: Dict[str, float] = field(default_factory=dict)
    running: bool = False
    stopped: bool = True


def register_p3_skills(executor: SkillExecutor, state: CentrifugeState) -> None:
    executor.register("P3_LOAD_AND_ARM", lambda req, ctx: _p3_load(executor, state, req, ctx))


def _p3_load(
    executor: SkillExecutor,
    state: CentrifugeState,
    request: SkillRequest,
    ctx: SafetyContext,
) -> SkillResult:
    order: List[str] = request.safety_context.get("load_order", [])
    if len(order) != 6:
        return SkillResult(status="ABORT", phase=SkillPhase.VALIDATE, errors=["need_six_tubes"])
    if len(set(order)) != 6:
        return SkillResult(status="ABORT", phase=SkillPhase.VALIDATE, errors=["duplicate_tube_id"])
    for idx, sid in enumerate(order, start=1):
        state.loaded_slots[idx] = sid
    masses = request.safety_context.get("masses_g", {})
    state.masses_g = {str(k): float(v) for k, v in masses.items()}
    pairs = [(1, 4), (2, 5), (3, 6)]
    for a, b in pairs:
        ma = state.masses_g.get(state.loaded_slots.get(a, ""), 0.0)
        mb = state.masses_g.get(state.loaded_slots.get(b, ""), 0.0)
        if abs(ma - mb) > float(request.safety_context.get("balance_tolerance_g", 0.5)):
            return SkillResult(
                status="SAFE_HOLD",
                phase=SkillPhase.SAFE_HOLD,
                errors=["rotor_imbalance"],
                verification={"pair": (a, b), "delta_g": abs(ma - mb)},
            )
    checks = {
        "six_tubes_sealed": bool(request.safety_context.get("all_sealed", False)),
        "ids_unique": len(set(order)) == 6,
        "slots_ordered": list(state.loaded_slots.keys()) == list(range(1, 7)),
        "rotor_balanced": True,
        "lid_closed": bool(request.safety_context.get("lid_closed", False)),
    }
    ok, msg = executor.safety.authorize_centrifuge_start(ctx, checks)
    if not ok:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.AUTHORIZE,
            errors=[msg],
            verification=checks,
        )
    state.running = bool(ctx.centrifuge_start_allowed and ctx.live_motion_authorized)
    state.stopped = not state.running
    return SkillResult(
        status="COMMIT" if not state.running else "COMMIT",
        phase=SkillPhase.COMMIT,
        verification={"loaded": state.loaded_slots, "start_armed": state.running},
    )
