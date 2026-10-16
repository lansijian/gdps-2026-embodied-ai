# G1 EDU 真机现场基线（2026-10-16）

本文记录 2026-10-16 现场 SSH 实际取得的 G1 EDU 机载系统信息，作为后续开发的硬件基线。
所有未经验证的历史假设（Ubuntu 22.04 / Humble / `/scan` 等）以本文为准覆盖。

状态标识：

- **CONFIRMED**：现场实际输出已确认
- **DISCOVERED**：Topic 名已发现，但数据频率/有效性尚未验证
- **UNVERIFIED**：需要进一步测试
- **BLOCKED**：当前条件无法继续

---

## 1. 网络环境

### Windows 开发机（CONFIRMED）

| 项 | 值 |
|---|---|
| 系统 | Windows |
| 工具 | Trae |
| 网卡 | Realtek PCIe GbE Family Controller |
| 接口名 | 以太网 |
| IPv4 | `192.168.123.99/24` |
| 链路速率 | 1 Gbps |
| Ping G1 | 4/4 成功，0% 丢包 |
| SSH TCP 22 | 连接成功 |

### G1 EDU 机载计算机（CONFIRMED）

| 项 | 值 |
|---|---|
| SSH | `unitree@192.168.123.164` |
| 端口 | 22 |
| hostname | `ubuntu` |
| 网卡 | `eth0` |
| 网卡地址 | `192.168.123.164/24` |

> SSH 密码仅在用户终端手动输入，不得写入仓库、脚本或日志。

---

## 2. 机载系统（CONFIRMED）

| 项 | 值 |
|---|---|
| OS | Ubuntu 20.04.6 LTS |
| Kernel | 5.10.104-tegra |
| Architecture | aarch64 |
| Python | 3.8.10 |
| ROS 2 | **Foxy** |
| ROS 1 | Noetic |
| Active ROS_DISTRO | foxy |
| ROS binary | `/opt/ros/foxy/bin/ros2` |
| colcon | `/usr/bin/colcon` |
| RMW_IMPLEMENTATION | `rmw_cyclonedds_cpp` |

硬件资源：

| 项 | 值 |
|---|---|
| RAM | 15 GiB（可用 ~13 GiB） |
| Swap | 7.5 GiB |
| Disk | 1.9 TB（可用 ~1.8 TB） |

**重要结论：真实系统是 Ubuntu 20.04 + ROS 2 Foxy + Python 3.8，不是此前假设的 Ubuntu 22.04 + Humble。**

约束：

- 优先兼容原生 Foxy，不安装 Humble、不升级 Ubuntu、不 `apt upgrade`、不修改 NVIDIA 驱动、不重启。
- 若 Nav2 依赖与 Foxy 不兼容，先给出兼容性评估，再决定是否用外部 Ubuntu 环境。

---

## 3. ROS 2 Topic 清单

原始输出保存在 `logs/g1-topics/ros2-topic-list-20261016.txt`（gitignored）。

### 3.1 激光雷达与感知

| Topic | 类型 | 状态 | 备注 |
|---|---|---|---|
| `/utlidar/cloud_livox_mid360` | `sensor_msgs/msg/PointCloud2` | **CONFIRMED** | MID-360 点云，**约 10 Hz**，frame_id=`livox_frame`，point_step=22，~20064 点/帧 |
| `/utlidar/imu_livox_mid360` | `sensor_msgs/msg/Imu` | DISCOVERED | MID-360 IMU |
| `/utlidar/range_info` | `geometry_msgs/msg/PointStamped` | DISCOVERED | 距离信息 |
| `/collision_clouds` `/pre_collision_clouds` | `PointCloud2` | DISCOVERED | 厂商碰撞点云分类 |
| `/safe_clouds` `/pre_safe_clouds` `/warning_clouds` `/no_warning_clouds` | `PointCloud2` | DISCOVERED | 厂商安全/警告分级点云 |
| `/grid_clouds` `/ele_clouds` | `PointCloud2` | DISCOVERED | 栅格/高程点云 |
| `/scan` | `sensor_msgs/msg/LaserScan` | **CONFIRMED** | 由 `pointcloud_to_laserscan` 节点本地转换产生，**frame_id=`livox_frame`**，360 桶，有效桶 ~310 |

**MID-360 点云字段（CONFIRMED）**：

| 字段 | offset | 类型 |
|---|---|---|
| x | 0 | float32 |
| y | 4 | float32 |
| z | 8 | float32 |
| intensity | 12 | float32 |
| ring | 16 | uint16 |
| time | 18 | float32 |

**LaserScan 转换实测（CONFIRMED）**：

| 项 | 值 |
|---|---|
| 角度桶数 | 360（angle_increment ≈ 0.0175 rad） |
| 有效桶/帧 | 308、314、317（连续三帧） |
| +X 方向 ±30° 最近 | 0.924m、0.911m、0.918m |
| global_min | ~0.300m（恰好接近 robot_radius 边界，已通过 robot_radius=0.35 + `<=` 过滤修正） |
| 转换前频率 | 点云 ~10 Hz |
| 转换后频率（旧版纯 Python） | ~5.7 Hz（瓶颈：逐点 Python 循环） |
| 转换后频率（新版 numpy 向量化） | 待现场验证（预计 ~10 Hz） |

**关键差异**：真机**没有**原生 `/scan`（LaserScan）。已实现 `pointcloud_to_laserscan` 节点将 MID-360 点云转为 `/scan`。注意 `livox_frame` 与 `robot_center` 的外参尚未确认，不能假设雷达 +X = 机器人前方。

### 3.2 里程计与 SLAM

| Topic | 类型 | 状态 | 备注 |
|---|---|---|---|
| `/dog_odom` | `nav_msgs/msg/Odometry` | **CONFIRMED** | **约 1000 Hz**，frame_id=`odom`，child_frame_id=`robot_center`。**选为局部导航里程计** |
| `/state_estimator/fusion_odom` | `Odometry` | UNVERIFIED | 上轮检查 0 publisher |
| `/unitree_slam/high_rate_odometry` | `Odometry` | **BLOCKED** | **0 个 Publisher**，不可用 |
| `/unitree/slam_mapping/odom` | `Odometry` | DISCOVERED | 1 个 Publisher（RELIABLE），持续发布待验证 |
| `/unitree/slam_relocation/odom` | `Odometry` | DISCOVERED | 1 个 Publisher（RELIABLE），暂未观察到实际消息 |
| `/unitree/slam_mapping/points` | `PointCloud2` | DISCOVERED | 建图点云 |
| `/unitree/slam_relocation/points` | `PointCloud2` | DISCOVERED | 重定位点云 |
| `/unitree/slam_relocation/global_map` | `PointCloud2` | DISCOVERED | 全局地图点云 |
| `/global_map` | `nav_msgs/msg/OccupancyGrid` | DISCOVERED | 1 个 Publisher，地图实际内容待验证 |
| `/unitree_slam/waypoints` | `std_msgs/msg/String` | DISCOVERED | 航点 |
| `/slam_info` `/slam_key_info` | `String` | **CONFIRMED** | 约 5 Hz。`ctrl_info.info="not init"`，`currentPose` 全 0，`stateMachine.ctrName="not init"`。厂商 SLAM 控制模块**未初始化** |
| `/robot_data`（`/slam_info` 内） | | **CONFIRMED** | `errorCode=0`，29 电机正常，`batteryPower=64.0`，`sportMode=-1`，`gaitType=-1` |

**选型结论**：`/dog_odom`（1000 Hz，`odom`→`robot_center`）为当前最可靠的局部里程计。SLAM 两路 odom 有 publisher 但数据未确认，`high_rate_odometry` 无 publisher 不可用。厂商 SLAM 处于 `not init` 状态，无公开 SDK/文档说明初始化流程，**不建议未经授权调用 `/api/slam_operate/request`**。

### 3.2.1 TF 状态（BLOCKED → 方案确定）

- `/tf`、`/tf_static`：**未发现**，厂商未发布标准 TF。
- **方案**：通过 `odom_tf` 节点从 `/dog_odom` 真实消息派生 `odom`→`robot_center` TF。此为数据派生，非伪造。
- `map`→`odom` 变换：待厂商 SLAM 重定位验证后确定来源，**当前不发布**。

### 3.3 高层运动接口（DISCOVERED）

| Topic | 类型 | 备注 |
|---|---|---|
| `/api/sport/request` | `unitree_api/msg/Request` | **已确认存在**，但 API ID/权限/FSM 未验证 |
| `/api/sport/response` | `unitree_api/msg/Response` | |
| `/api/robot_state/request` `/response` | | 机器人状态查询 |
| `/api/motion_switcher/request` `/response` | | 运动模式切换 |
| `/api/slam_operate/request` `/response` | | SLAM 操作 |
| `/lf/sportmodestate` `/sportmodestate` | | 运动模式状态 |
| `/lf/lowstate` `/lowstate` | | 底层状态 |

**结论**：`RosSportRequestBackend` 具备验证条件，但发现 Topic ≠ 可发运动。禁止向 `/api/sport/request` 发布消息。保留 `LocoClient` 与 ROS Sport Request 两方案，比较后决定。

### 3.4 其他接口（DISCOVERED，本阶段不开发）

`/frontvideostream`、`/wirelesscontroller`、`/gridmap`、`/planner_map`、`/dog_imu_raw`、`/secondary_imu`、`/api/videohub/request`、`/api/audiohub/request`。

---

## 4. 当前代码与真机的关键差异

### 差异 A：LaserScan 输入缺失（UNVERIFIED → 需适配）

- 现有 `scan_restamper_node.py` 默认订阅 `/scan_raw`，输出 `/scan`。
- `local_navigator_node.py` 订阅 `/scan`。
- 真机只有 `/utlidar/cloud_livox_mid360`（PointCloud2），无 `/scan`。
- **方案**：实现 PointCloud2 → LaserScan 转换节点，处理坐标系、机身遮挡、高度过滤、地面点区分、有效角度、时间戳、QoS、频率、坐标变换。优先复用 ROS 2 Foxy 兼容的 `pointcloud_to_laserscan`；若不可用，实现经测试的转换节点。

### 差异 B：定位与 TF（UNVERIFIED）

- Topic 列表中**未见** `/tf` 与 `/tf_static`。
- 需检查是否有真实 TF 发布者，是否为命名空间或运行状态问题。
- 读取真实 Odometry 的 `header.frame_id` / `child_frame_id` / pose / twist / timestamp 后建立正确变换。
- 不得与厂商已有 TF 重复发布，不得虚构 `map → odom`。

### 差异 C：ROS 2 Foxy 兼容性（需检查）

现有包以 Humble 为参考。需检查：

- Python 3.8 语法（`from __future__ import annotations` 已用，f-string、`str | None` 等需注意）
- `rclpy`、`launch_ros`、`tf2_ros`、`sensor_msgs` Foxy API
- Nav2 Foxy API
- colcon、`setup.py`、`package.xml` 依赖
- 参数声明与 QoS

### 差异 D：安全配置（保持）

```yaml
mode: dry-run
backend: mock
```

`require_odom` / `require_tf` / `require_heartbeat` 默认关闭，live 前必须根据真实数据调整。

---

## 5. 构建与验收状态

### Level 1：Foxy 编译（CONFIRMED ✅）

- `colcon build --symlink-install --packages-select gdps_g1_navigation`
- 结果：`Finished <<< gdps_g1_navigation [1.91s]`，`Summary: 1 package finished [2.38s]`
- 6 个导航可执行节点已注册。
- 部署路径：`/home/unitree/gdps-2026-embodied-ai`

### Level 2：纯感知 LaserScan 转换（CONFIRMED ✅）

- 启动 `pointcloud_to_laserscan` 节点（仅订阅点云，不发运动）。
- `/scan` 持续发布，360 角度桶，有效桶 ~310。
- 前方 +X ±30° 最近距离 ~0.91m，数据真实随环境变化。
- 转换性能：纯 Python 实现 10→5.7Hz（瓶颈确认），已提交 numpy 向量化快路径，待现场复测频率。
- 时间戳：已改用原始点云 `header.stamp`，不再用节点本地时钟。
- 脚本：`bash scripts/g1/perception_dryrun.sh` + `ros2 run gdps_g1_navigation perception_probe.py`（Foxy 兼容，rclpy 订阅）。

### Level 3：STOP/CLEAR 决策 Dry-run（PARTIAL — 待现场复测）

- `ObstacleMonitor` 已新增盲区（blind_zone_m=0.40）与最小有效点数（min_forward_points=3）保护，<0.40m 返回不判定 CLEAR。
- 自遮挡过滤：`robot_radius` 上调至 0.35m，边界点用 `<=` 排除。
- 单元测试 29 项全通过。
- **待现场复测**：用固定挡板做四方向 A/B 测试，验证 STOP/CLEAR 实时切换。

### 已确认的成功命令

```bash
# 点云 → LaserScan 转换（不发运动）
cd /home/unitree/gdps-2026-embodied-ai/shared/navigation/ros2_ws
source /opt/ros/foxy/setup.bash
source install/setup.bash
ros2 run gdps_g1_navigation pointcloud_to_laserscan_node.py

# 纯感知监测（Foxy 兼容 rclpy）
python3 scripts/g1/perception_probe.py
```

### 待完成项（明天）

1. 现场复测 numpy 向量化后的 `/scan` 频率是否恢复 ~10Hz。
2. 确认 `livox_frame` 与 `robot_center` 的真实外参（不能假设雷达 +X = 机器人前方）。
3. 四方向挡板 A/B 测试，验证 STOP/CLEAR 决策切换。
4. `odom_tf` 节点派生 `odom`→`robot_center` TF 验证。
5. `/global_map` 实际地图内容检查。
6. Foxy 兼容的 slam_toolbox / Nav2 配置准备（仅配置，不启动真实运动）。
7. `/api/sport/request` 的 API ID、权限、FSM 兼容（live 前，只读审计）。

---

## 6. 严禁事项

- 发布真实运动命令 / 调用 live LocoClient / 切换 FSM
- 使用 Damp / ZeroTorque 作为普通停车
- 覆盖厂商节点 / 删除已有地图 / 重启机器人
- 修改系统内核或 ROS 安装 / 系统级升级
- 自动启动 Nav2 实机运动
