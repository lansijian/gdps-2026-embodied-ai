# G1 EDU 质检硬件接口矩阵（2026-10-17）

状态枚举：`VERIFIED` | `DOCUMENTED_UNVERIFIED` | `UNKNOWN` | `UNSUPPORTED`

| item | claimed_model | evidence | host | source | access | verified_on_real_G1 | blockers |
|---|---|---|---|---|---|---|---|
| 机体 DoF / URDF | G1 EDU 23/29 | DOCUMENTED_UNVERIFIED | PC2 | xr_teleoperate URDF | read | NO | 未读 joint 总数 |
| 关节状态 ROS | JointState | UNKNOWN | PC2 | `/joint_states`? | read | NO | topic 未列全 |
| 行走里程计 | `/dog_odom` | VERIFIED | PC2 | nav_msgs/Odometry | read | YES | 非 TF |
| 激光 MID-360 | Livox | VERIFIED | PC2 | `/utlidar/cloud_livox_mid360` | read | YES | 非抓取精度 |
| 全局 TF | `/tf` | UNSUPPORTED | PC2 | — | read | NO | 7s 窗口无数据 |
| 头部 RGB | D435i? | UNKNOWN | PC2/头显 | teleimager / USB | read | NO | 无 ROS 图像证据 |
| 深度 | RealSense? | UNKNOWN | PC2 | — | read | NO | align 未测 |
| 左/右 Dex3-1 | Dex3-1 | DOCUMENTED_UNVERIFIED | PC2 | SDK2 `HandState` | read/write | NO | 未订阅 DDS |
| 双臂 SDK | arm7 high level | DOCUMENTED_UNVERIFIED | PC2 | unitree_sdk2 | write | NO | 禁止今日发令 |
| 音频 | G1 Audio | DOCUMENTED_UNVERIFIED | PC2 | sdk2 audio example | write | NO | 仅展示 |
| 电子秤 | 赛场设备 | UNKNOWN | 工位 | 视觉/API? | read | NO | 无协议 |
| 离心机 | 六孔台式 | UNKNOWN | 工位 | 按钮/视觉 | read/write | NO | 无反馈 API |
| 报告上传 | 赛方 API | UNKNOWN | 外网 | HTTP | write | NO | 仅本地 pending JSON |

探测命令（只读）：`scripts/g1/qi_hardware_probe_readonly.py --ros2`（机载执行）。
