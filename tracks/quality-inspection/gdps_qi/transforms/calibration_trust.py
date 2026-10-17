from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from gdps_qi.adapters.readonly.joint_snapshot import JointSnapshot, JointValidity
from gdps_qi.transforms.calibration_manager import CalibrationManager


@dataclass
class CalibrationTrust:
    camera_info_fresh: bool = False
    table_calibrated: bool = False
    robot_joints_valid: bool = False
    base_pelvis_verified: bool = False
    tf_chain_fresh: bool = False
    tcp_verified: bool = False
    calibration_id: str = ""
    max_age_s: float = 0.25

    def allows_calibrated_world(self, now: Optional[float] = None) -> Tuple[bool, List[str]]:
        now = now or time.time()
        reasons: List[str] = []
        if not self.table_calibrated:
            reasons.append("table_not_calibrated")
        if not self.camera_info_fresh:
            reasons.append("camera_info_not_fresh")
        if not self.robot_joints_valid:
            reasons.append("robot_joints_invalid")
        if not self.base_pelvis_verified:
            reasons.append("base_pelvis_unverified")
        if not self.tf_chain_fresh:
            reasons.append("tf_chain_stale")
        return (len(reasons) == 0, reasons)

    @classmethod
    def from_sources(
        cls,
        calibration: CalibrationManager,
        joint_snapshot: Optional[JointSnapshot],
        joint_stamp: Optional[float],
        base_pelvis_verified: bool,
        tf_last_stamp: float,
        camera_info_stamp: Optional[float],
        tcp_verified: bool,
    ) -> "CalibrationTrust":
        ok_cal, _ = calibration.is_valid()
        now = time.time()
        joints_ok = (
            joint_snapshot is not None
            and joint_snapshot.validity is JointValidity.VALID
            and joint_snapshot.stamp_sec is not None
        )
        cam_ok = camera_info_stamp is not None and (now - camera_info_stamp) <= 1.0
        tf_ok = tf_last_stamp > 0 and (now - tf_last_stamp) <= 0.25
        cid = calibration.bundle.calibration_id if calibration.bundle else ""
        return cls(
            camera_info_fresh=cam_ok,
            table_calibrated=ok_cal,
            robot_joints_valid=joints_ok,
            base_pelvis_verified=base_pelvis_verified,
            tf_chain_fresh=tf_ok,
            tcp_verified=tcp_verified,
            calibration_id=cid,
        )
