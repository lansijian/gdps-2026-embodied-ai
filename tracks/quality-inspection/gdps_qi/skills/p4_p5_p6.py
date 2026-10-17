from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.planning.motion_safety_gate import SafetyContext
from gdps_qi.types import SkillPhase, SkillRequest, SkillResult


@dataclass
class QcRecord:
    sample_id: str
    leak_status: str = "UNKNOWN_REVIEW_REQUIRED"
    integrity: str = "UNKNOWN_REVIEW_REQUIRED"
    final_class: str = "PENDING"
    image_ref: str = ""


@dataclass
class MissionTailState:
    centrifuge_stopped: bool = False
    qc: Dict[str, QcRecord] = field(default_factory=dict)
    report_pending: List[Dict[str, object]] = field(default_factory=list)


def register_p456_skills(executor: SkillExecutor, state: MissionTailState) -> None:
    executor.register("P4_UNLOAD", lambda req, ctx: _p4_unload(state, req, ctx))
    executor.register("P5_QC", lambda req, ctx: _p5_qc(state, req, ctx))
    executor.register("P6_SORT_REPORT", lambda req, ctx: _p6_sort_report(executor, state, req, ctx))


def _p4_unload(state: MissionTailState, request: SkillRequest, ctx: SafetyContext) -> SkillResult:
    if not state.centrifuge_stopped and not request.safety_context.get("force_stopped", False):
        return SkillResult(
            status="SAFE_HOLD",
            phase=SkillPhase.VERIFY,
            errors=["centrifuge_not_confirmed_stopped"],
        )
    state.centrifuge_stopped = True
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        verification={"tubes_returned": request.safety_context.get("tube_ids", [])},
    )


def _p5_qc(state: MissionTailState, request: SkillRequest, ctx: SafetyContext) -> SkillResult:
    sid = request.sample_id
    vis = request.safety_context.get("visible", {})
    leak = vis.get("leak", "unknown")
    crack = vis.get("crack", "unknown")
    rec = state.qc.setdefault(sid, QcRecord(sample_id=sid))
    rec.image_ref = str(request.safety_context.get("image_ref", f"qc_{sid}.png"))
    if leak == "yes":
        rec.leak_status = "LEAK_SUSPECTED"
    elif leak == "no":
        rec.leak_status = "NO_VISIBLE_LEAK"
    else:
        rec.leak_status = "UNKNOWN_REVIEW_REQUIRED"
    if crack == "yes":
        rec.integrity = "DAMAGED_SUSPECTED"
    elif crack == "no":
        rec.integrity = "NO_VISIBLE_DAMAGE"
    else:
        rec.integrity = "UNKNOWN_REVIEW_REQUIRED"
    return SkillResult(
        status="COMMIT",
        phase=SkillPhase.COMMIT,
        verification={"leak_status": rec.leak_status, "integrity": rec.integrity},
    )


def _p6_sort_report(
    executor: SkillExecutor,
    state: MissionTailState,
    request: SkillRequest,
    ctx: SafetyContext,
) -> SkillResult:
    from gdps_qi.evidence.report_uploader import ReportUploader

    uploader = ReportUploader(endpoint=request.safety_context.get("endpoint", ""))
    records = []
    for sid, rec in state.qc.items():
        cls = "PASS" if rec.leak_status == "NO_VISIBLE_LEAK" and rec.integrity == "NO_VISIBLE_DAMAGE" else "REVIEW"
        if rec.leak_status.startswith("LEAK") or rec.integrity.startswith("DAMAGED"):
            cls = "FAIL"
        rec.final_class = cls
        records.append(
            {
                "sample_id": sid,
                "leak_status": rec.leak_status,
                "integrity": rec.integrity,
                "final_class": cls,
                "image_ref": rec.image_ref,
            }
        )
    upload = uploader.upload_batch(records, idempotency_key=request.safety_context.get("idempotency_key", "run1"))
    state.report_pending = records
    status = "COMMIT" if upload.ack else "SAFE_HOLD"
    return SkillResult(
        status=status,
        phase=SkillPhase.COMMIT if upload.ack else SkillPhase.SAFE_HOLD,
        verification={"upload": upload.as_dict(), "records": records},
        errors=[] if upload.ack else ["upload_no_ack"],
    )
