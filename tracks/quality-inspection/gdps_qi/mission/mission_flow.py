from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class FlowNode(str, enum.Enum):
    NAVIGATE_TO_STATION = "NAVIGATE_TO_STATION"
    STABILIZE_BODY = "STABILIZE_BODY"
    REGISTER_WORKSTATION = "REGISTER_WORKSTATION"
    VERIFY_CAMERA_AND_TF = "VERIFY_CAMERA_AND_TF"
    OBSERVE_TARGET = "OBSERVE_TARGET"
    ESTIMATE_3D_POSE = "ESTIMATE_3D_POSE"
    VALIDATE_SENSOR_AND_TF = "VALIDATE_SENSOR_AND_TF"
    CENTER_TARGET = "CENTER_TARGET"
    ADJUST_BODY_OR_WAIST = "ADJUST_BODY_OR_WAIST"
    REOBSERVE = "REOBSERVE"
    CHECK_REACHABLE_WORKSPACE = "CHECK_REACHABLE_WORKSPACE"
    MANIPULATION_READY = "MANIPULATION_READY"
    P1_PICK_AND_WEIGH = "P1_PICK_AND_WEIGH"
    P2_PREPARE_TUBE = "P2_PREPARE_TUBE"
    REPEAT_6 = "REPEAT_6"
    P3_CENTRIFUGE = "P3_CENTRIFUGE"
    P4_UNLOAD = "P4_UNLOAD"
    P5_INSPECT = "P5_INSPECT"
    P6_REPORT = "P6_REPORT"


class FlowPhase(str, enum.Enum):
    PRECONDITION = "precondition"
    EXECUTE = "execute"
    VERIFY = "verify"
    TIMEOUT = "timeout"
    RETRY = "retry"
    RECOVER = "recover"
    SAFE_HOLD = "safe_hold"
    EVIDENCE = "evidence"


@dataclass(frozen=True)
class FlowEdge:
    from_node: FlowNode
    to_node: FlowNode
    guard: str


@dataclass
class NodeSpec:
    node: FlowNode
    preconditions: List[str]
    execute: str
    verify: str
    timeout_s: float
    max_retries: int
    recover: str
    safe_hold: str
    evidence: List[str]
    motion_handoff: str = "navigation_release_before_manipulation"


MISSION_FLOW_ORDER: Tuple[FlowNode, ...] = (
    FlowNode.NAVIGATE_TO_STATION,
    FlowNode.STABILIZE_BODY,
    FlowNode.REGISTER_WORKSTATION,
    FlowNode.VERIFY_CAMERA_AND_TF,
    FlowNode.OBSERVE_TARGET,
    FlowNode.ESTIMATE_3D_POSE,
    FlowNode.VALIDATE_SENSOR_AND_TF,
    FlowNode.CENTER_TARGET,
    FlowNode.ADJUST_BODY_OR_WAIST,
    FlowNode.REOBSERVE,
    FlowNode.CHECK_REACHABLE_WORKSPACE,
    FlowNode.STABILIZE_BODY,
    FlowNode.MANIPULATION_READY,
    FlowNode.P1_PICK_AND_WEIGH,
    FlowNode.P2_PREPARE_TUBE,
    FlowNode.REPEAT_6,
    FlowNode.P3_CENTRIFUGE,
    FlowNode.P4_UNLOAD,
    FlowNode.P5_INSPECT,
    FlowNode.P6_REPORT,
)


def default_specs() -> Dict[FlowNode, NodeSpec]:
    common_nav = [
        "odom_fresh",
        "lidar_decision_not_stop",
        "motion_lock_owner=navigation",
        "dry_run_or_live_authorized",
    ]
    common_qi = [
        "robot_joints_valid_or_unknown_gate",
        "camera_intrinsics_trusted_or_rgb_only_path",
        "tf_base_pelvis_verified_for_calibrated_world",
        "tcp_verified_for_executable_grasp",
    ]
    return {
        FlowNode.NAVIGATE_TO_STATION: NodeSpec(
            FlowNode.NAVIGATE_TO_STATION,
            preconditions=common_nav + ["goal_and_pose_valid"],
            execute="SharedNavigator.step or preview only until station perimeter",
            verify="pose_within_station_tolerance",
            timeout_s=120.0,
            max_retries=1,
            recover="stop_nav_hold_position",
            safe_hold="zero_cmd_vel",
            evidence=["nav_status_json", "odom_trace"],
            motion_handoff="navigation_active",
        ),
        FlowNode.STABILIZE_BODY: NodeSpec(
            FlowNode.STABILIZE_BODY,
            preconditions=["feet_contact_assumed", "no_active_nav_cmd"],
            execute="wait settle 2s; reject if odom jitter > threshold",
            verify="body_stable_flag",
            timeout_s=15.0,
            max_retries=2,
            recover="extend_wait_or_operator_confirm",
            safe_hold="freeze_all_motion",
            evidence=["imu_or_odom_stability_sample"],
            motion_handoff="navigation_release_before_manipulation",
        ),
        FlowNode.REGISTER_WORKSTATION: NodeSpec(
            FlowNode.REGISTER_WORKSTATION,
            preconditions=["calibration_bundle_present_or_simulation_mode"],
            execute="load workstation yaml; apply table_frame TF",
            verify="can_transform(base,table_frame)",
            timeout_s=30.0,
            max_retries=0,
            recover="manual_register_workstation",
            safe_hold="no_manipulation",
            evidence=["calibration_id", "tf_version"],
        ),
        FlowNode.VERIFY_CAMERA_AND_TF: NodeSpec(
            FlowNode.VERIFY_CAMERA_AND_TF,
            preconditions=common_qi,
            execute="head_camera probe + joint snapshot + g1_tf chain update",
            verify="tier>=RELATIVE_TABLE or SAFE_HOLD",
            timeout_s=45.0,
            max_retries=1,
            recover="rgb_only_perception_path",
            safe_hold="P1_blocked",
            evidence=["camera_probe_json", "joint_snapshot"],
        ),
        FlowNode.OBSERVE_TARGET: NodeSpec(
            FlowNode.OBSERVE_TARGET,
            preconditions=["rgb_frame_ok"],
            execute="detect/lock target bbox",
            verify="confidence>=threshold",
            timeout_s=30.0,
            max_retries=2,
            recover="reacquire_target",
            safe_hold="SAFE_HOLD",
            evidence=["annotated_rgb"],
        ),
        FlowNode.ESTIMATE_3D_POSE: NodeSpec(
            FlowNode.ESTIMATE_3D_POSE,
            preconditions=["intrinsics_trusted"],
            execute="rgbd_target_geometry.estimate_target_range",
            verify="valid_or_unknown_depth",
            timeout_s=20.0,
            max_retries=1,
            recover="plane_geometry_fallback",
            safe_hold="no_grasp_pose",
            evidence=["range_estimate_json"],
        ),
        FlowNode.VALIDATE_SENSOR_AND_TF: NodeSpec(
            FlowNode.VALIDATE_SENSOR_AND_TF,
            preconditions=["tf_chain_report"],
            execute="sensor_validation_report + tf_chain_report",
            verify="no_missing_critical_edge",
            timeout_s=30.0,
            max_retries=1,
            recover="rgb_only_continue",
            safe_hold="centering_blocked",
            evidence=["sensor_validation_json"],
        ),
        FlowNode.CENTER_TARGET: NodeSpec(
            FlowNode.CENTER_TARGET,
            preconditions=["target_centering_controller"],
            execute="discrete observe-plan-step cycles",
            verify="pixel_within_deadzone",
            timeout_s=120.0,
            max_retries=2,
            recover="SAFE_HOLD",
            safe_hold="zero_motion",
            evidence=["centering_steps_csv"],
        ),
        FlowNode.ADJUST_BODY_OR_WAIST: NodeSpec(
            FlowNode.ADJUST_BODY_OR_WAIST,
            preconditions=["lidar_allows_lateral", "dry_run_or_live_authorized"],
            execute="lateral preview or waist_preview (no LowCmd)",
            verify="odom_delta_matches_intent",
            timeout_s=60.0,
            max_retries=2,
            recover="reverse_last_step",
            safe_hold="stop_motion",
            evidence=["dry_run_cmd_log"],
            motion_handoff="navigation_active",
        ),
        FlowNode.REOBSERVE: NodeSpec(
            FlowNode.REOBSERVE,
            preconditions=["post_motion_settle"],
            execute="new rgbd sample",
            verify="pixel_error_not_worse",
            timeout_s=30.0,
            max_retries=2,
            recover="SAFE_HOLD",
            safe_hold="freeze",
            evidence=["before_after_overlay"],
        ),
        FlowNode.CHECK_REACHABLE_WORKSPACE: NodeSpec(
            FlowNode.CHECK_REACHABLE_WORKSPACE,
            preconditions=["manipulation_workspace_template"],
            execute="IK readonly feasibility",
            verify="reachable_readonly",
            timeout_s=45.0,
            max_retries=1,
            recover="adjust_dock_pose",
            safe_hold="P1_blocked",
            evidence=["ik_readonly_report"],
        ),
        FlowNode.MANIPULATION_READY: NodeSpec(
            FlowNode.MANIPULATION_READY,
            preconditions=["centered", "tf_trusted", "body_stable"],
            execute="ManipulationReadyGate.evaluate",
            verify="status==MANIPULATION_READY",
            timeout_s=15.0,
            max_retries=0,
            recover="continue_centering",
            safe_hold="NOT_READY_FOR_GRASP",
            evidence=["manipulation_ready_json"],
        ),
        FlowNode.P1_PICK_AND_WEIGH: NodeSpec(
            FlowNode.P1_PICK_AND_WEIGH,
            preconditions=common_qi + ["sample_id_param", "P1_LOCALIZE_01_ok"],
            execute="P1_LOCALIZE_01 then P1_PICK_TABLET (param sample_id)",
            verify="pickup_confirmed only if verified_pickup_visual",
            timeout_s=90.0,
            max_retries=1,
            recover="SAFE_HOLD and re-localize",
            safe_hold="no_arm_cmd_without_allow_actuation",
            evidence=["detection_image", "grasp_plan_readonly"],
        ),
        FlowNode.P2_PREPARE_TUBE: NodeSpec(
            FlowNode.P2_PREPARE_TUBE,
            preconditions=["P1_commit_ok", "tube_pose_tier_ok"],
            execute="P2_TUBE skill parameterized by sample_id",
            verify="tube_state_committed",
            timeout_s=120.0,
            max_retries=1,
            recover="discard_partial_tube_state",
            safe_hold="hands_idle",
            evidence=["tube_skill_log"],
        ),
        FlowNode.REPEAT_6: NodeSpec(
            FlowNode.REPEAT_6,
            preconditions=["sample_index_1..6"],
            execute="loop P1+P2 with same skill templates",
            verify="six_unique_sample_ids",
            timeout_s=600.0,
            max_retries=0,
            recover="abort_tail_and_report",
            safe_hold="mission_pause",
            evidence=["per_sample_evidence_bundle"],
        ),
        FlowNode.P3_CENTRIFUGE: NodeSpec(
            FlowNode.P3_CENTRIFUGE,
            preconditions=["loaded_slots_validated"],
            execute="P3 load sequence",
            verify="centrifuge_interlock_sim_or_verified",
            timeout_s=180.0,
            max_retries=0,
            recover="manual_unload_protocol",
            safe_hold="no_start_without_interlock",
            evidence=["slot_mass_map"],
        ),
        FlowNode.P4_UNLOAD: NodeSpec(
            FlowNode.P4_UNLOAD,
            preconditions=["P3_complete_verified"],
            execute="P4 unload skill",
            verify="rotor_slots_empty_verified",
            timeout_s=180.0,
            max_retries=1,
            recover="operator_assist",
            safe_hold="freeze",
            evidence=["unload_log"],
        ),
        FlowNode.P5_INSPECT: NodeSpec(
            FlowNode.P5_INSPECT,
            preconditions=["samples_at_inspection_station"],
            execute="P5 vision/measure skills",
            verify="qc_flags",
            timeout_s=120.0,
            max_retries=1,
            recover="rescan",
            safe_hold="hold",
            evidence=["qc_images"],
        ),
        FlowNode.P6_REPORT: NodeSpec(
            FlowNode.P6_REPORT,
            preconditions=["mission_tail_complete"],
            execute="aggregate evidence + upload",
            verify="upload_ACK_or_local_write_ok",
            timeout_s=60.0,
            max_retries=2,
            recover="local_json_fallback",
            safe_hold="n/a",
            evidence=["final_report_json"],
        ),
    }


@dataclass
class MissionFlowState:
    current: FlowNode = FlowNode.NAVIGATE_TO_STATION
    sample_index: int = 1
    retries: Dict[FlowNode, int] = field(default_factory=dict)
    completed: List[FlowNode] = field(default_factory=list)
    safe_hold: bool = False
    evidence: Dict[str, object] = field(default_factory=dict)

    def transition(self, success: bool, specs: Dict[FlowNode, NodeSpec]) -> Tuple[FlowNode, str]:
        if self.safe_hold:
            return self.current, "safe_hold_active"
        spec = specs[self.current]
        if not success:
            r = self.retries.get(self.current, 0) + 1
            self.retries[self.current] = r
            if r <= spec.max_retries:
                return self.current, FlowPhase.RETRY.value
            self.safe_hold = True
            return self.current, FlowPhase.SAFE_HOLD.value
        self.completed.append(self.current)
        idx = MISSION_FLOW_ORDER.index(self.current)
        if self.current is FlowNode.REPEAT_6:
            if self.sample_index < 6:
                self.sample_index += 1
                self.current = FlowNode.P1_PICK_AND_WEIGH
                return self.current, FlowPhase.EXECUTE.value
        if idx + 1 < len(MISSION_FLOW_ORDER):
            self.current = MISSION_FLOW_ORDER[idx + 1]
            return self.current, FlowPhase.EXECUTE.value
        return self.current, "mission_complete"
