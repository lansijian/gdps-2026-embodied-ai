# 质检赛道交接 — 2026-10-17（Cursor）

## 运行（Windows 离线）

```powershell
cd E:\GDPS\competition
python -m pytest tests/quality_inspection -q
python -m pytest tests/ -q
```

```python
from gdps_qi.mission.mission_controller import MissionController
mc = MissionController.build_offline()
summary = mc.run_full_offline_mission()
print(summary)
```

需将 `tracks/quality-inspection` 加入 `PYTHONPATH`，或使用仓库 `tests/conftest.py` 自动注入。

## 模块索引

| 组件 | 路径 |
|---|---|
| RobotHardwareAdapter | `gdps_qi/adapters/robot_hardware.py` |
| CameraAdapter | `gdps_qi/adapters/camera.py` |
| Dex3HandAdapter | `gdps_qi/adapters/dex3_hand.py` |
| TransformManager | `gdps_qi/transforms/transform_manager.py` |
| CalibrationManager | `gdps_qi/transforms/calibration_manager.py` |
| ArmKinematics | `gdps_qi/kinematics/arm_kinematics.py` |
| ObjectRegistry | `gdps_qi/registry/object_registry.py` |
| PoseEstimator | `gdps_qi/perception/pose_estimator.py` |
| GraspPlanner | `gdps_qi/planning/grasp_planner.py` |
| MotionSafetyGate | `gdps_qi/planning/motion_safety_gate.py` |
| SkillExecutor | `gdps_qi/execution/skill_executor.py` |
| MissionController | `gdps_qi/mission/mission_controller.py` |
| DeadlineManager | `gdps_qi/mission/deadline_manager.py` |
| EvidenceRecorder | `gdps_qi/evidence/evidence_recorder.py` |
| ReportUploader | `gdps_qi/evidence/report_uploader.py` |

## 测试标记

| 范围 | 标记 |
|---|---|
| 单元/离线集成 | **OFFLINE_TEST_PASS**（见 pytest） |
| 代码完整度 | **CODE_COMPLETE**（P1–P6 逻辑链 + dry-run 执行） |
| 真机 READ | **HARDWARE_READ_VERIFIED** — 仅导航基线文档，质检未测 |
| 真机动作 | **未标记 LIVE_ACTION_VERIFIED** |

## 已知缺口

- 官方 `G1_29_ArmIK` 未移植；简化 IK 仅用于离线。
- 报告上传无赛方 ACK 时保存 `logs/quality-inspection/pending_uploads/`。
- 所有接触动作默认 `SAFE_HOLD` 直至标定 + live 授权。
