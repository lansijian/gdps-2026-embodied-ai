from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraInfo
from gdps_qi.perception.camera_geometry import (
    ProjectionStatus,
    choose_lateral_direction_by_reprojection,
    make_t_base_camera,
    project_base_point_to_pixel,
    se2_apply_y,
    optical_to_base_rotation,
)
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
    trial_dy_m: float = 0.05
    min_improvement_px: float = 1.0


@dataclass
class LateralLoopIteration:
    iteration: int
    pixel_u: float
    pixel_du: float
    cmd_vy: float
    odom_y_before: float
    odom_y_after: float
    pixel_du_after: float
    lateral_choice: str
    projection_status: str


@dataclass
class LateralClosedLoopSimulator:
    """Offline replay: dry-run lateral commands + synthetic odom shift."""

    nav: SharedNavigator
    world_target: Tuple[float, float, float]
    t_base_camera: np.ndarray
    camera_info: CameraInfo
    cfg: LateralLoopConfig = field(default_factory=LateralLoopConfig)
    history: List[LateralLoopIteration] = field(default_factory=list)

    def _t_at_pose_y(self, pose_y: float) -> np.ndarray:
        t = self.t_base_camera.copy()
        return se2_apply_y(pose_y, t)

    def project_error(self, pose_y: float):
        pr = project_base_point_to_pixel(self.world_target, self._t_at_pose_y(pose_y), self.camera_info)
        return pr

    def run(self, initial_pose_y: float = 0.0) -> Tuple[bool, List[LateralLoopIteration]]:
        self.history.clear()
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
        pr0 = self.project_error(y)
        if pr0.status is not ProjectionStatus.OK:
            return False, self.history
        if abs(pr0.du) < 1e-3:
            return False, self.history
        for i in range(self.cfg.max_iterations):
            t_cam = self._t_at_pose_y(y)
            lat, du_before, du_candidate = choose_lateral_direction_by_reprojection(
                self.world_target, t_cam, self.camera_info, self.cfg.trial_dy_m
            )
            if lat == "none":
                break
            intent = MotionIntent.LATERAL_LEFT if lat == "left" else MotionIntent.LATERAL_RIGHT
            cmd = self.nav.preview_motion(intent, speed_scale=self.cfg.vy_scale)
            dy = cmd.vy * self.cfg.step_dt_s * self.cfg.odom_vy_to_dy
            y_before = y
            y += dy
            pr_after = self.project_error(y)
            du_after = pr_after.du if pr_after.status is ProjectionStatus.OK else du_before
            self.history.append(
                LateralLoopIteration(
                    iteration=i,
                    pixel_u=self.camera_info.cx + du_before,
                    pixel_du=du_before,
                    cmd_vy=cmd.vy,
                    odom_y_before=y_before,
                    odom_y_after=y,
                    pixel_du_after=du_after,
                    lateral_choice=lat,
                    projection_status=pr_after.status.value,
                )
            )
            if pr_after.status is not ProjectionStatus.OK:
                break
            if abs(du_after) < self.cfg.pixel_tolerance_px:
                ok = True
                break
            if abs(du_after) + self.cfg.min_improvement_px < abs(du_before):
                du_before = du_after
                continue
            break
        return ok, self.history
