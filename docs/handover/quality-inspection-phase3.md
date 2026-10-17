# Phase 3 — 只读硬件、TF、P1-01 定位

## Git

- 分支：`feat/quality-inspection-agent`
- Phase 2 远端：`0073dbc`（已 push）
- Phase 3：见最新 commit

## 机载第一批只读命令（人工 SSH 后执行）

```bash
cd ~/gdps-2026-embodied-ai   # 或同步后的仓库路径
export GDPS_QI_EXECUTION_MODE=field
export GDPS_G1_URDF_PATH=/path/to/g1_body29_hand14.urdf   # 从 xr_teleoperate 拷贝后填写

# 1) 结构化诊断（默认 dry-run，不订阅）
python3 scripts/g1/qi_hardware_diagnostics.py

# 2) 现场确认 Topic 后复制 example yaml，再 live 探测（只读）
cp tracks/quality-inspection/configs/g1/qi_topics_readonly.example.yaml /tmp/qi_topics.yaml
# 编辑 /tmp/qi_topics.yaml 填入实测 rgb/joint_states 等
python3 scripts/g1/qi_hardware_diagnostics.py --live --timeout 5 --config /tmp/qi_topics.yaml

# 3) P1 只读规划（simulation 仅开发机）
export GDPS_QI_EXECUTION_MODE=simulation
python3 -c "
from gdps_qi.mission.mission_controller import MissionController
from gdps_qi.types import SkillRequest
import numpy as np, os
os.environ['GDPS_QI_EXECUTION_MODE']='simulation'
mc = MissionController.build_offline()
mc.register_simulation_workstation()
rgb = np.zeros((480,640,3), dtype=np.uint8); rgb[100:380,120:520]=210
mc.executor.camera.set_mock_frame(rgb)
print(mc.executor.run(SkillRequest('P1_LOCALIZE_01','01',{},[],False,{'use_mock_detections':True,'allow_relative_table':True}), mc._safety_context()))
"
```

## 仍待现场确认

- 头部相机 ROS Topic / teleimager URL、CameraInfo、Depth 对齐
- `/joint_states` 是否存在；否则 LowState DDS 索引映射
- Dex3 HandState 电流/触觉字段
- `head_camera_link` 与光学系外参标定
- 指尖 TCP 实测
