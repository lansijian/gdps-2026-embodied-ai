from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from gdps_qi.adapters.camera import CameraFrame
from gdps_qi.kinematics.kinematics_backend import G1UrdfKinematicsAdapter
from gdps_qi.perception.detection_types import Detection
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.perception.tablet_vision import detect_tablets_in_rgb
from gdps_qi.planning.grasp_planner import GraspPlan, GraspPlanner
from gdps_qi.transforms.calibration_trust import CalibrationTrust
from gdps_qi.transforms.g1_tf_chain import G1TfChain
from gdps_qi.types import PoseRecord


class PositionTier(str, enum.Enum):
    DETECTED_IMAGE = "DETECTED_IMAGE"
    CALIBRATED_WORLD = "CALIBRATED_WORLD"
    RELATIVE_TABLE = "RELATIVE_TABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class P1LocalizationResult:
    sample_id: str
    status: str
    tier: PositionTier
    detection: Optional[Detection]
    pose: Optional[PoseRecord]
    grasp_plan: Optional[GraspPlan]
    errors: List[str]
    diagnostics: Dict[str, object]


def localize_tablet_01(
    sample_id: str,
    frame: CameraFrame,
    pose_estimator: PoseEstimator,
    grasp_planner: GraspPlanner,
    g1_tf: Optional[G1TfChain],
    trust: Optional[CalibrationTrust] = None,
    require_calibrated_table: bool = True,
    detections_override: Optional[Sequence[Detection]] = None,
) -> P1LocalizationResult:
    errors: List[str] = []
    chain: List[Dict[str, object]] = []
    if frame.rgb is None:
        return P1LocalizationResult(sample_id, "SAFE_HOLD", PositionTier.UNKNOWN, None, None, None, ["no_rgb"], {})
    if detections_override is not None:
        detections = list(detections_override)
        det_msg = "ok" if detections else "no_mock_detections"
        chain.append({"step": "detect", "result": det_msg, "count": len(detections), "source": "mock"})
    else:
        detections, det_msg = detect_tablets_in_rgb(frame.rgb)
    chain.append({"step": "detect", "result": det_msg, "count": len(detections)})
    if det_msg != "ok":
        return P1LocalizationResult(
            sample_id, "REFINE", PositionTier.DETECTED_IMAGE, None, None, None, [det_msg], {"chain": chain}
        )
    ok, msg = pose_estimator.validate_detections_for_target(detections, sample_id)
    if not ok:
        return P1LocalizationResult(
            sample_id, "REFINE", PositionTier.DETECTED_IMAGE, None, None, None, [msg], {"chain": chain}
        )
    det = next(d for d in detections if d.label == sample_id)
    tier = PositionTier.DETECTED_IMAGE
    pose, pose_msg = pose_estimator.tablet_pose_from_detection(sample_id, frame, det)
    chain.append({"step": "pose", "result": pose_msg, "provenance": pose.provenance.value if pose else ""})
    if pose_msg == "ok":
        tier = PositionTier.RELATIVE_TABLE
    else:
        errors.append(pose_msg)
        tier = PositionTier.UNKNOWN

    if trust is not None:
        ok_world, reasons = trust.allows_calibrated_world()
        chain.append({"step": "calibrated_world_gate", "ok": ok_world, "reasons": reasons})
        if ok_world and pose_msg == "ok":
            tier = PositionTier.CALIBRATED_WORLD
        elif require_calibrated_table and tier != PositionTier.CALIBRATED_WORLD:
            errors.extend(reasons or ["calibrated_world_not_met"])
    elif require_calibrated_table:
        errors.append("calibration_trust_missing")

    if tier is PositionTier.UNKNOWN:
        return P1LocalizationResult(sample_id, "SAFE_HOLD", tier, det, pose, None, errors, {"chain": chain})

    if g1_tf and not g1_tf.is_robot_tf_fresh():
        errors.append("robot_tf_stale_or_missing")

    plan = grasp_planner.plan_tablet_grasp(
        pose, allow_executable=bool(trust and trust.tcp_verified and g1_tf and g1_tf.base_pelvis_verified)
    )
    if not plan.reachable:
        errors.append(plan.message)
        return P1LocalizationResult(
            sample_id, "SAFE_HOLD", tier, det, pose, plan, errors, {"chain": chain, "ik": plan.message}
        )
    if isinstance(grasp_planner.kinematics, G1UrdfKinematicsAdapter):
        if grasp_planner.kinematics.kind.name == "UNAVAILABLE":
            errors.append("urdf_kinematics_unavailable")
    if not plan.executable_plan:
        errors.append("plan_readonly_not_executable")
    if plan.message == "uncertainty_high_readonly":
        errors.append("position_uncertainty_high")
    status = "PLAN_READONLY_OK" if plan.reachable and not any(
        e for e in errors if e not in ("plan_readonly_not_executable", "position_uncertainty_high")
    ) else "SAFE_HOLD"
    return P1LocalizationResult(
        sample_id,
        status,
        tier,
        det,
        pose,
        plan,
        errors,
        {
            "detection_confidence": det.confidence,
            "tier": tier.value,
            "timestamp": time.time(),
            "chain": chain,
        },
    )
