from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from gdps_qi.adapters.camera import CameraAdapter, CameraFrame
from gdps_qi.math_se3 import (
    compose_transform,
    deproject_pixel,
    invert_transform,
    plane_ray_intersection,
    solve_pnp_planar,
    transform_point,
    undistort_normalized,
)
from gdps_qi.registry.object_registry import ObjectRegistry, SlotTemplate
from gdps_qi.transforms.transform_manager import TransformManager
from gdps_qi.types import PoseRecord, Uncertainty


@dataclass
class Detection:
    object_id: str
    label: str
    confidence: float
    bbox_xywh: Tuple[int, int, int, int]
    center_uv: Tuple[float, float]


@dataclass
class PoseEstimator:
    tf: TransformManager
    registry: ObjectRegistry
    max_grasp_position_error_m: float = 0.004

    def detect_tablet_ids_from_mock(self, frame: CameraFrame) -> List[Detection]:
        """Offline OCR substitute: read two-digit labels from solid-color blobs."""
        if frame.rgb is None:
            return []
        h, w = frame.rgb.shape[:2]
        detections: List[Detection] = []
        for sample_id, ident in self.registry.samples.items():
            slot = self.registry.tablet_slots[ident.tray_slot]
            u = int(w * (0.2 + 0.1 * ident.tray_slot))
            v = int(h * 0.55)
            detections.append(
                Detection(
                    object_id=f"tablet_{sample_id}",
                    label=sample_id,
                    confidence=0.92,
                    bbox_xywh=(u - 10, v - 10, 20, 20),
                    center_uv=(float(u), float(v)),
                )
            )
        return detections

    def estimate_table_pose_from_template(
        self, frame: CameraFrame, table_points: List[Tuple[float, float, float]], image_points: List[Tuple[float, float]]
    ) -> PoseRecord:
        info = frame.info
        t_cam_table = solve_pnp_planar(
            table_points,
            image_points,
            info.fx,
            info.fy,
            info.cx,
            info.cy,
        )
        stamp = frame.stamp
        self.tf.set_transform(
            "head_camera_optical",
            "table_frame",
            t_cam_table,
            stamp,
            info.calibration_id,
            static=False,
        )
        return PoseRecord(
            frame_id="head_camera_optical",
            stamp=stamp,
            position=(0.0, 0.0, 0.0),
            orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            object_id="table_frame",
            calibration_id=info.calibration_id,
            uncertainty=Uncertainty(0.003, 0.02, source="pnp_planar"),
            confidence=0.85,
            source="pnp",
        )

    def tablet_pose_in_base(
        self,
        sample_id: str,
        base_frame: str = "robot_center",
    ) -> PoseRecord:
        ident = self.registry.get_sample(sample_id)
        slot: SlotTemplate = self.registry.tablet_slots[ident.tray_slot]
        t_base_table = self.tf.lookup(base_frame, "table_frame")
        p_table = np.array(slot.position_table)
        p_base = transform_point(t_base_table, p_table)
        return PoseRecord(
            frame_id=base_frame,
            stamp=time.time(),
            position=(float(p_base[0]), float(p_base[1]), float(p_base[2])),
            orientation_xyzw=slot.orientation_xyzw,
            object_id=f"tablet_{sample_id}",
            calibration_id=self.tf.version,
            uncertainty=Uncertainty(0.0025, 0.015, source="slot_template"),
            confidence=0.9,
            source="registry_slot",
        )

    def pixel_to_table_point(
        self,
        u: float,
        v: float,
        frame: CameraFrame,
        depth_m: Optional[float],
    ) -> Tuple[bool, np.ndarray, str]:
        info = frame.info
        if depth_m is not None and depth_m > 0.05:
            p_cam = deproject_pixel(u, v, depth_m, info.fx, info.fy, info.cx, info.cy)
            try:
                t_cam_table = self.tf.lookup("head_camera_optical", "table_frame", frame.stamp)
            except Exception as exc:
                return False, p_cam, str(exc)
            p_tab = transform_point(invert_transform(t_cam_table), p_cam)
            return True, p_tab, "depth"
        ray = undistort_normalized(u, v, info.fx, info.fy, info.cx, info.cy)
        try:
            t_cam_table = self.tf.lookup("head_camera_optical", "table_frame", frame.stamp)
        except Exception as exc:
            return False, np.zeros(3), str(exc)
        t_table_cam = invert_transform(t_cam_table)
        origin = transform_point(t_table_cam, np.zeros(3))
        direction = transform_point(t_table_cam, ray) - origin
        ok, hit = plane_ray_intersection(
            origin,
            direction,
            plane_point=(0.0, 0.0, 0.0),
            plane_normal=(0.0, 0.0, 1.0),
        )
        if not ok:
            return False, hit, "ray_parallel"
        return True, hit, "plane_intersection"

    def validate_detections_unique(self, detections: List[Detection]) -> Tuple[bool, str]:
        labels = [d.label for d in detections]
        if len(labels) != 6:
            return False, "expected_six_tablets"
        if len(set(labels)) != 6:
            return False, "duplicate_labels"
        if not all(re.fullmatch(r"\d{2}", lb) for lb in labels):
            return False, "invalid_label_format"
        return True, "ok"
