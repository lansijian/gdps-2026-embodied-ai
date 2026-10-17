from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from gdps_qi.adapters.readonly.dds_readonly import DdsReadOnlyConfig, parse_lowstate_motors, subscribe_dds_once
from gdps_qi.adapters.readonly.joint_snapshot import JointSnapshot, JointValidity
from gdps_qi.adapters.readonly.ros2_probe import joint_state_from_summary, probe_ros2_topic_once
from gdps_qi.hardware.g1_joint_map import LOWSTATE_INDEX_TO_JOINT_G1_29, all_arm_joint_names
from gdps_qi.types import VerificationStatus


@dataclass
class RobotStateReadOnly:
    robot_variant: str = "G1_29_HAND14"
    joint_state_topic: str = ""
    dog_odom_topic: str = "/dog_odom"
    lowstate_dds_topic: str = ""
    expected_dof: int = 29
    dds_cfg: DdsReadOnlyConfig = field(default_factory=DdsReadOnlyConfig)
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _snapshot: Optional[JointSnapshot] = None
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "g1_robot_state",
            "variant": self.robot_variant,
            "expected_dof": self.expected_dof,
            "joint_state_topic": self.joint_state_topic,
            "dog_odom_topic": self.dog_odom_topic,
            "lowstate_dds_topic": self.lowstate_dds_topic,
            "joint_map_documented": LOWSTATE_INDEX_TO_JOINT_G1_29,
            "arm_joint_names": all_arm_joint_names(),
            "missing": [],
            "snapshot_validity": "UNKNOWN",
        }
        self._snapshot = None
        if not live:
            report["mode"] = "dry_run_schema"
            self._last_probe = report
            return report
        report["mode"] = "live_readonly"
        if self.joint_state_topic:
            try:
                from sensor_msgs.msg import JointState

                js = probe_ros2_topic_once(self.joint_state_topic, JointState, timeout_s)
                report["joint_states"] = js
                if js.get("ok"):
                    summary = js.get("msg_summary", {})
                    if isinstance(summary, dict):
                        snap = joint_state_from_summary(summary, "ros_joint_states_topic")
                        self._snapshot = snap
                        report["snapshot_validity"] = snap.validity.value
            except ImportError:
                report["joint_states"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        else:
            report["missing"].append("joint_states_topic_unconfigured")
        if self._snapshot is None or self._snapshot.validity is JointValidity.UNKNOWN:
            if self.lowstate_dds_topic:
                dds = self._probe_lowstate_dds(timeout_s)
                report["lowstate_dds"] = dds
                if dds.get("ok") and isinstance(dds.get("positions"), dict):
                    pos = dds["positions"]
                    if pos and not dds.get("reject"):
                        self._snapshot = JointSnapshot(
                            positions={str(k): float(v) for k, v in pos.items()},
                            stamp_sec=float(dds.get("host_received_at", 0.0)) or None,
                            source="unitree_lowstate_dds",
                            validity=JointValidity.PARTIAL,
                            mapping_basis="LOWSTATE_INDEX_TO_JOINT_G1_29_documented_unverified",
                            raw_joint_count=int(dds.get("motor_count", 0)),
                        )
                        report["snapshot_validity"] = self._snapshot.validity.value
                    else:
                        report["errors"] = [dds.get("error", "lowstate_rejected")]
            else:
                report["missing"].append("lowstate_dds_unconfigured")
        if self.dog_odom_topic:
            try:
                from nav_msgs.msg import Odometry

                report["dog_odom"] = probe_ros2_topic_once(self.dog_odom_topic, Odometry, timeout_s)
                report["dog_odom_note"] = "odom_not_substitute_for_body_joint_state"
            except ImportError:
                report["dog_odom"] = {"ok": False, "error": "nav_msgs_unavailable"}
        if self._snapshot:
            report["joint_position_count"] = len(self._snapshot.positions)
        self._last_probe = report
        return report

    def _probe_lowstate_dds(self, timeout_s: float) -> Dict[str, object]:
        if not self.lowstate_dds_topic:
            return {"ok": False, "error": "topic_unconfigured"}
        try:
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_  # type: ignore
        except ImportError:
            try:
                from unitree_sdk2py.idl.default import LowState_  # type: ignore
            except ImportError as exc:
                return {"ok": False, "error": f"lowstate_idl_unavailable:{exc}"}

        def parser(msg: object) -> Dict[str, object]:
            return parse_lowstate_motors(
                msg, LOWSTATE_INDEX_TO_JOINT_G1_29, expected_dof=self.expected_dof
            )

        return subscribe_dds_once(
            self.lowstate_dds_topic, LowState_, timeout_s, parser, self.dds_cfg
        )

    def get_joint_snapshot(self) -> Optional[JointSnapshot]:
        return self._snapshot
