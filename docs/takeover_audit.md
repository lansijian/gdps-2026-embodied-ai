# GDPS S05 质检赛道 — Cursor 接管审计（2026-10-17）

## Git / 工作区状态（接管时）

| 项 | 值 |
|---|---|
| 分支 | `feat/quality-inspection-agent` |
| HEAD | `391f558`（与 `feat/shared-g1-field-bringup` 一致） |
| `main` 远端 | `65af162` |
| 未追踪文件 | 任务书 Markdown、`完整研究包.zip`、`深度技术研究报告.md`（非代码，未纳入提交） |

## Trae / 既有代码 — 已完成且可延续

| 区域 | 状态 | 说明 |
|---|---|---|
| `shared/navigation/` | **可复用** | MID-360→LaserScan、安全监督、Nav2 包、真机基线已文档化 |
| `shared/robot_control/g1/` | **可复用** | 行走 `G1MotionAdapter`、dry-run/live 门禁、MotionLock |
| `shared/perception/` | 占位 | 导航侧障碍在 `shared/navigation/perception/` |
| `scripts/g1/` | **可复用** | 部署、探测、preflight |
| `docs/deployment/g1-edu-field-baseline.md` | **CONFIRMED 基线** | Foxy、Topic、无 `/tf` 等 |
| `tests/navigation/` | **OFFLINE_TEST_PASS** | 29 项导航相关测试 |

## 质检赛道（接管前）

| 路径 | 状态 |
|---|---|
| `tracks/quality-inspection/` | 仅 README，**无 P1–P6 实现** |
| 机械臂 IK/TF/视觉/行为树 | **缺失**（任务书与深度报告为设计输入，非可执行代码） |

## 本轮新增（Cursor）

- `tracks/quality-inspection/gdps_qi/`：模块化质检栈（适配器、TF、标定、视觉位姿、抓取规划、安全门、技能 P1–P6、任务调度、证据与报告）
- `tests/quality_inspection/`：SE3、TF、视觉、IK、Dex3 模板、任务流、deadline、上传幂等
- `scripts/g1/qi_hardware_probe_readonly.py`：机载只读探测脚手架
- `docs/research/source_audit.md`、`docs/hardware_interface_matrix.md`、`tomorrow_field_checklist.md`、`docs/handover/quality-inspection-2026-10-17.md`

## 假设与风险

- G1 29DoF URDF、Pinocchio/CasADi 官方 IK：**未在 PC2 验证**；离线使用简化 7DoF 链 + 数值 IK，**不得**宣称与真机一致。
- 头部 RGB/Depth、Dex3 DDS、臂 SDK：**DOCUMENTED_UNVERIFIED**，默认 dry-run。
- 离心机启停：**无远程 API 证据**，代码仅逻辑联锁 + 人工授权位。

## 明显错误 / 需现场修正

- 现场无 `/tf`：工位 `table_frame` 必须每次站位后标定或测量更新，不能写死 `robot_center→table_frame` 常数上机。
- `lookup()` 依赖显式边与时间戳；静态标定边需 `static=True` 或定期刷新。
