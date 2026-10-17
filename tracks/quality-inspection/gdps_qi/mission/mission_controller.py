from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from gdps_qi.adapters.camera import CameraAdapter
from gdps_qi.adapters.dex3_hand import Dex3HandAdapter
from gdps_qi.adapters.robot_hardware import RobotHardwareAdapter
from gdps_qi.evidence.evidence_recorder import EvidenceRecorder
from gdps_qi.execution.skill_executor import SkillExecutor
from gdps_qi.kinematics.kinematics_backend import (
    G1UrdfKinematicsAdapter,
    SimplifiedTestKinematics,
)
from gdps_qi.mission.deadline_manager import DeadlineManager
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.planning.motion_safety_gate import MotionSafetyGate, SafetyContext
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.runtime.execution_mode import ExecutionMode, allow_simulation_assets, get_execution_mode
from gdps_qi.skills.p1_localize import register_p1_localize_skills
from gdps_qi.skills.p1_tablet import register_p1_skills
from gdps_qi.transforms.g1_tf_chain import G1TfChain
from gdps_qi.skills.p2_tube import P2State, register_p2_skills
from gdps_qi.skills.p3_centrifuge import CentrifugeState, register_p3_skills
from gdps_qi.skills.p4_p5_p6 import MissionTailState, register_p456_skills
from gdps_qi.transforms.calibration_manager import CalibrationManager
from gdps_qi.transforms.transform_manager import TransformManager
from gdps_qi.types import MissionPhase, SkillRequest, SkillResult


@dataclass
class MissionController:
    registry: ObjectRegistry
    tf: TransformManager
    calibration: CalibrationManager
    deadline: DeadlineManager
    executor: SkillExecutor
    execution_mode: ExecutionMode = ExecutionMode.FIELD
    p2_state: P2State = field(default_factory=P2State)
    p3_state: CentrifugeState = field(default_factory=CentrifugeState)
    tail_state: MissionTailState = field(default_factory=MissionTailState)
    phase: MissionPhase = MissionPhase.P1_TABLET
    _sim_workstation_registered: bool = False
    results: List[SkillResult] = field(default_factory=list)
    g1_tf: Optional[G1TfChain] = None

    @classmethod
    def build(
        cls,
        calibration_path: Optional[Path] = None,
        urdf_path: Optional[str] = None,
        execution_mode: Optional[ExecutionMode] = None,
    ) -> "MissionController":
        mode = execution_mode or get_execution_mode()
        registry = ObjectRegistry.default_six_sample_layout()
        tf = TransformManager(max_age_s=2.0)
        calibration = CalibrationManager()
        if calibration_path and calibration_path.is_file():
            calibration.load_yaml(calibration_path)
            calibration.apply_to_transform_manager(tf)
        else:
            calibration.bundle = None
        robot = RobotHardwareAdapter()
        hands = Dex3HandAdapter()
        camera = CameraAdapter()
        robot.connect()
        hands.connect()
        camera.connect()
        pose_estimator = PoseEstimator(tf=tf, registry=registry)
        if mode is ExecutionMode.SIMULATION:
            kinematics = SimplifiedTestKinematics()
        else:
            kinematics = G1UrdfKinematicsAdapter(
                urdf_path=urdf_path or os.environ.get("GDPS_G1_URDF_PATH"),
                verified_on_robot=False,
            )
        grasp_planner = GraspPlanner(registry=registry, kinematics=kinematics)
        safety = MotionSafetyGate(calibration=calibration)
        evidence = EvidenceRecorder(output_dir=Path("logs/quality-inspection"))
        executor = SkillExecutor(
            robot=robot,
            hands=hands,
            camera=camera,
            pose_estimator=pose_estimator,
            grasp_planner=grasp_planner,
            safety=safety,
            evidence=evidence,
        )
        g1_tf = None
        if isinstance(kinematics, G1UrdfKinematicsAdapter) and kinematics._model:
            g1_tf = G1TfChain(tf=tf, urdf=kinematics._model)
        mc = cls(
            registry=registry,
            tf=tf,
            calibration=calibration,
            deadline=DeadlineManager(),
            executor=executor,
            execution_mode=mode,
            p2_state=P2State(),
            p3_state=CentrifugeState(),
            tail_state=MissionTailState(),
            g1_tf=g1_tf,
        )
        mc._register_skills()
        return mc

    @classmethod
    def build_offline(cls, calibration_path: Optional[Path] = None) -> "MissionController":
        os.environ["GDPS_QI_EXECUTION_MODE"] = "simulation"
        return cls.build(calibration_path=calibration_path, execution_mode=ExecutionMode.SIMULATION)

    def _register_skills(self) -> None:
        register_p1_skills(self.executor)
        register_p1_localize_skills(self.executor, self.g1_tf)
        register_p2_skills(self.executor, self.p2_state)
        register_p3_skills(self.executor, self.p3_state)
        register_p456_skills(self.executor, self.tail_state)

    def register_simulation_workstation(self) -> None:
        if not allow_simulation_assets():
            raise RuntimeError("simulation workstation only allowed in SIMULATION mode")
        if self._sim_workstation_registered:
            return
        stamp = time.time()
        cid = "simulation_not_verified"
        self.tf.set_transform(
            "robot_center",
            "table_frame",
            np.array(
                [
                    [1, 0, 0, 0.28],
                    [0, 1, 0, 0.05],
                    [0, 0, 1, 0.42],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            ),
            stamp,
            cid,
            static=False,
        )
        self.tf.set_transform(
            "head_camera_optical",
            "table_frame",
            np.eye(4),
            stamp,
            cid,
            static=False,
        )
        self._sim_workstation_registered = True

    def _safety_context(self, live: bool = False) -> SafetyContext:
        ok_cal, _ = self.calibration.is_valid()
        sim_ok = allow_simulation_assets() and self._sim_workstation_registered
        return SafetyContext(
            live_motion_authorized=live,
            calibration_ok=ok_cal or sim_ok,
            tf_version=self.tf.version,
            owner=self.executor.robot.owner,
            contact_allowed=False,
            centrifuge_start_allowed=False,
        )

    def run_offline_p1_sample01(self) -> SkillResult:
        self.register_simulation_workstation()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[200:280, 250:350] = 180
        self.executor.camera.set_mock_frame(rgb)
        req = SkillRequest(
            skill_name="P1_PICK_TABLET_01",
            sample_id="01",
            object_refs={"tablet": "01"},
            calibration_refs=["simulation_not_verified"],
            allowed_actuation=False,
            safety_context={"use_mock_detections": True},
        )
        result = self.executor.run(req, self._safety_context())
        self.results.append(result)
        return result

    def run_full_offline_mission(self) -> Dict[str, object]:
        self.register_simulation_workstation()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb[200:280, 250:350] = 180
        self.executor.camera.set_mock_frame(rgb)
        ctx = self._safety_context()
        summary: Dict[str, object] = {"samples": {}, "phases": []}
        for i, sid in enumerate([f"{x:02d}" for x in range(1, 7)], start=1):
            if not self.deadline.should_continue(samples_remaining=7 - i)[0]:
                summary["aborted"] = "deadline"
                break
            r1 = self.executor.run(
                SkillRequest(
                    skill_name="P1_PICK_TABLET",
                    sample_id=sid,
                    object_refs={},
                    calibration_refs=[],
                    allowed_actuation=False,
                    safety_context={"use_mock_detections": True},
                ),
                ctx,
            )
            r2 = self.executor.run(
                SkillRequest(
                    skill_name="P2_PREP_SAMPLE",
                    sample_id=sid,
                    object_refs={},
                    calibration_refs=[],
                    allowed_actuation=False,
                    safety_context={
                        "allow_simulation_mass": True,
                        "mock_mass_g": 10.0 + int(sid),
                        "allow_simulation_unscrew": True,
                        "unscrew_steps": 2,
                        "verified_cap_open": True,
                        "verified_tablet_inserted": True,
                        "verified_cap_closed": True,
                    },
                ),
                ctx,
            )
            summary["samples"][sid] = {"P1": r1.status, "P2": r2.status}
        load_order = [f"{i:02d}" for i in range(1, 7)]
        r3 = self.executor.run(
            SkillRequest(
                skill_name="P3_LOAD_AND_ARM",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={
                    "load_order": load_order,
                    "masses_g": {sid: 10.0 + int(sid) for sid in load_order},
                    "all_sealed": True,
                    "lid_closed": True,
                },
            ),
            ctx,
        )
        r4 = self.executor.run(
            SkillRequest(
                skill_name="P4_UNLOAD",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={
                    "tube_ids": load_order,
                    "simulation_centrifuge_stopped": True,
                },
            ),
            ctx,
        )
        for sid in load_order:
            self.executor.run(
                SkillRequest(
                    skill_name="P5_QC",
                    sample_id=sid,
                    object_refs={},
                    calibration_refs=[],
                    allowed_actuation=False,
                    safety_context={"visible": {"leak": "no", "crack": "no"}},
                ),
                ctx,
            )
        r6 = self.executor.run(
            SkillRequest(
                skill_name="P6_SORT_REPORT",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"idempotency_key": "offline_run"},
            ),
            ctx,
        )
        summary["phases"] = {
            "P3": r3.status,
            "P4": r4.status,
            "P6": r6.status,
            "deadline_remaining_s": self.deadline.remaining_s(),
        }
        return summary
