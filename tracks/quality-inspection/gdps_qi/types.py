from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    DOCUMENTED_UNVERIFIED = "DOCUMENTED_UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class DataProvenance(str, enum.Enum):
    MOCK = "MOCK"
    SIMULATION = "SIMULATION"
    SENSOR_READ = "SENSOR_READ"
    VISION_INFERENCE = "VISION_INFERENCE"
    CALIBRATION_FILE = "CALIBRATION_FILE"
    VERIFIED_FIELD = "VERIFIED_FIELD"


class UploadServerStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACK = "ACK"
    FAILED = "FAILED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class SkillPhase(str, enum.Enum):
    PREPARE = "PREPARE"
    OBSERVE = "OBSERVE"
    LOCALIZE = "LOCALIZE"
    VALIDATE = "VALIDATE"
    PLAN = "PLAN"
    AUTHORIZE = "AUTHORIZE"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    COMMIT = "COMMIT"
    RETRY = "RETRY"
    REFINE = "REFINE"
    RECOVER = "RECOVER"
    SAFE_HOLD = "SAFE_HOLD"
    ABORT = "ABORT"


class MissionPhase(str, enum.Enum):
    P1_TABLET = "P1_TABLET"
    P2_TUBE_PREP = "P2_TUBE_PREP"
    P3_CENTRIFUGE_LOAD = "P3_CENTRIFUGE_LOAD"
    P4_CENTRIFUGE_UNLOAD = "P4_CENTRIFUGE_UNLOAD"
    P5_QC = "P5_QC"
    P6_SORT_REPORT = "P6_SORT_REPORT"


@dataclass(frozen=True)
class Timestamped:
    stamp: float
    frame_id: str

    @classmethod
    def now(cls, frame_id: str) -> "Timestamped":
        return cls(stamp=time.time(), frame_id=frame_id)


@dataclass
class Uncertainty:
    position_m: float
    orientation_rad: float
    source: str = "default"

    def exceeds(self, pos_limit_m: float, ori_limit_rad: float) -> bool:
        return self.position_m > pos_limit_m or self.orientation_rad > ori_limit_rad


@dataclass
class PoseRecord:
    frame_id: str
    stamp: float
    position: Tuple[float, float, float]
    orientation_xyzw: Tuple[float, float, float, float]
    object_id: str = ""
    calibration_id: str = ""
    uncertainty: Optional[Uncertainty] = None
    confidence: float = 0.0
    source: str = ""
    provenance: DataProvenance = DataProvenance.MOCK

    def as_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "stamp": self.stamp,
            "position": list(self.position),
            "orientation_xyzw": list(self.orientation_xyzw),
            "object_id": self.object_id,
            "calibration_id": self.calibration_id,
            "uncertainty": (
                {
                    "position_m": self.uncertainty.position_m,
                    "orientation_rad": self.uncertainty.orientation_rad,
                    "source": self.uncertainty.source,
                }
                if self.uncertainty
                else None
            ),
            "confidence": self.confidence,
            "source": self.source,
            "provenance": self.provenance.value,
        }


@dataclass
class SampleIdentity:
    sample_id: str
    tablet_id: str
    tray_slot: int
    tube_id: str

    def validate(self) -> None:
        if not self.sample_id or len(self.sample_id) != 2:
            raise ValueError("sample_id must be two-digit string")
        if self.tray_slot < 1 or self.tray_slot > 6:
            raise ValueError("tray_slot must be 1..6")


@dataclass
class ActionEvidence:
    task_id: str
    sample_id: str
    phase: str
    tf_version: str
    started_at: float
    ended_at: float
    result: str
    failure_reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new_task_id() -> str:
        return str(uuid.uuid4())


@dataclass
class SkillRequest:
    skill_name: str
    sample_id: str
    object_refs: Dict[str, str]
    calibration_refs: List[str]
    allowed_actuation: bool
    safety_context: Dict[str, Any]


@dataclass
class SkillResult:
    status: str
    phase: SkillPhase
    observations: Dict[str, Any] = field(default_factory=dict)
    estimated_pose: Optional[PoseRecord] = None
    planned_waypoints: List[PoseRecord] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    retries: int = 0
    evidence: List[ActionEvidence] = field(default_factory=list)
