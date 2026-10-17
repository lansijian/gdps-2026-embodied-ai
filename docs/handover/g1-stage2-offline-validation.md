# G1第二阶段离线交付检查

日期：2026-10-17。基线 `7e6bdb62e39b7b5d98c6d393a4808b8abeaf03ba`，分支 `codex/g1-field-baseline-stage2-20261017`；以原功能分支为 Draft PR 目标，不合并main。

## 已执行

- 检查Git状态并将此前未提交改动备份到ignored `dist/work-in-progress-before-g1-stage2-20261017/`。沿用、审查此前G1门禁改动；没有覆盖用户删除的 tomorrow_field_checklist.md，原始输入包/旧交接文档不混入提交。
- 读取提供的离线目录、HANDOFF及用户粘贴代码；27条/27代码块归档为不可运行文本。原文SHA256 `d4b4a04861f3b8f67a4e132891f2f27b88e259f73c13c0a70e699b31468c27e0`。起身RPC返回值冲突、腰部末值/变化量与跟踪精度已澄清，未复现实机实验。
- `python -m pytest tests/ -q -rs --junitxml=dist/g1-stage2-tests.xml`：**219 passed, 4 skipped**（Windows Python3.11.4）。包含73项G1 backend、控制门禁、采集清理、轨迹质量/滤波及预览集成测试；既有导航/质检测试通过。只使用Mock/fake SDK；没有真实运动调用。
- 4项跳过：Windows无rclpy/Foxy的ROS合约1项、无Pinocchio的运动学3项，不能视为通过。
- 16个G1相关Python源文件按Python3.8语法解析通过；没有Python3.8/Linux/Foxy运行时测试，不声称机载兼容已实测。
- CLI合成数据：readonly status标记SYNTHETIC_TEST且execute_allowed=false；完整17关节JSONL分析成功、时钟回退拒绝、源数据保留。capture CLI注入假Subscriber验证成功及Init失败均Close，禁止Publisher。
- `git diff --check`通过（Windows换行提示不影响检查）。没有修改导航架构、机械动作P1–P6或依赖安装/机载服务。

## 代码映射

| 范围 | 文件 |
|---|---|
| 复用适配器/锁/dry-run并完善失败门禁 | shared/robot_control/g1/{adapter,loco_backend,loco_readonly,mock_backend,__init__}.py；MotionLock原实现不变 |
| 只读状态证据与诊断 | shared/robot_control/g1/motion_evidence.py；scripts/g1/g1_motion_diag_readonly.py |
| 臂/腰观测、离线质量与Kalman | shared/robot_control/g1/teach_trajectory.py；scripts/g1/{g1_arm_readonly_capture,analyze_teach_trajectory}.py |
| 现有RGB-D/TF/居中/可达性组合 | tracks/quality-inspection/gdps_qi/centering/teaching_preview.py |
| 回归 | tests/robot_control/；tests/navigation/test_safety_and_nav.py仅补Mock授权 |
| 安全白名单打包 | scripts/g1/package_g1_stage2.py；复用package_phase44.py白名单 |
| 现场事实与原始源码 | docs/training-logs/quality-inspection/2026-10-17-motion-field-baseline.md及2026-10-17-source-archive/ |
| 下一轮流程和命令 | docs/deployment/g1-stage2-readonly.md；2026-10-18-g1-rgbd-teach-sop.md |

## 明确保留的缺口

无真机网络连接、无PC2部署、无FSM写/无阻力/步行/机械臂/手部运动。未实现ArmSDK轨迹执行器、控制权arbiter运行时、重力补偿示教、FK/碰撞仿真或抓取验证，交接中的M1–M7后续建议不能宣称已全部完成。当前MotionSnapshot与关节采样是只读证据，未提供完整同步29关节+MotionSwitcher+相机合同；后者留待真实数据核验后收敛。

权重1.0仅保留实验经验；渐变/退出是未来执行器的必需审查条件，本次没有新增写接口。未知固件/lease、腰控制权与高刚度参数、跌倒根因、Dex3设备、真实标定/TCP/URDF/仿真均待现场与厂家证据。停止回执、视频运动观察都不提升为本包硬件动作授权。

下一步只获取真实静态传感器/关节数据并离线分析；没有可靠防跌落保护、厂家支持路径及另行逐项授权前，不动态复验。本轮交付后停止编码。
