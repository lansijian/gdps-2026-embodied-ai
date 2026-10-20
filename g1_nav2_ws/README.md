# G1 MID360：ROS 2 Foxy 最小导航工作空间

参照 Unitree 官方 ROS2/SDK、Livox 官方驱动、pointcloud_to_laserscan、slam_toolbox 和 Nav2 Foxy。自研业务仅速度桥，以及规格明确要求的 `launch/odom_bridge.py` 例外。参考版本见 `references.json`；第三方代码沿用 Apache-2.0，Livox 原版权随上游源码保留。

## 环境与边界

目标为 Ubuntu 20.04 ARM64 / ROS 2 Foxy / CycloneDDS **0.10.2** / G1 29-DoF。CI 在更新的 GitHub runner 上使用 **Focal/Foxy 容器**，同时运行 amd64 和 ARM64；Ubuntu 20.04 托管 runner 已停用。CI 用合成传感器输入，不证明真机网络、时间同步、安装标定、运动响应或现场避障效果。

默认 `dry_run:=true`，速度桥不导入 SDK、不切换模式、不调用运动接口。所有部署/构建命令均不启动运动。只有明确设置 `dry_run:=false` 才初始化 LocoClient、调用 501 和 BalanceMode(1)。本目录不依赖旧感知栈。

## 安装（机器人本地）

将本目录复制为 `~/g1_nav2_ws`。使用新终端，先关闭旧导航 launch（在原终端 Ctrl+C），避免重复 TF/同名话题发布者；不要同时运行旧驱动和新 Livox 驱动占用 UDP 端口。

```bash
cd ~/g1_nav2_ws
bash src/g1_nav_bringup/scripts/install_deps.sh
source .deps/environment.bash
colcon build --symlink-install
source install/setup.bash
```

安装脚本第一步从 `~/g1_mid360_foxy_ws_stage3_20261020/` 复制真实 `MID360_config.json` 并比较内容/打印 SHA256；如果存在多个文件，脚本打印候选路径，请指定实际正在使用的那一个：

```bash
MID360_CONFIG_SOURCE=/绝对路径/实际工作的/MID360_config.json \
  bash src/g1_nav_bringup/scripts/install_deps.sh
```

源码中的 `{}` 仅为无硬件安装占位，**没有编造任何 IP/端口**。提供的 session tar 仅包含 site YAML/补丁，不含网络 JSON。脚本保留现场文件原字节，包括 192.168.123.x 和 56101–56501 设置。`--ci` 仅用于没有机器人的 CI，跳过此复制步骤；机器人部署不要使用此参数。

依赖脚本通过 apt 安装 Nav2、SLAM 和点云转换器；Livox SDK2、Livox ROS2 驱动、CycloneDDS 0.10.2 和 Foxy RMW 从固定 commit 编译到本目录 `.deps`，不覆盖系统 ROS。没有不存在的 Livox apt 包，也不调用上游会清理整个工作空间的 build.sh。

## 两个终端

终端 1：先建图，默认只感知，不启动速度桥。

```bash
cd ~/g1_nav2_ws
source .deps/environment.bash
source install/setup.bash
ros2 launch g1_nav_bringup mapping.launch.py odom_topic:=/dog_odom
```

终端 2：RViz，Fixed Frame 已设为 `map`。

```bash
cd ~/g1_nav2_ws
source .deps/environment.bash
source install/setup.bash
rviz2 -d src/g1_nav_bringup/config/navigation.rviz
```

确认地图正常后，在终端 1 Ctrl+C，然后启动“继续建图 + Nav2 + 速度桥 dry-run”，终端 2 保持 RViz。通过 Nav2 Goal 发送目标，Nav2 规划/避障、输出 `/cmd_vel`，速度桥接收但不调用 SDK。

```bash
ros2 launch g1_nav_bringup nav_bringup.launch.py slam:=true dry_run:=true odom_topic:=/dog_odom
```

保存地图（可在终端 2 退出 RViz 后运行，再启动 RViz）：

```bash
ros2 run nav2_map_server map_saver_cli -f "$HOME/g1_nav2_ws/maps/site"
```

已有地图时，终端 1 用下列命令替换上一条 launch，RViz 使用 2D Pose Estimate 设置初始位置。此模式只用 AMCL 发布 `map -> odom`，不会同时启动 SLAM。

```bash
ros2 launch g1_nav_bringup nav_bringup.launch.py \
  slam:=false map:="$HOME/g1_nav2_ws/maps/site.yaml" dry_run:=true
```

允许真机运动时才将上述导航命令改为 `dry_run:=false interface:=eth0`。此操作会切入运动模式，必须由现场人员在急停可用、周边清空且确认外参/里程计正确后执行。默认命令从不启用运动。退出时先零速，再 BalanceMode(0)，最后恢复进入前读取的 FSM，避免猜测固件的“锁定站立”编号；恢复原 FSM 不等于已确认特定站立姿态。

## 数据与 TF

```text
livox_ros_driver2 /livox/lidar (PointCloud2, livox_frame, configured 10 Hz)
    -> pointcloud_to_laserscan /scan (LaserScan, base_link, scan_time 0.1)
    -> slam_toolbox /map -> Nav2
/dog_odom (nav_msgs/Odometry) -> odom_bridge -> /odom and odom -> base_link
map -> odom             : SLAM，或 saved-map 模式下 AMCL
odom -> base_link       : odom_bridge 唯一发布者
base_link -> livox_frame: tf2_ros static_transform_publisher 唯一发布者
```

`/livox/imu` 是驱动备用输出，本期不参与计算；目标 200 Hz 由雷达配置/固件决定，未通过硬件测量。里程计按输入频率转发，输入 50 Hz 才输出 50 Hz，绝不补造测量值。输入 Odometry 的原始时间戳原样保留；本栈没有时钟替换/偏移校准节点。驱动时戳必须与主机/里程计同一时基，现场用 topic echo 确认；若仍落后，应在驱动/传感器同步设置层解决。

原生 `/dog_odom` 必须是 `nav_msgs/Odometry`、位姿相对 odom，twist 在机体坐标系；旧提供者要关闭其自身 odom TF 发布功能。`odom_topic` 是**输入**，不能设为输出 `/odom`，避免回环。`base_frame`、`scan_topic`、`odom_topic`、`params_file` 可通过 launch 覆盖，默认只使用上述四个 frame。

`use_native_odom:=false` 使用随用户 ZIP 交付的 `g1_ros2_bridge/odom_bridge.py` 同样接口：SDK `rt/sportmodestate` 的测量 position/velocity/IMU。采用平面 yaw，世界速度转机体速度。**G1 当前固件是否发布该 DDS 类型/话题仍需现场确认**。`rt/lowstate` 在官方消息定义中只有 IMU/电机等，没有 x/y 或机体速度；g1pilot 遥测同样不能凭空提供它们，因此没有实现从该消息伪造里程计的积分器。没有原生 odom 时应使用实测可用的官方服务或成熟里程计上游。

## 倒装外参与地图风险

默认严格保留 session tar 的粗标 `xyz=(0,0,0.4), xyzw=(0,1,0,0)`，它是 **绕 Y 轴 180°**。规格中的 **roll=180° 是绕 X 轴**，两者不同；X 轴半转对应 `(1,0,0,0)`。z=0.4 与“头部约 1.4m”的说法也尚未统一，不把任何一个当成精标。外参支持 launch 参数 `lidar_x/y/z/qx/qy/qz/qw`，现场测量后覆盖，例如只在确定为 X 轴半转时设置 `lidar_qx:=1 lidar_qy:=0 lidar_qz:=0 lidar_qw:=0`。

点云高度范围 `[-0.05,0.35]` 定义于 **转换后的 base_link 坐标系**。若 base_link 在骨盆、而不是地面，这不是腿部地面高度层，需结合真实机体原点精调；本栈没有额外地面 frame。网络 JSON 内的点云 extrinsic 若非零，应先查清驱动是否已将点变换，以免再施加同一外参；脚本不会擅自改动真实 JSON。

参考 [deepglint 倒装实现](https://github.com/deepglint/FAST_LIO_LOCALIZATION_HUMANOID)；本期不消费 IMU，仅通过 TF 处理点云。未来启用 LIO 时须同步处理 IMU 坐标与重力，不能以当前纯 2D 链验收 LIO。

## Nav2 配置与内存

`params_file` 为公开 launch 参数，默认加载本包 `config/nav2_params.yaml`，不再加载旧配置。以 Foxy 官方模板为基础，改帧名/真实时钟、速度 0.4/0.5、半径 0.35，以及必要的同义速度上限；`map` 参数交给官方 localization launch。局部 costmap 3×3 m / 0.05 m = 60×60 cells；全局分辨率 0.05m，尺寸由真实 SLAM/map_server 地图决定，模板不固定全局 width/height。地图不能因此声称无界内存保证，现场异常地图尺寸仍须查源头。采用官方 DWB/obstacle/voxel/inflation 动态避障，无自写避障算法。

## 现场检查（人工命令，不影响数据管道）

```bash
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic hz /scan
ros2 topic hz /dog_odom
ros2 topic hz /odom
ros2 topic info /livox/lidar --verbose
ros2 topic echo /livox/lidar --field header
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_ros tf2_echo base_link livox_frame
ros2 run tf2_ros tf2_echo map odom
ros2 action list -t
ros2 topic echo /cmd_vel
```

Foxy 点云转换器按 SensorData QoS 订阅；本栈原生 odom 订阅同样用 BEST_EFFORT，兼容可靠/尽力发布者。没有输入时，odom 订阅正常等待，SLAM/Nav2 由上游日志报告缺 TF/数据；没有自研超时退出或诊断话题。官方点云转换器按 scan 订阅者按需订阅输入；RViz/SLAM 启动后会激活。

G1 EDU+ 固件 1.5.3 存在 [SDK issue #170](https://github.com/unitreerobotics/unitree_sdk2_python/issues/170)：高层命令返回成功但运动未执行。现场确认固件并先执行官方 SDK 自测，**该示例会切换状态/可能运动，不是安装步骤**：

```bash
cd /home/unitree/unitree_sdk2_python
python3 example/g1/high_level/g1_loco_client_example.py eth0
```

脚本源码、操作提示和急停由现场人员先检查，再按示例交互执行；当前环境没有执行。SDK RPC 同步调用，`SetTimeout(10.0)` 按规格保留：正常返回时定时器目标 50 Hz；通信阻塞时不能保证 50 Hz 或 0.5s 回调准点，发送的 SDK velocity duration 固定 0.1s 限制命令有效期，**固件是否执行到期自停必须现场测量**。退出恢复也不是对断电/强杀的保证。

## 开发验证

GitHub 根目录包含此目录 workflow 的镜像，因为 Actions 不发现嵌套 `.github/workflows`。本目录是唯一交付工作空间；CI 副本不改变原工作区。CI 构建实际开源依赖，运行速度桥接口/顺序/超时测试、默认无设备 mapping launch，以及合成点云→scan→地图→Nav2 目标/速度输出、动态障碍写入/清除检查（SLAM 与保存地图 AMCL 两种模式），日志作为 artifact 上传。不会把驱动缺硬件错误或 timeout 的任意失败都当成功。

每个 launch 的职责：`sensing.launch.py` 雷达/静态 TF/scan；`mapping.launch.py` 再加里程计和 SLAM；`nav_bringup.launch.py` 完整导航（SLAM 或保存地图二选一）；`cmd_vel_bridge/bridge.launch.py` 单独速度桥。默认 launch 不需要额外手起 TF 或 QoS 转换。

完整导航默认读取 `g1_nav_bringup/config/bridge.yaml`；独立速度桥默认读取 `cmd_vel_bridge/config/bridge.yaml`。两者都可通过 `bridge_params_file` 覆盖。
