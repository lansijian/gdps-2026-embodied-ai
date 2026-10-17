from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from gdps_qi.hardware.g1_joint_map import (
    DEFAULT_LEFT_PINCH_TCP,
    DEFAULT_RIGHT_PINCH_TCP,
    URDF_FRAME_HEAD_CAMERA,
    URDF_FRAME_LEFT_WRIST,
    URDF_FRAME_PELVIS,
    URDF_FRAME_RIGHT_WRIST,
    URDF_FRAME_TORSO,
)
from gdps_qi.kinematics.g1_urdf_model import G1UrdfModel
from gdps_qi.math_se3 import compose_transform, transform_from_pose
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
    _last_joint_stamp: float = 0.0

    def update_robot_chain_from_joints(
        self, joint_positions: Dict[str, float], stamp: float, calibration_id: str
    ) -> None:
        if self.urdf is None or not self.urdf._pin:
            self.status = VerificationStatus.UNKNOWN
            return
        from gdps_qi.math_se3 import invert_transform

        q = self.urdf.set_named_joints(joint_positions)
        t_base_pelvis = np.eye(4)
        self.tf.set_transform(self.robot_base_frame, URDF_FRAME_PELVIS, t_base_pelvis, stamp, calibration_id)
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
        for side, wrist, tcp in (
            ("left", URDF_FRAME_LEFT_WRIST, DEFAULT_LEFT_PINCH_TCP),
            ("right", URDF_FRAME_RIGHT_WRIST, DEFAULT_RIGHT_PINCH_TCP),
        ):
            t_tcp = transform_from_pose(tcp.position_xyz, tcp.orientation_xyzw)
            self.tf.set_transform(
                wrist,
                f"{side}_finger_tcp",
                t_tcp,
                stamp,
                calibration_id if tcp.verified else "tcp_unverified",
                static=tcp.verified,
            )
        self._last_joint_stamp = stamp
        self.status = VerificationStatus.DOCUMENTED_UNVERIFIED

    def set_table_from_camera_pnp(
        self, t_camera_table: np.ndarray, stamp: float, calibration_id: str
    ) -> None:
        self.tf.set_transform(
            self.camera_optical_frame,
            self.table_frame,
            t_camera_table,
            stamp,
            calibration_id,
            static=False,
        )

    def is_robot_tf_fresh(self, now: Optional[float] = None, max_age_s: float = 0.25) -> bool:
        now = now or time.time()
        return (now - self._last_joint_stamp) <= max_age_s
