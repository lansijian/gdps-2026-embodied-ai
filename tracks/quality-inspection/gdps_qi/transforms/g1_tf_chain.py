from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

from gdps_qi.hardware.g1_joint_map import (
    DEFAULT_LEFT_PINCH_TCP,
    DEFAULT_RIGHT_PINCH_TCP,
    URDF_FRAME_HEAD_CAMERA,
    URDF_FRAME_LEFT_WRIST,
    URDF_FRAME_PELVIS,
    URDF_FRAME_RIGHT_WRIST,
    URDF_FRAME_TORSO,
    all_arm_joint_names,
)
from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel, JointConfigureResult
from gdps_qi.math_se3 import compose_transform, invert_transform, transform_from_pose
from gdps_qi.transforms.transform_manager import TransformManager
from gdps_qi.types import VerificationStatus


@dataclass
class G1TfChain:
    tf: TransformManager
    urdf: Optional[G1UrdfModel] = None
    robot_base_frame: str = "robot_center"
    table_frame: str = "table_frame"
    camera_optical_frame: str = "head_camera_optical"
    status: VerificationStatus = VerificationStatus.UNKNOWN
    base_pelvis_verified: bool = False
    tcp_verified: bool = False
    _last_joint_stamp: float = 0.0
    _last_configure: Optional[JointConfigureResult] = None

    def set_verified_base_pelvis(
        self, t_robot_pelvis: np.ndarray, stamp: float, calibration_id: str
    ) -> None:
        self.tf.set_transform(
            self.robot_base_frame,
            URDF_FRAME_PELVIS,
            t_robot_pelvis,
            stamp,
            calibration_id,
            static=True,
        )
        self.base_pelvis_verified = True

    def update_robot_chain_from_joints(
        self, joint_positions: Dict[str, float], stamp: float, calibration_id: str
    ) -> Tuple[bool, str]:
        if self.urdf is None or self.urdf._pin is None:
            self.status = VerificationStatus.UNKNOWN
            return False, "urdf_not_loaded"
        if not self.base_pelvis_verified:
            self.status = VerificationStatus.UNKNOWN
            return False, "base_pelvis_transform_unverified"
        required = tuple(all_arm_joint_names())
        cfg = self.urdf.configure_required_joints(joint_positions, required)
        self._last_configure = cfg
        if not cfg.ok:
            self.status = VerificationStatus.UNKNOWN
            return False, cfg.message
        q = cfg.q
        w_pelvis = self.urdf.frame_placement(URDF_FRAME_PELVIS, q)
        w_torso = self.urdf.frame_placement(URDF_FRAME_TORSO, q)
        w_left = self.urdf.frame_placement(URDF_FRAME_LEFT_WRIST, q)
        w_right = self.urdf.frame_placement(URDF_FRAME_RIGHT_WRIST, q)
        w_cam = self.urdf.frame_placement(URDF_FRAME_HEAD_CAMERA, q)
        self.tf.set_transform(
            URDF_FRAME_PELVIS,
            URDF_FRAME_TORSO,
            compose_transform(invert_transform(w_pelvis), w_torso),
            stamp,
            calibration_id,
            static=False,
        )
        self.tf.set_transform(
            URDF_FRAME_TORSO,
            URDF_FRAME_LEFT_WRIST,
            compose_transform(invert_transform(w_torso), w_left),
            stamp,
            calibration_id,
            static=False,
        )
        self.tf.set_transform(
            URDF_FRAME_TORSO,
            URDF_FRAME_RIGHT_WRIST,
            compose_transform(invert_transform(w_torso), w_right),
            stamp,
            calibration_id,
            static=False,
        )
        self.tf.set_transform(
            URDF_FRAME_TORSO,
            self.camera_optical_frame,
            compose_transform(invert_transform(w_torso), w_cam),
            stamp,
            calibration_id,
            static=False,
        )
        if self.tcp_verified:
            for side, wrist, tcp in (
                ("left", URDF_FRAME_LEFT_WRIST, DEFAULT_LEFT_PINCH_TCP),
                ("right", URDF_FRAME_RIGHT_WRIST, DEFAULT_RIGHT_PINCH_TCP),
            ):
                if not tcp.verified:
                    continue
                t_tcp = transform_from_pose(tcp.position_xyz, tcp.orientation_xyzw)
                self.tf.set_transform(
                    wrist,
                    f"{side}_finger_tcp",
                    t_tcp,
                    stamp,
                    calibration_id,
                    static=True,
                )
        self._last_joint_stamp = stamp
        self.status = VerificationStatus.DOCUMENTED_UNVERIFIED
        return True, "ok"

    def is_robot_tf_fresh(self, now: Optional[float] = None, max_age_s: float = 0.25) -> bool:
        now = now or time.time()
        return self.base_pelvis_verified and (now - self._last_joint_stamp) <= max_age_s
