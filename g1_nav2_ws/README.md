# G1 MID360：ROS 2 Foxy 最小导航工作空间

参照 Unitree 官方 ROS2/SDK、Livox 官方驱动、pointcloud_to_laserscan、slam_toolbox 和 Nav2 Foxy。自研业务仅 `cmd_vel_bridge` 速度桥与 `g1_nav_bringup` 里程计桥。参考版本见 `references.json`；第三方代码沿用 Apache-2.0，Livox 原版权随上游源码保留。

## 平台事实（不得改口）

- 机器人是 **Unitree G1 EDU 人形机器人，29 个自由度**，不是机器狗。
- 机载电脑为 **16GB Jetson Orin 类**，Ubuntu 20.04，ROS 2 **Foxy**。
- LiDAR 是 **Livox Mid360，头部倒装**。当前只保留粗标 TF：`base_link -> livox_frame` = `xyz 0 0 0.4`、`quat xyzw 0 1 0 0`，即**绕 Y 轴 180°**；这不是精标。若正墙测试发现正前方的墙出现在 `/scan` 的 angle π，切换为绕 X 轴 180°（`quat xyzw 1 0 0 0`）再测。
- Mid360 网络真值以现场 `MID360_config.json` 为准：雷达 `192.168.123.120`，主机网口 `192.168.123.x`；端口映射 56100→56101、56200→56201、56300→56301、56400→56401、56500→56501。源码树里的 `src/g1_nav_bringup/config/mid360_config.json` 只允许是 `{}` 占位；部署脚本复制真值并做 sha256/cmp 校验。
- 运动控制只用高层 `unitree_sdk2_python` 的 `LocoClient`。已验证序列：`ChannelFactoryInitialize(0, "eth0")` → `LocoClient.SetTimeout(10.0)` → `Init()` → `SetFsmId(501)` → `SetBalanceMode(1)` → `SetVelocity(vx, vy, omega, duration)`。退出先零速，再 `SetBalanceMode(0)`，最后恢复进入前 `GetFsmId()` 读到的 initial_fsm。**禁止**把 `rt/arm_sdk` 低层手臂控制、LowCmd/LowState 代码放进本工作区。
- 只有两个 ROS 包：`g1_nav_bringup`、`cmd_vel_bridge`。坐标系只有 `map` / `odom` / `base_link` / `livox_frame`。
- 默认 `dry_run:=true`：不 import `unitree_sdk2py`、不 `ChannelFactoryInitialize`、不调 `SetFsmId/SetBalanceMode/SetVelocity`。
- 本里程碑 Nav2 只前进+转向：DWB `max_vel_y:=0.0`、`acc_lim_y:=0.0`；`cmd_vel_bridge` 保留 vy clamp 接口，但 Nav2 默认不命令横向。
- global_costmap 只有 `static_layer` + `inflation_layer`，不订阅 `/scan`；动态障碍只进 local_costmap（`voxel_layer` + `inflation_layer`，`observation_sources: scan`，`data_type: LaserScan`，marking/clearing 均开）。
- 不实现 LIO，不消费 `/livox/imu`，不从 `rt/lowstate` 伪造/积分里程计。`/dog_odom` 与 `rt/sportmodestate` 都不可用时，栈只报错并提示下一步（接官方可用的里程计上游），不写新里程计算法。
- 所有脚本一律用 `bash src/g1_nav_bringup/scripts/xxx.sh` 调用（Windows zip 可能丢 exec bit，不依赖 `./xxx.sh`）。

## 1. Windows 复制到机器人

Windows PowerShell（在 `E:\GDPS\competition` 执行）：

```powershell
scp -r .\g1_nav2_ws unitree@<机器人IP>:/home/unitree/
# 机器人上若还没有 /home/unitree/unitree_sdk2_python，一并把官方 SDK zip 拷过去：
scp .\unitree_sdk2_python.zip unitree@<机器人IP>:/home/unitree/
```

`unitree_sdk2_python.zip` 在 Windows 侧用固定 commit（`814556d15970dd2ecf1c9984e845ca02ab07e206`，见 `references.json`）的官方仓库内容制作；**机器人部署不依赖 git clone**。机器人上工作区固定为 `~/g1_nav2_ws`。先关闭旧导航 launch（原终端 Ctrl+C），避免重复 TF/同名话题；不要同时运行旧驱动和新 Livox 驱动占用 UDP 端口。

## 2. 机器人从零安装到 dry-run 建图（严格按此顺序，一步失败先修再走）

```bash
ssh unitree@<机器人IP>
conda deactivate            # 2.0 有 conda 必先退出；之后 source environment.bash 时若仍打印 conda 警告，重开终端从本步重来
cd ~/g1_nav2_ws
bash src/g1_nav_bringup/scripts/install_deps.sh
#   或离线复装（.deps 已构建过，跳过 apt/rosdep/git，只校验关键产物）：
#   G1_DEPS_OFFLINE=1 bash src/g1_nav_bringup/scripts/install_deps.sh
#   多个 MID360_config.json 候选时：MID360_CONFIG_SOURCE=/绝对路径/MID360_config.json bash src/g1_nav_bringup/scripts/install_deps.sh
source .deps/environment.bash
python3 -m pip install --user --no-binary cyclonedds "cyclonedds==0.10.2"
# 确认/安装 unitree_sdk2_python 到 /home/unitree/unitree_sdk2_python（优先用现场已验证目录；否则解压 scp 过来的 zip）：
cd /home/unitree && unzip -o unitree_sdk2_python.zip
# 若解压得到 unitree_sdk2_python-master 或 unitree_sdk2_python-<commit>，必须改名：
mv unitree_sdk2_python-master unitree_sdk2_python 2>/dev/null || mv unitree_sdk2_python-* unitree_sdk2_python
test -f unitree_sdk2_python/unitree_sdk2py/core/channel.py   # 必须存在，否则停下来修路径，不要继续
cd ~/g1_nav2_ws
python3 -c "import cyclonedds; from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient; print('sdk imports OK')"
colcon build --symlink-install
source install/setup.bash
ros2 launch g1_nav_bringup mapping.launch.py
```

要点：`install_deps.sh` 先复制 MID360 真值配置（sha256/cmp 校验），再 apt + 从固定 commit 编译 CycloneDDS 0.10.2 / rmw_cyclonedds / Livox-SDK2 / livox_ros_driver2 到 `.deps/`（不覆盖系统 ROS）；脚本**不会**自动 pip 安装 SDK 相关 python 包，只做 import 检查并打印本节的精确修复命令。pip 安装 cyclonedds 必须在 `source .deps/environment.bash` 之后，使 python 绑定与同一个 C 库对齐。

## 3. 单 CycloneDDS 环境检查（每个新终端 / 排障时）

```bash
cd ~/g1_nav2_ws
source .deps/environment.bash     # CONDA_PREFIX 非空会打印警告：先 conda deactivate
echo "$RMW_IMPLEMENTATION"        # 必须输出 rmw_cyclonedds_cpp
echo "$CYCLONEDDS_HOME"           # 必须指向 ~/g1_nav2_ws/.deps/dds/install/cyclonedds
ldd .deps/dds/install/rmw_cyclonedds_cpp/lib/librmw_cyclonedds_cpp.so | grep libddsc   # 必须解析到 .deps 内
python3 -c "import cyclonedds; from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient; print('sdk imports OK')"
```

ROS RMW 与 unitree_sdk2py 共用同一个进程内 CycloneDDS 实例（同一个 `CYCLONEDDS_HOME`，其 `lib` 已前置到 `LD_LIBRARY_PATH`）；不要再 source 其他 DDS 环境。

## 4. 话题/TF 检查与正墙测试（必做，决定外参）

建图 launch 保持运行，另开终端：

```bash
cd ~/g1_nav2_ws && source .deps/environment.bash && source install/setup.bash
bash src/g1_nav_bringup/scripts/check_stack.sh
```

正墙测试判据：G1 正对约 1 m 的平墙站定，脚本末段打印 `/scan` 的 angle 0 与 angle π 读数。**angle 0 应 ≈1 m（正前方的墙）**。若 angle π ≈1 m 而 angle 0 是远处，说明前后反向：停止导航调参，Ctrl+C 停 launch，改用绕 X 轴 180° 复测：

```bash
ros2 launch g1_nav_bringup mapping.launch.py lidar_qx:=1 lidar_qy:=0 lidar_qz:=0 lidar_qw:=0
```

两种姿态都只用这四个 launch 参数切换，不改文件；现场确认后再把胜出的值写回三个 launch 的 `lidar_q*` 默认值。`lidar_z=0.4` 同样是粗标，现场测量后用 `lidar_x/y/z` 覆盖。

- 里程计默认转发 `/dog_odom`（`use_native_odom:=true`，BEST_EFFORT 订阅）。`use_native_odom:=false` 改用 SDK `rt/sportmodestate` 测量值（平面 yaw、世界速度转机体），**G1 当前固件是否发布该话题仍需现场确认**。
- `/scan` 高度窗默认 `scan_min_height:=-0.05 scan_max_height:=0.35`（转换后的 base_link 系）。首轮现场可临时 `scan_min_height:=-0.8 scan_max_height:=0.8` 验证墙层，再按 base_link 下的真实 z 分布收回。
- RViz：`rviz2 -d src/g1_nav_bringup/config/navigation.rviz`（Fixed Frame 已设为 `map`）。

## 5. 闭环建图与保存

建图 launch 保持运行，低速走一个闭环回到起点，确认 `/map` 闭环无撕裂后：

```bash
bash src/g1_nav_bringup/scripts/save_map.sh
# 产出：~/g1_nav2_ws/maps/site.pgm + site.yaml（nav2_map_server）
#       /home/unitree/maps/site_posegraph.posegraph（slam_toolbox 序列化图）
```

序列化服务类型是 `slam_toolbox/srv/SerializePoseGraph`（任何旧写法 `slam_toolbox/srv/SerializeMap` 一律作废），服务名 `/slam_toolbox/serialize_map`；最终以机上 `ros2 service type /slam_toolbox/serialize_map` 实测为准。

调参闸（顺序不可颠倒）：只有 check_stack 正墙、TF、`/odom` 全干净后，若建图仍稀疏/分段，才允许把 slam_toolbox 的 `minimum_time_interval` / `minimum_travel_distance` / `minimum_travel_heading` 从 0.5 调到 0.2，`map_update_interval` 从 5.0 调到 2.0；**禁止**先动 `use_scan_matching` / correlative / loop closing 参数。

## 6. dry-run 完整导航（继续建图模式）

```bash
ros2 launch g1_nav_bringup nav_bringup.launch.py slam:=true dry_run:=true
```

RViz 用 Nav2 Goal 发单点目标；确认 `/cmd_vel` 有输出、local_costmap 对动态障碍正确 mark/clear、global_costmap 无 obstacle_layer。速度桥只打印日志，不调用 SDK。

## 7. dry-run 完整导航（保存地图模式）

```bash
ros2 launch g1_nav_bringup nav_bringup.launch.py slam:=false map:=$HOME/g1_nav2_ws/maps/site.yaml dry_run:=true
```

RViz 用 2D Pose Estimate 给初始位姿（AMCL 唯一发布 `map -> odom`，不会与 SLAM 并存），再发 Nav2 Goal 验证规划与 `/cmd_vel`。

## 8. 真机运动（仅当 4–7 全绿）

> ⚠️ **安全警告**：以下命令会切入运动模式并驱动物理机器人。执行前必须同时满足：现场人员到位、急停可用、周边清空；正墙测试（第 4 节）通过；`check_stack.sh` 全绿；固件不含已知问题（G1 EDU+ 固件 1.5.3 有 [SDK issue #170](https://github.com/unitreerobotics/unitree_sdk2_python/issues/170)：高层命令返回成功但不运动——先用官方 `g1_loco_client_example.py` 自测，该示例本身会动作，需同等安全条件）。首次只发近距离单点目标，低速起步。

```bash
ros2 launch g1_nav_bringup nav_bringup.launch.py slam:=false map:=$HOME/g1_nav2_ws/maps/site.yaml dry_run:=false interface:=eth0
```

只有 `dry_run:=false` 才初始化 LocoClient、执行 501 / BalanceMode(1)。SDK RPC 为同步调用，`SetTimeout(10.0)` 保留；通信阻塞时 50 Hz 定时与 0.5 s 超时不再准点，下发的 velocity duration 固定 0.1 s 限制命令有效期，**固件是否到期自停必须现场测量**。退出顺序由栈保证：先零速 → `SetBalanceMode(0)` → 恢复进入前 `GetFsmId()` 读到的 initial_fsm；这不是对断电/强杀的保证。

## 9. 航点导航（单点稳定之后）

单点 NavigateToPose 连续多次稳定到达后，才允许用 Nav2 waypoint follower（`FollowWaypoints`）：

- RViz 面板切 waypoint 模式逐点下发；或命令行：

```bash
ros2 action send_goal /follow_waypoints nav2_msgs/action/FollowWaypoints \
  "{poses: [{header: {frame_id: map}, pose: {position: {x: 1.0}, orientation: {w: 1.0}}}]}"
```

## 10. CI 绿 ≠ 真机验证

CI（`ros:foxy` 容器，amd64 + ARM64 矩阵）只证明：编译通过；禁用词与 `robot_center` 零命中；配置与 launch 传参链静态正确；速度桥时序/异常处理正确；合成点云下 SLAM 与保存地图 AMCL 两种模式的 scan→map→Nav2 goal→`/cmd_vel` 与 local costmap 动态障碍 mark/clear 正确。CI **不**证明真机网络与时间同步、MID360 安装外参（必须现场正墙测试）、固件运动响应、现场避障效果。真机首动必须走第 8 节流程。

## 附录：数据与 TF

```text
livox_ros_driver2 /livox/lidar (PointCloud2, livox_frame, configured 10 Hz)
    -> pointcloud_to_laserscan /scan (LaserScan, base_link, scan_time 0.1)
    -> slam_toolbox /map -> Nav2
/dog_odom (nav_msgs/Odometry) -> odom_bridge -> /odom and odom -> base_link
map -> odom             : SLAM，或 saved-map 模式下 AMCL
odom -> base_link       : odom_bridge 唯一发布者
base_link -> livox_frame: tf2_ros static_transform_publisher 唯一发布者
```

`/livox/imu` 是驱动备用输出，本期不参与计算。里程计按输入频率转发，绝不补造测量值；输入 Odometry 的原始时间戳原样保留。`odom_topic` 是**输入**，不能设为输出 `/odom`。launch 职责：`sensing.launch.py` 雷达/静态 TF/scan；`mapping.launch.py` 加里程计和 SLAM；`nav_bringup.launch.py` 完整导航（SLAM 或保存地图二选一）；`cmd_vel_bridge/bridge.launch.py` 单独速度桥。局部 costmap 3×3 m / 0.05 m；全局分辨率 0.05 m，尺寸由真实地图决定。

## 附录：开发验证

GitHub 根目录包含此目录 workflow 的镜像，因为 Actions 不发现嵌套 `.github/workflows`。本目录是唯一交付工作空间。CI 构建实际开源依赖，运行禁用词检查、`compileall`、`tests/test_config.py`（配置与传参链，纯文本/YAML 断言）、`tests/test_bridge.py`（速度桥）、默认无设备 mapping launch，以及合成管线测试（`tests/launch_check.py`，SLAM 与 AMCL 两种模式），日志作为 artifact 上传。无硬件的 Livox Init 失败不算失败，任何 timeout 也不算成功。Windows 本机无 ROS：本地只做 `compileall`/禁用词 grep/`test_config.py`，ROS 级验证一律以 GitHub CI 为准。

```bash
! grep -rnE 'RESTART_REQUIRED|BLOCKED_|latch|smoke|verified|ReceiptClock|robot_center' src/
! grep -rnwE 'health|gate|watchdog|state_machine' src/
python3 -m compileall -q src tests
python3 tests/test_config.py
python3 tests/test_bridge.py   # 需要 ROS 环境（CI 容器或机器人），Windows 本机不可跑
```
