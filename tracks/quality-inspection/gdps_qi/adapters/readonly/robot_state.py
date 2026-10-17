from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from gdps_qi.types import VerificationStatus

# Joint names aligned with xr_teleoperate g1_body29_hand14.urdf (DOCUMENTED_UNVERIFIED on PC2).
G1_URDF_ARM_JOINTS_LEFT: Tuple[str, ...] = (
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
)


@dataclass
class RobotStateReadOnly:
    status: VerificationStatus = VerificationStatus.UNKNOWN
    lowstate_topic: str = ""
    joint_state_topic: str = "/joint_states"
    _positions: Dict[str, float] = field(default_factory=dict)

    def connect(self) -> Tuple[bool, str]:
        return False, "sdk2_or_ros_subscription_not_wired_in_phase2"

    def get_joint_positions(self) -> Dict[str, float]:
        return dict(self._positions)

    def field_check_steps(self) -> Tuple[str, ...]:
        return (
            "ros2 topic list -t | grep -E 'joint|lowstate|sport'",
            "Confirm 23 vs 29 DoF via unitree lowstate or official example (read only)",
            "Map motor index -> URDF joint name before any IK target",
            "Verify waist yaw/roll/pitch availability for camera TF",
        )
