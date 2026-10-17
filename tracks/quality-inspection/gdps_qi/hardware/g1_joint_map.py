from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Names aligned with unitree xr_teleoperate assets/g1/g1_body29_hand14.urdf (DOCUMENTED_UNVERIFIED).
G1_WAIST_JOINTS: Tuple[str, ...] = (
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
)

G1_LEFT_ARM_JOINTS: Tuple[str, ...] = (
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
)

G1_RIGHT_ARM_JOINTS: Tuple[str, ...] = (
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
)

# LowState motor index map for G1 29DoF (unitree_sdk2 low_level example — verify on EDU unit).
LOWSTATE_INDEX_TO_JOINT_G1_29: Dict[int, str] = {
    0: "left_hip_pitch_joint",
    1: "left_hip_roll_joint",
    2: "left_hip_yaw_joint",
    3: "left_knee_joint",
    4: "left_ankle_pitch_joint",
    5: "left_ankle_roll_joint",
    6: "right_hip_pitch_joint",
    7: "right_hip_roll_joint",
    8: "right_hip_yaw_joint",
    9: "right_knee_joint",
    10: "right_ankle_pitch_joint",
    11: "right_ankle_roll_joint",
    12: "waist_yaw_joint",
    13: "waist_roll_joint",
    14: "waist_pitch_joint",
    15: "left_shoulder_pitch_joint",
    16: "left_shoulder_roll_joint",
    17: "left_shoulder_yaw_joint",
    18: "left_elbow_joint",
    19: "left_wrist_roll_joint",
    20: "left_wrist_pitch_joint",
    21: "left_wrist_yaw_joint",
    22: "right_shoulder_pitch_joint",
    23: "right_shoulder_roll_joint",
    24: "right_shoulder_yaw_joint",
    25: "right_elbow_joint",
    26: "right_wrist_roll_joint",
    27: "right_wrist_pitch_joint",
    28: "right_wrist_yaw_joint",
}

DEX3_JOINT_NAMES_LEFT: Tuple[str, ...] = tuple(f"left_hand_joint_{i}" for i in range(7))
DEX3_JOINT_NAMES_RIGHT: Tuple[str, ...] = tuple(f"right_hand_joint_{i}" for i in range(7))

URDF_FRAME_LEFT_WRIST = "left_wrist_yaw_link"
URDF_FRAME_RIGHT_WRIST = "right_wrist_yaw_link"
URDF_FRAME_TORSO = "torso_link"
URDF_FRAME_PELVIS = "pelvis"
URDF_FRAME_HEAD_CAMERA = "head_camera_link"  # verify against actual URDF / calib


@dataclass(frozen=True)
class TcpOffset:
    """Static palm->finger_tcp; must be measured in field."""

    name: str
    position_xyz: Tuple[float, float, float]
    orientation_xyzw: Tuple[float, float, float, float]
    verified: bool = False


DEFAULT_LEFT_PINCH_TCP = TcpOffset(
    "left_pinch_tcp",
    (0.08, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
    verified=False,
)
DEFAULT_RIGHT_PINCH_TCP = TcpOffset(
    "right_pinch_tcp",
    (0.08, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
    verified=False,
)


def all_arm_joint_names() -> List[str]:
    return list(G1_LEFT_ARM_JOINTS) + list(G1_RIGHT_ARM_JOINTS) + list(G1_WAIST_JOINTS)
