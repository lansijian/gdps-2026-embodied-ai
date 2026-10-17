from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraFrame, CameraInfo
from gdps_qi.math_se3 import deproject_pixel, make_transform, transform_point
from gdps_qi.perception.detection_types import Detection
from shared.navigation.api.navigator import MotionIntent, SharedNavigator
from shared.navigation.api.types import Pose2D
from shared.navigation.perception.obstacle_monitor import ScanFrame


@dataclass
class LateralLoopConfig:
    vy_scale: float = 0.5
    step_dt_s: float = 0.5
    odom_vy_to_dy: float = 1.0
    pixel_tolerance_px: float = 15.0
    max_iterations: int = 8


@dataclass
class LateralLoopIteration:
    iteration: int
    pixel_u: float
    pixel_du: float
    bearing_rad: float
    cmd_vy: float
    odom_y_before: float
    odom_y_after: float
    pixel_du_after: float


@dataclass
class LateralClosedLoopSimulator:
    """Offline replay: dry-run lateral commands + synthetic odom shift."""

    nav: SharedNavigator
    world_target: Tuple[float, float, float]
    t_base_camera: np.ndarray
    camera_info: CameraInfo
    cfg: LateralLoopConfig = field(default_factory=LateralLoopConfig)
    history: List[LateralLoopIteration] = field(default_factory=list)

    @staticmethod
    def optical_to_base_rotation() -> np.ndarray:
        """ROS optical (x right, y down, z forward) with base x forward, y left, z up."""
        return np.array([[0.0, -1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]], dtype=float)

    def _project_pixel_error(self, pose_y: float) -> Tuple[float, float, float]:
        """Fixed target in base; robot lateral offset shifts camera +Y."""
        t = self.t_base_camera.copy()
        if np.allclose(t[:3, :3], np.eye(3)):
            t[:3, :3] = self.optical_to_base_rotation()
        t[1, 3] = float(t[1, 3]) + pose_y
        t_cam_base = np.linalg.inv(t)
        p_b = np.array([self.world_target[0], self.world_target[1], self.world_target[2], 1.0])
        p_c = t_cam_base @ p_b
        if p_c[2] <= 0.01:
            return self.camera_info.cx, 0.0, 0.0
        u = self.camera_info.fx * (p_c[0] / p_c[2]) + self.camera_info.cx
        du = u - self.camera_info.cx
        bearing = math.atan2(self.world_target[1] - pose_y, max(self.world_target[0], 0.05))
        return u, du, bearing

    def run(self, initial_pose_y: float = 0.0) -> Tuple[bool, List[LateralLoopIteration]]:
        pose = Pose2D(0.0, initial_pose_y, 0.0, "odom")
        self.nav.safety.require_sensor = False
        self.nav.safety.require_odom = False
        self.nav.on_scan(
            ScanFrame(
                ranges=tuple([5.0] * 21),
                angle_min=-0.5,
                angle_increment=0.05,
            )
        )
        self.nav.on_pose(pose)
        self.nav.start()
        y = initial_pose_y
        ok = False
        for i in range(self.cfg.max_iterations):
            u, du, bearing = self._project_pixel_error(y)
            intent = MotionIntent.LATERAL_LEFT if bearing > 0 else MotionIntent.LATERAL_RIGHT
            cmd = self.nav.preview_motion(intent, speed_scale=self.cfg.vy_scale)
            dy = cmd.vy * self.cfg.step_dt_s * self.cfg.odom_vy_to_dy
            y_before = y
            y += dy
            pose = Pose2D(0.0, y, 0.0, "odom")
            self.nav.on_pose(pose)
            _, du_after, _ = self._project_pixel_error(y)
            self.history.append(
                LateralLoopIteration(
                    iteration=i,
                    pixel_u=u,
                    pixel_du=du,
                    bearing_rad=bearing,
                    cmd_vy=cmd.vy,
                    odom_y_before=y_before,
                    odom_y_after=y,
                    pixel_du_after=du_after,
                )
            )
            if abs(du_after) < self.cfg.pixel_tolerance_px:
                ok = True
                break
            if abs(du_after) >= abs(du):
                break
        return ok, self.history
