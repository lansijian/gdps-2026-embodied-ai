from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame
from gdps_qi.kinematics.kinematics_backend import G1UrdfKinematicsAdapter, KinematicsBackend
from gdps_qi.perception.detection_types import Detection
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.perception.tablet_vision import detect_tablets_in_rgb
from gdps_qi.planning.grasp_planner import GraspPlan, GraspPlanner
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
    require_calibrated_table: bool = True,
) -> P1LocalizationResult:
    errors: List[str] = []
    if frame.rgb is None:
        return P1LocalizationResult(sample_id, "SAFE_HOLD", PositionTier.UNKNOWN, None, None, None, ["no_rgb"], {})
    detections, det_msg = detect_tablets_in_rgb(frame.rgb)
    if det_msg != "ok":
        return P1LocalizationResult(
            sample_id, "REFINE", PositionTier.DETECTED_IMAGE, None, None, None, [det_msg], {"count": len(detections)}
        )
    ok, msg = pose_estimator.validate_detections_for_target(detections, sample_id)
    if not ok:
        return P1LocalizationResult(
            sample_id, "REFINE", PositionTier.DETECTED_IMAGE, None, None, None, [msg], {}
        )
    det = next(d for d in detections if d.label == sample_id)
    tier = PositionTier.DETECTED_IMAGE
    pose, pose_msg = pose_estimator.tablet_pose_from_detection(sample_id, frame, det)
    if pose_msg == "ok" and g1_tf and g1_tf.tf.can_transform("robot_center", "table_frame"):
        tier = PositionTier.CALIBRATED_WORLD
    elif pose_msg == "ok":
        tier = PositionTier.RELATIVE_TABLE
    elif pose_msg in ("missing_table_tf", "missing_base_table_tf"):
        if require_calibrated_table:
            errors.append(pose_msg)
            tier = PositionTier.UNKNOWN
        else:
            tier = PositionTier.RELATIVE_TABLE
    else:
        errors.append(pose_msg)
        tier = PositionTier.UNKNOWN

    if tier is PositionTier.UNKNOWN:
        return P1LocalizationResult(sample_id, "SAFE_HOLD", tier, det, pose, None, errors, {"pose_msg": pose_msg})

    if g1_tf and not g1_tf.is_robot_tf_fresh():
        errors.append("robot_tf_stale_or_missing")

    plan = grasp_planner.plan_tablet_grasp(pose)
    if not plan.reachable:
        errors.append(plan.message)
        return P1LocalizationResult(
            sample_id, "SAFE_HOLD", tier, det, pose, plan, errors, {"ik": plan.message}
        )
    if isinstance(grasp_planner.kinematics, G1UrdfKinematicsAdapter):
        if grasp_planner.kinematics.kind.name == "UNAVAILABLE":
            errors.append("urdf_kinematics_unavailable")
    status = "PLAN_OK" if not errors else "SAFE_HOLD"
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
        },
    )
