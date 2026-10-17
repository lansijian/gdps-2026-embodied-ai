"""Compose existing perception gates for a read-only teaching handoff.

No hardware controller and no automatic grasp transition. Later stages require
separate vendor, FK, simulation and human review; this module cannot unlock them.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from gdps_qi.centering.target_centering_controller import TargetCenteringController
from gdps_qi.centering.manipulation_ready import ManipulationReadyGate
from gdps_qi.perception.rgbd_target_geometry import estimate_target_range
from gdps_qi.transforms.tf_chain_report import build_frame_graph_report


@dataclass
class TeachingPreview:
    centering: TargetCenteringController
    ready_gate: ManipulationReadyGate = field(default_factory=ManipulationReadyGate)

    def observe(self, frame, detection, **readiness_evidence):
        # No moved_since_last=True: this wrapper never moves the robot.
        centered = self.centering.step(frame, detection, workspace_ok=False)
        result = dict(stage='SAFE_HOLD', motor_write_allowed=False, execute_allowed=False,
                      field_verified=False, target_id=centered.locked_target_id,
                      recommended_lateral=centered.recommended_lateral,
                      pixel_du=centered.pixel_du, pixel_dv=centered.pixel_dv,
                      reasons=list(centered.reasons), grasp_ready=False)
        if not centered.safe:
            return result
        result['stage'] = 'CENTER_PREVIEW'
        if not centered.centered:
            return result
        report = build_frame_graph_report(self.centering.tf, self.centering.base_frame, stamp=frame.stamp)
        u,v = detection.center_uv
        distance = estimate_target_range(frame, u, v, report.T_base_camera, self.centering.base_frame)
        # Always delegate physical readiness to the existing provenance gate.
        evidence = dict(body_stable=False, workspace_ok=False, uncertainty_ok=False)
        evidence.update(readiness_evidence)
        ready = self.ready_gate.evaluate(centered, distance, report, **evidence)
        result['readiness_status'] = ready.status
        result['reasons'] += ready.reasons
        result['stage'] = 'POSE_REVIEW_PENDING' if ready.manipulation_ready else 'BODY_READY_BLOCKED'
        # Even a complete gate only permits review, never this program's grasp.
        return result
