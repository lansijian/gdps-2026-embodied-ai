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

### 3.1 激光雷达与感知（DISCOVERED）

| Topic | 类型 | 备注 |
|---|---|---|
| `/utlidar/cloud_livox_mid360` | `sensor_msgs/msg/PointCloud2` | MID-360 点云，**需验证频率/frame_id/有效点数** |
| `/utlidar/imu_livox_mid360` | `sensor_msgs/msg/Imu` | MID-360 IMU |
| `/utlidar/range_info` | `geometry_msgs/msg/PointStamped` | 距离信息 |
| `/collision_clouds` `/pre_collision_clouds` | `PointCloud2` | 厂商碰撞点云分类 |
| `/safe_clouds` `/pre_safe_clouds` `/warning_clouds` `/no_warning_clouds` | `PointCloud2` | 厂商安全/警告分级点云 |
| `/grid_clouds` `/ele_clouds` | `PointCloud2` | 栅格/高程点云 |

**关键差异**：真机**没有** `/scan_raw` 或 `/scan`（LaserScan）。现有 `scan_restamper_node` 订阅 `/scan_raw` 将收不到数据。需要 PointCloud2 → LaserScan 转换。

### 3.2 里程计与 SLAM（DISCOVERED）

| Topic | 类型 | 备注 |
|---|---|---|
| `/dog_odom` | `nav_msgs/msg/Odometry` | 厂商里程计，**需比较后选型** |
| `/state_estimator/fusion_odom` | `Odometry` | 融合里程计 |
| `/unitree_slam/high_rate_odometry` | `Odometry` | SLAM 高速里程计 |
| `/unitree/slam_mapping/odom` | `Odometry` | 建图里程计 |
| `/unitree/slam_relocation/odom` | `Odometry` | 重定位里程计 |
| `/unitree/slam_mapping/points` | `PointCloud2` | 建图点云 |
| `/unitree/slam_relocation/points` | `PointCloud2` | 重定位点云 |
| `/unitree/slam_relocation/global_map` | `PointCloud2` | 全局地图点云 |
| `/global_map` | `nav_msgs/msg/OccupancyGrid` | 栅格地图 |
| `/unitree_slam/waypoints` | `std_msgs/msg/String` | 航点 |
| `/slam_info` `/slam_key_info` | `String` | SLAM 状态 |

**待验证**：比较各 odom 的频率、坐标系、时间戳、姿态连续性，选出导航输入。`/global_map` 若有效可复用，减少重复建图。

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

## 5. 下一步验证项（UNVERIFIED）

1. MID-360 是否持续发布实时数据（频率、frame_id、点数量）。
2. `/dog_odom` 是否正常，与其他 odom 比较选型。
3. SLAM 与 `/global_map` 是否有有效发布者。
4. TF 是否实际存在（`/tf` `/tf_static`）。
5. `/api/sport/request` 的 publisher、QoS、API ID。
6. `unitree_sdk2py` 是否可导入，`LocoClient` 接口签名。

执行脚本：`bash scripts/g1/sensor_diag.sh`（机载只读，不发运动）。

---

## 6. 严禁事项

- 发布真实运动命令 / 调用 live LocoClient / 切换 FSM
- 使用 Damp / ZeroTorque 作为普通停车
- 覆盖厂商节点 / 删除已有地图 / 重启机器人
- 修改系统内核或 ROS 安装 / 系统级升级
- 自动启动 Nav2 实机运动
