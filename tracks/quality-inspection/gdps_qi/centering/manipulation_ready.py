from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
import hashlib
import json
import time
import numpy as np

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
    require_verified_calibration_id: bool = True
    require_tcp_verified: bool = True

    def evaluate(
        self,
        centering: CenteringStepResult,
        range_est: TargetRangeEstimate,
        tf_report: FrameGraphReport,
        body_stable: bool,
        workspace_ok: bool,
        uncertainty_ok: bool,
        calibration_id: str = "",
        calibration_verified: bool = False,
        tcp_verified: bool = False,
        depth_reliable: bool = False,
        tf_fresh: bool = False,
        evidence_path: Optional[Path] = None,
        kinematics=None,
    ) -> ManipulationReadyResult:
        reasons: List[str] = []
        # Externally supplied booleans cannot establish calibration or reachability.
        if evidence_path is None:
            reasons.append("source_evidence_bundle_missing")
        else:
            try:
                e = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
                if e["data_source"] != "REAL_SENSOR" or e["calibration_id"] != calibration_id:
                    reasons.append("calibration_provenance_invalid")
                if not 0 <= time.time() - float(e["stamp"]) <= 0.25:
                    reasons.append("readiness_evidence_stale")
                for key in ("calibration", "tcp", "urdf", "workspace_check"):
                    item = e[key]
                    path = Path(evidence_path).parent / item["path"]
                    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                        reasons.append(key + "_source_hash_mismatch")
                import yaml
                calibration = yaml.safe_load((Path(evidence_path).parent / e["calibration"]["path"]).read_text())
                tcp = yaml.safe_load((Path(evidence_path).parent / e["tcp"]["path"]).read_text())
                if (calibration.get("calibration_id") != calibration_id or not calibration.get("calibrated")
                        or not calibration.get("transforms") or calibration.get("robot_variant") in (None, "G1_UNKNOWN")
                        or not 0 <= time.time()-float(calibration["created_at"]) <= 86400):
                    reasons.append("calibration_source_invalid")
                tcp_t = np.asarray(tcp["T_wrist_tcp"], dtype=float)
                if (tcp.get("calibration_id") != calibration_id or tcp.get("source") != "REAL_SENSOR"
                        or tcp_t.shape != (4,4) or not np.isfinite(tcp_t).all()
                        or not np.allclose(tcp_t[3], [0,0,0,1])
                        or not np.allclose(tcp_t[:3,:3].T @ tcp_t[:3,:3], np.eye(3), atol=1e-6)
                        or not np.isclose(np.linalg.det(tcp_t[:3,:3]), 1)):
                    reasons.append("tcp_source_invalid")
                check = json.loads((Path(evidence_path).parent / e["workspace_check"]["path"]).read_text())
                if (check["backend"] != "G1_URDF_VERIFIED" or not check["reachable"]
                        or not np.allclose(check["target_base"], range_est.p_base, atol=0.005)
                        or check["fk_residual_m"] > 0.005
                        or check["urdf_sha256"] != e["urdf"]["sha256"]
                        or check["tcp_sha256"] != e["tcp"]["sha256"]):
                    reasons.append("workspace_target_or_fk_unverified")
                if kinematics is None or kinematics.kind.value != "G1_URDF_VERIFIED":
                    reasons.append("verified_urdf_fk_backend_required")
                else:
                    fk = kinematics.fk(check["joint_positions"], frame="wrist", side=check["side"]) @ tcp_t
                    if (check["base_frame"] != tf_report.base_frame
                            or np.linalg.norm(fk[:3,3]-np.asarray(range_est.p_base)) > 0.005):
                        reasons.append("actual_tcp_fk_outside_target")
            except Exception:
                reasons.append("source_evidence_bundle_invalid")
        if not np.isfinite([centering.pixel_du, centering.pixel_dv]).all():
            reasons.append("pixel_error_invalid")
        if not tf_report.statuses or any(x.stamp is None or not 0 <= time.time()-x.stamp <= 0.25 for x in tf_report.statuses):
            reasons.append("tf_timestamp_evidence_missing_or_stale")
        if tf_report.errors or any(not x.available for x in tf_report.statuses):
            reasons.append("tf_chain_invalid")
        if not centering.safe:
            reasons.append("centering_unsafe")
        if range_est.depth_std_m is None or not np.isfinite(range_est.depth_std_m):
            reasons.append("depth_uncertainty_unknown")
        if range_est.p_base is None or not np.isfinite(range_est.p_base).all():
            reasons.append("target_base_invalid")
        if not centering.centered:
            reasons.append("not_centered")
        if abs(centering.pixel_du) > self.max_pixel_du_px:
            reasons.append("pixel_off_center")
        if not range_est.valid:
            reasons.append("range_invalid")
        if not depth_reliable:
            reasons.append("depth_not_reliable")
        if range_est.depth_std_m is not None and range_est.depth_std_m > self.max_depth_std_m:
            reasons.append("depth_noise_high")
        if tf_report.T_base_camera is None:
            reasons.append("T_base_camera_missing")
        if not tf_fresh:
            reasons.append("tf_not_fresh")
        if self.require_tf_target and tf_report.T_base_target is None and range_est.p_base is None:
            reasons.append("target_pose_unverified")
        if self.require_verified_calibration_id and (not calibration_id or not calibration_verified):
            reasons.append("calibration_unverified")
        if self.require_tcp_verified and not tcp_verified:
            reasons.append("tcp_unverified")
        if not body_stable:
            reasons.append("body_not_stable")
        if not workspace_ok:
            reasons.append("outside_reach_workspace")
        if not uncertainty_ok:
            reasons.append("uncertainty_too_high")
        ready = (
            centering.centered
            and body_stable
            and workspace_ok
            and uncertainty_ok
            and range_est.valid
            and depth_reliable
            and tf_fresh
            and calibration_verified
            and (tcp_verified or not self.require_tcp_verified)
            and tf_report.T_base_camera is not None
            and not reasons
        )
        status = "MANIPULATION_READY" if ready else "NOT_READY_FOR_GRASP"
        if centering.centered and not ready:
            status = "CENTERED"
        return ManipulationReadyResult(
            manipulation_ready=ready,
            centered=centering.centered,
            status=status,
            reasons=reasons,
        )
