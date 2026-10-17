from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from gdps_qi.transforms.calibration_manager import CalibrationManager
from gdps_qi.types import PoseRecord, SkillPhase


@dataclass
class SafetyContext:
    live_motion_authorized: bool = False
    calibration_ok: bool = False
    tf_version: str = ""
    owner: str = "gdps_quality_inspection"
    contact_allowed: bool = False
    centrifuge_start_allowed: bool = False


@dataclass
class MotionSafetyGate:
    calibration: CalibrationManager
    motion_owner: str = "gdps_quality_inspection"
    _owner_lock: Optional[str] = None
    violations: List[str] = field(default_factory=list)

    def acquire_owner(self, requester: str) -> Tuple[bool, str]:
        if self._owner_lock is None:
            self._owner_lock = requester
            return True, "acquired"
        if self._owner_lock == requester:
            return True, "already_owner"
        return False, f"owner_conflict:{self._owner_lock}"

    def release_owner(self, requester: str) -> None:
        if self._owner_lock == requester:
            self._owner_lock = None

    def authorize_phase(
        self,
        phase: SkillPhase,
        ctx: SafetyContext,
        target: Optional[PoseRecord] = None,
        requires_contact: bool = False,
    ) -> Tuple[bool, str]:
        self.violations.clear()
        ok_cal, reason_cal = self.calibration.is_valid()
        if not ok_cal:
            self.violations.append(reason_cal)
            return False, reason_cal
        if not ctx.calibration_ok:
            self.violations.append("safety_context_calibration_false")
            return False, "safety_context_calibration_false"
        if phase in (SkillPhase.EXECUTE, SkillPhase.VERIFY) and requires_contact:
            if not ctx.contact_allowed:
                self.violations.append("contact_not_allowed")
                return False, "contact_not_allowed"
            if not ctx.live_motion_authorized:
                self.violations.append("live_motion_not_authorized")
                return False, "live_motion_not_authorized"
        if target is not None:
            if target.confidence < 0.5:
                self.violations.append("low_confidence_pose")
                return False, "low_confidence_pose"
            if target.uncertainty and target.uncertainty.position_m > 0.006:
                self.violations.append("pose_uncertainty_exceeds_grasp_margin")
                return False, "pose_uncertainty_exceeds_grasp_margin"
        if phase == SkillPhase.AUTHORIZE and requires_contact and not ctx.live_motion_authorized:
            return False, "authorize_requires_live_token"
        return True, "ok"

    def authorize_centrifuge_start(self, ctx: SafetyContext, checks: Dict[str, bool]) -> Tuple[bool, str]:
        required = [
            "six_tubes_sealed",
            "ids_unique",
            "slots_ordered",
            "rotor_balanced",
            "lid_closed",
        ]
        for key in required:
            if not checks.get(key, False):
                return False, f"missing:{key}"
        if not ctx.centrifuge_start_allowed:
            return False, "centrifuge_start_not_authorized"
        if not ctx.live_motion_authorized:
            return False, "live_motion_not_authorized"
        return True, "ok"
