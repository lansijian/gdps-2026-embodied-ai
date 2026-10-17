from __future__ import annotations

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
from gdps_qi.kinematics.arm_kinematics import ArmKinematics
from gdps_qi.mission.deadline_manager import DeadlineManager
from gdps_qi.perception.pose_estimator import PoseEstimator
from gdps_qi.planning.grasp_planner import GraspPlanner
from gdps_qi.planning.motion_safety_gate import MotionSafetyGate, SafetyContext
from gdps_qi.registry.object_registry import ObjectRegistry
from gdps_qi.skills.p1_tablet import register_p1_skills
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
    p2_state: P2State = field(default_factory=P2State)
    p3_state: CentrifugeState = field(default_factory=CentrifugeState)
    tail_state: MissionTailState = field(default_factory=MissionTailState)
    phase: MissionPhase = MissionPhase.P1_TABLET
    _global_registered: bool = False
    results: List[SkillResult] = field(default_factory=list)

    @classmethod
    def build_offline(cls, calibration_path: Optional[Path] = None) -> "MissionController":
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
        kinematics = ArmKinematics()
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
        mc = cls(
            registry=registry,
            tf=tf,
            calibration=calibration,
            deadline=DeadlineManager(),
            executor=executor,
            p2_state=P2State(),
            p3_state=CentrifugeState(),
            tail_state=MissionTailState(),
        )
        mc._register_skills()
        return mc

    def _register_skills(self) -> None:
        register_p1_skills(self.executor)
        register_p2_skills(self.executor, self.p2_state)
        register_p3_skills(self.executor, self.p3_state)
        register_p456_skills(self.executor, self.tail_state)

    def register_workstation_once(self) -> None:
        if self._global_registered:
            return
        # Static edges for offline demo; field replaces with measured calibration.
        stamp = time.time()
        cid = "offline_demo"
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
            "table_frame",
            "scale_frame",
            np.eye(4),
            stamp,
            cid,
            static=True,
        )
        self._global_registered = True

    def _safety_context(self, live: bool = False) -> SafetyContext:
        ok_cal, _ = self.calibration.is_valid()
        if self.calibration.bundle is None:
            ok_cal = True  # offline demo allows mock TF registration
        return SafetyContext(
            live_motion_authorized=live,
            calibration_ok=ok_cal or self._global_registered,
            tf_version=self.tf.version,
            owner=self.executor.robot.owner,
            contact_allowed=False,
            centrifuge_start_allowed=False,
        )

    def run_offline_p1_sample01(self) -> SkillResult:
        self.register_workstation_once()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.executor.camera.set_mock_frame(rgb)
        req = SkillRequest(
            skill_name="P1_PICK_TABLET_01",
            sample_id="01",
            object_refs={"tablet": "01"},
            calibration_refs=["offline_demo"],
            allowed_actuation=False,
            safety_context={},
        )
        result = self.executor.run(req, self._safety_context())
        self.results.append(result)
        return result

    def run_full_offline_mission(self) -> Dict[str, object]:
        self.register_workstation_once()
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.executor.camera.set_mock_frame(rgb)
        ctx = self._safety_context()
        summary: Dict[str, object] = {"samples": {}, "phases": []}
        for sid in [f"{i:02d}" for i in range(1, 7)]:
            if not self.deadline.should_continue(("P1", "P2"))[0]:
                summary["aborted"] = "deadline"
                break
            r1 = self.executor.run(
                SkillRequest(
                    skill_name="P1_PICK_TABLET",
                    sample_id=sid,
                    object_refs={},
                    calibration_refs=[],
                    allowed_actuation=False,
                    safety_context={},
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
                    safety_context={"mock_mass_g": 10.0 + int(sid)},
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
        self.tail_state.centrifuge_stopped = True
        r4 = self.executor.run(
            SkillRequest(
                skill_name="P4_UNLOAD",
                sample_id="",
                object_refs={},
                calibration_refs=[],
                allowed_actuation=False,
                safety_context={"tube_ids": load_order, "force_stopped": True},
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
