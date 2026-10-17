# 给 Codex 的明确开发任务：G1 运控基线与 2026-10-18 S05 视觉示教

**执行边界**：只操作仓库，不 SSH 实机，不发布真实电机/运动指令，不部署；采用 `feat/quality-inspection-agent` 的最新状态为基线，另外建立功能分支、commit、push 并发起 Draft PR。不得覆盖已有 S05 感知/TF/导航代码。

## 输入文件和权威证据

1. `docs/training-logs/quality-inspection/2026-10-17-motion-field-baseline.md`：今天已发生的动作与限制。
2. `docs/deployment/2026-10-18-g1-rgbd-teach-sop.md`：明天的安全 Gate 与动作时序。
3. `shared/robot_control/g1/`：已有 `G1MotionAdapter`、`UnitreeLocoBackend`、Mock、锁和 dry-run；优先复用。
4. `tracks/quality-inspection/gdps_qi/centering/`、`perception/rgbd_target_geometry.py`、`centering/manipulation_ready.py`：已实现的只读 RGB-D 与居中/可操作性门禁。
5. `scripts/g1/g1_arm_readonly_capture.py`、`shared/robot_control/g1/teach_trajectory.py`：新加入的只读示教采集与离线轨迹功能。
6. PC2 本地的 DeepSeek 原始脚本未在 GitHub，须由操作员**另行审查后提供**。不重写为“复原的已验收脚本”，不把事故脚本部署进可运行入口。

## 请在后续 Codex 迭代实现（本轮不等于已完成）

- M1：抽象**只读** `G1StateSnapshot`（FSM API 7001、mode_machine、MotionSwitcher、IMU、q/dq/tau_est、采样鲜度）。注意查询 RPC 非零即失败；不得用 `SetFsmId()` 代替查询。
- M2：设计 `MotionArbiter`，控制模式变迁走人工批准状态机；行走、原厂 ArmAction、`rt/arm_sdk`、Dex3 不得双主写；未知模式 fail-closed。未经厂商核对不得自动 Debug/501/801/6。
- M3：将 10-17 运动实验的程序**仅作为历史输入**，把真正经过复验的腿部 API、上肢动作转换为独立 backend，先 Mock；步行 RPC=0 不能证明实际位移；停止必须有独立传感反馈验证。
- M4：`ArmSDK` 控制器要兼容**动作中控制权重达到 1.0**、平滑交接以及 q/dq/tau_est 与 IMU 读数；未知腰部权限/高刚度不可硬编码。异常时不可因姿态守卫拒绝发送释放/安全退出，但任何“释放”也不能承诺自动防跌倒。
- M5：设计统一的只读相机/深度/TF 观测接口、目标 ID 锁定、居中**预览**、人工授权的限幅单步规划、任务状态机；禁止以单个像素误差直接给腰部或电机下发角度。
- M6：离线示教 JSONL → 数据质量门禁 → Kalman 平滑 → 关键帧分段 → URDF/FK/TCP 和自碰撞离线检查 → **仿真**复放；真实手动拖臂需厂家确认与安全吊架，禁止关闭全身平衡。
- M7：Dex3 先只读订阅/验证设备；真实抓取/视觉伺服留待独立验收。任务编排为 `PRECHECK/OBSERVE/CENTER/STOP/BODY_READY/ARM/GRASP/RETRACT`，状态与责任日志完整。

## 必测离线反例

FSM 查询失败、模式不明、SDK lease 冲突、双控制源同时写、DDS 数据陈旧、低质量深度/TF、目标 ID 突变、关节 NaN/越限、腰部异常耦合、机械臂 q 跳变、轨迹时钟回退、设备断连、抓取失败、无人批准、离线数据误接 live backend。另覆盖“高层 RPC=0 但物理没动”和“倾角异常时原异常处理无法发零权重”的已知风险。

## 验收输出

- 提交最小可复审 PR，说明改动/未改动的真实硬件接口；测试日志、commit SHA、变更文件与迁移风险。
- 单测、端到端 dry-run、静态语法检查、必要时 Windows/Linux 兼容测试。
- 禁止在 CI/GitHub Actions/Mock 中通过环境变量误激活 DDS live 写。
- 现场无人确认或未提供可靠防跌落装置，则所有写动作保持 DISABLED。不可把视频居中模拟成功、Kalman 输出或历史实机口述标成真机抓取通过。
