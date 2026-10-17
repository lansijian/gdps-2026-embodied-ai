from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from gdps_qi.centering.target_centering_controller import CenteringStepResult
from gdps_qi.perception.rgbd_target_geometry import TargetRangeEstimate
from gdps_qi.transforms.tf_chain_report import FrameGraphReport


@dataclass
class ManipulationReadyResult:
    manipulation_ready: bool
    centered: bool
    status: str
    reasons: List[str] = field(default_factory=list)


@dataclass
class ManipulationReadyGate:
    max_depth_std_m: float = 0.02
    max_pixel_du_px: float = 12.0
    require_tf_target: bool = True

    def evaluate(
        self,
        centering: CenteringStepResult,
        range_est: TargetRangeEstimate,
        tf_report: FrameGraphReport,
        body_stable: bool,
        workspace_ok: bool,
        uncertainty_ok: bool,
    ) -> ManipulationReadyResult:
        reasons: List[str] = []
        if not centering.centered:
            reasons.append("not_centered")
        if abs(centering.pixel_du) > self.max_pixel_du_px:
            reasons.append("pixel_off_center")
        if not range_est.valid:
            reasons.append("range_invalid")
        if range_est.depth_std_m is not None and range_est.depth_std_m > self.max_depth_std_m:
            reasons.append("depth_noise_high")
        if tf_report.T_base_camera is None:
            reasons.append("T_base_camera_missing")
        if self.require_tf_target and tf_report.T_base_target is None and range_est.p_base is None:
            reasons.append("target_pose_unverified")
        if not body_stable:
            reasons.append("body_not_stable")
        if not workspace_ok:
            reasons.append("outside_reach_workspace")
        if not uncertainty_ok:
            reasons.append("uncertainty_too_high")
        centered = centering.centered and not reasons
        ready = centered and body_stable and workspace_ok and uncertainty_ok and range_est.valid
        status = "MANIPULATION_READY" if ready else "NOT_READY_FOR_GRASP"
        if centering.centered and not ready:
            status = "CENTERED"
        return ManipulationReadyResult(
            manipulation_ready=ready,
            centered=centering.centered,
            status=status,
            reasons=reasons,
        )
