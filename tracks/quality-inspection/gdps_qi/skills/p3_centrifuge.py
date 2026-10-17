from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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


def _require_mass(masses: Dict[str, float], tube_id: str) -> Tuple[bool, float, str]:
    if tube_id not in masses:
        return False, 0.0, f"missing_mass:{tube_id}"
    val = masses[tube_id]
    if val is None:
        return False, 0.0, f"missing_mass:{tube_id}"
    return True, float(val), "ok"


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

    masses_raw = request.safety_context.get("masses_g", {})
    masses: Dict[str, float] = {}
    for sid in order:
        ok, val, msg = _require_mass(masses_raw, sid)
        if not ok:
            return SkillResult(status="ABORT", phase=SkillPhase.VALIDATE, errors=[msg])

        masses[sid] = val

    proposed_slots = {idx: sid for idx, sid in enumerate(order, start=1)}
    pairs = [(1, 4), (2, 5), (3, 6)]
    tol = float(request.safety_context.get("balance_tolerance_g", 0.5))
    for a, b in pairs:
        sa = proposed_slots[a]
        sb = proposed_slots[b]
        if abs(masses[sa] - masses[sb]) > tol:
            return SkillResult(
                status="SAFE_HOLD",
                phase=SkillPhase.VALIDATE,
                errors=["rotor_imbalance"],
                verification={"pair": (a, b), "delta_g": abs(masses[sa] - masses[sb])},
            )

    checks = {
        "six_tubes_sealed": bool(request.safety_context.get("all_sealed", False)),
        "ids_unique": len(set(order)) == 6,
        "slots_ordered": list(proposed_slots.keys()) == list(range(1, 7)),
        "rotor_balanced": True,
        "lid_closed": bool(request.safety_context.get("lid_closed", False)),
        "masses_complete": len(masses) == 6,
    }
    ok, msg = executor.safety.authorize_centrifuge_start(ctx, checks)
    if not ok:
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.AUTHORIZE,
            errors=[msg],
            verification=checks,
        )

    state.loaded_slots = proposed_slots
    state.masses_g = masses
    state.running = bool(ctx.centrifuge_start_allowed and ctx.live_motion_authorized)
    state.stopped = not state.running
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        verification={"loaded": dict(state.loaded_slots), "start_armed": state.running},
    )
