# 开源源码研读审计（GDPS S05 质检）

> 研读方式：对照官方仓库目录结构与公开 API；**未在 Windows 克隆完整第三方树进仓库**（见 `.gitignore` `.research/`）。版本以 2026-10-17 默认分支为参考，上机前须 pin commit。

## A. 宇树真机与控制

### 1. unitree_sdk2 (BSD-3-Clause)

| 项 | 内容 |
|---|---|
| URL | https://github.com/unitreerobotics/unitree_sdk2 |
| 关键路径 | `example/g1/dex3/g1_dex3_example.cpp`（HandCmd/HandState、左右索引）；`example/g1/high_level/g1_arm7_sdk_dds_example.cpp`；`example/g1/low_level/g1_dual_arm_example.cpp`（**低层风险，不运行**） |
| 可复用 | DDS 话题命名、Dex3 关节索引与限位概念、臂高层 SDK 模式 |
| 不复用 | 直接运行低层接管示例；未验证的 motor 索引写入生产 |
| 兼容性 | C++；机载 ARM64 需交叉/原生编译；与 Foxy 并存需隔离进程 |
| 决策 | **借鉴接口表**；真机臂/手走独立 Adapter + 独占 Owner |

### 2. unitree_sdk2_python (BSD-3-Clause)

| 项 | 内容 |
|---|---|
| URL | https://github.com/unitreerobotics/unitree_sdk2_python |
| 关键路径 | `example/g1/high_level/g1_arm7_sdk_dds_example.py`；`unitree_sdk2py/idl` |
| 可复用 | Python 侧 CycloneDDS 通道模式 |
| 风险 | Python 3.8 + 机载依赖未实测；与 ROS2 节点混用易双写电机 |
| 决策 | 明天 PC2 只读订阅验证；**今日不安装到仓库**

### 3. xr_teleoperate (MIT)

| 项 | 内容 |
|---|---|
| URL | https://github.com/unitreerobotics/xr_teleoperate |
| 关键路径 | `teleop/robot_control/robot_arm_ik.py`（`G1_29_ArmIK`）；`robot_hand_unitree.py`（`Dex3_1_Controller`）；`assets/g1/g1_body29_hand14.urdf` |
| 可复用 | 关节命名、TCP/腕部定义、Pinocchio+CasADi IK 流程 |
| 不复用 | 完整遥操作启动；CasADi 在 Foxy ARM64 上未验证 |
| 决策 | **算法路线对齐官方 IK**；离线用简化 IK，现场优先评估移植 `G1_29_ArmIK` |

### 4. unitree_ros / 5. unitree_ros2

| URDF、`g1_description`、ROS2 arm SDK 示例 | 用于核对 frame 名与 DoF；**机型以真机为准** |
| 决策 | 标定与 TF 边命名跟 URDF 对齐，不照搬单一 rev |

### 6. teleimager（Teleoperate 配套）

| 相机服务候选 | RGB/Depth 与时间戳；**UNVERIFIED 是否已在 PC2 运行** |

## B. TF / 几何 / 视觉 / 轨迹

| # | 项目 | 许可证 | 关键借鉴 | 不复用原因 |
|---|---|---|---|---|
| 7 | Pinocchio | BSD-2 | FK、Jacobian、URDF | 机载二进制依赖待验证 |
| 8 | robot_state_publisher | Apache-2.0 | joint_states→/tf | 现场尚无权威 JointState |
| 9 | ros2 geometry2 / tf2 | Apache-2.0 | 时间戳、逆变换 | 与 Foxy API 对齐 |
| 10 | apriltag | BSD-2 | PnP 辅助 | 赛场是否允许贴标未知 |
| 11 | OpenCV | Apache-2.0 | PnP、畸变、轮廓 | 本仓库 DLT PnP 为无依赖备选 |
| 12 | ros2_handeye_calibration | Apache-2.0 | 手眼流程 | 需实测标定数据 |
| 13 | librealsense | Apache-2.0 | RGB-D align | 相机型号未确认 |
| 14 | ruckig | MIT | 限速轨迹 | 依赖未装机载 |
| 15 | py_trees | BSD-3 | BT 模式 | 新版不支持 Py3.8 → **自研轻量状态机** |

## C. 行为树

- **选用**：`gdps_qi.mission.mission_controller` + 技能阶段枚举（等价 OBSERVE…COMMIT），不引入 py_trees 依赖。
- BehaviorTree.CPP：Foxy 下 Python 绑定成本高，**不采用**。

## 仓库内实现映射

| 能力 | 模块 |
|---|---|
| SE(3) | `gdps_qi.math_se3` |
| TF | `gdps_qi.transforms.transform_manager` |
| 标定 YAML | `gdps_qi.transforms.calibration_manager` |
| 视觉位姿 | `gdps_qi.perception.pose_estimator` |
| IK（离线） | `gdps_qi.kinematics.arm_kinematics` |
| P1–P6 | `gdps_qi.skills.*` + `mission_controller` |
