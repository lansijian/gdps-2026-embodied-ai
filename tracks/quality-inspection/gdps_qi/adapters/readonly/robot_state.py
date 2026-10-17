from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from gdps_qi.adapters.readonly.ros2_probe import probe_ros2_topic_once
from gdps_qi.hardware.g1_joint_map import LOWSTATE_INDEX_TO_JOINT_G1_29, all_arm_joint_names
from gdps_qi.types import VerificationStatus


@dataclass
class RobotStateReadOnly:
    robot_variant: str = "G1_29_HAND14"
    joint_state_topic: str = ""
    dog_odom_topic: str = "/dog_odom"
    lowstate_dds_topic: str = ""
    status: VerificationStatus = VerificationStatus.UNKNOWN
    _positions: Dict[str, float] = field(default_factory=dict)
    _last_probe: Dict[str, object] = field(default_factory=dict)

    def probe(self, live: bool, timeout_s: float = 3.0) -> Dict[str, object]:
        report: Dict[str, object] = {
            "device": "g1_robot_state",
            "variant": self.robot_variant,
            "joint_state_topic": self.joint_state_topic,
            "dog_odom_topic": self.dog_odom_topic,
            "lowstate_dds_topic": self.lowstate_dds_topic,
            "joint_map": LOWSTATE_INDEX_TO_JOINT_G1_29,
            "arm_joint_names": all_arm_joint_names(),
            "missing": [],
        }
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
                    self._ingest_joint_summary(js.get("msg_summary", {}))
            except ImportError:
                report["joint_states"] = {"ok": False, "error": "sensor_msgs_unavailable"}
        else:
            report["missing"].append("joint_states_topic_unconfigured")
        if self.dog_odom_topic:
            try:
                from nav_msgs.msg import Odometry

                report["dog_odom"] = probe_ros2_topic_once(self.dog_odom_topic, Odometry, timeout_s)
            except ImportError:
                report["dog_odom"] = {"ok": False, "error": "nav_msgs_unavailable"}
        if self.lowstate_dds_topic:
            report["lowstate_dds"] = self._probe_lowstate_dds(timeout_s)
        else:
            report["missing"].append("lowstate_dds_unconfigured")
        self._last_probe = report
        return report

    def _ingest_joint_summary(self, summary: object) -> None:
        if not isinstance(summary, dict):
            return
        names = summary.get("joint_names_sample")
        if isinstance(names, list):
            for i, n in enumerate(names):
                self._positions[str(n)] = 0.0

    def _probe_lowstate_dds(self, timeout_s: float) -> Dict[str, object]:
        try:
            from unitree_sdk2py.core.channel import ChannelSubscriber  # type: ignore
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_  # type: ignore
        except ImportError as exc:
            return {"ok": False, "error": f"unitree_sdk2py_unavailable:{exc}"}
        return {
            "ok": False,
            "error": "lowstate_subscriber_requires_on_robot_manual_run",
            "hint": "use ChannelSubscriber one-shot in on-robot script with --live",
        }

    def get_joint_positions(self) -> Dict[str, float]:
        return dict(self._positions)
