# Codex 执行任务｜Unitree G1 29-DOF + 原厂 MID-360 + ROS 2 Foxy 完整导航避障工作空间（最终整合版）

你现在是项目的主工程师。请在**当前本地代码工作区**实际完成分析、开发、测试、打包和迁移文档，而不只是讨论方案；不需要反复向我询问本次已经给出的机器配置。所有机器人运行事实以现场命令与日志为准，不能将假设当成已确认结果。不要在没有机器人连接时声称已完成实机验收。

## 0. 最终交付目标与硬边界

目标是获得一套能从 Windows 本地开发机迁移到 Unitree G1 机器人 Ubuntu 20.04（arm64）上、使用 ROS 2 Foxy 通过 `ros2 launch` 一键启动的**原厂 Livox MID-360 激光建图、定位、Nav2 路径规划、局部动态障碍检测与安全速度桥接**工作空间。核心算法优先采用成熟开源 Foxy 分支的 Nav2、SLAM Toolbox、pointcloud_to_laserscan，而非我们以前未经真机验证的自写导航算法。

**第一交付目标**：传感器 → 时间同步 → 正确 TF → 点云转换/障碍层 → SLAM/定位 → Nav2 → `/cmd_vel` dry-run、健康监控、诊断、日志、地图保存，全部可一键启动并可证明各节点真实收到数据。

**第二交付目标**：一个独立的 G1 高层速度执行模块，默认绝对不向机器人发送运动命令；仅在后续真机现场完成验证、明确授权及独立安全保护后才能切换 LIVE。此次 Codex 执行任务**不得自动发送机器人行走指令、不得自行切换 FSM、不得调用起立/趴下动作或接管腿腰底层关节**。

不修改系统安装的 `/opt/ros/foxy`，不卸载原厂 SDK 或原厂 SLAM，不改写 G1 原厂服务，不 `apt autoremove`、`dist-upgrade`、升级 JetPack/ROS、不重装雷达驱动。不覆盖已有的工作区、V1 示教、原厂文件或未经提交的修改。

## 1. 唯一真实目标机器与实机已知状态（2026-10-20）

- 机器人：Unitree G1 EDU，29-DOF；机载 Ubuntu 20.04.6 LTS、arm64、ROS 2 Foxy、Python 3.8、CycloneDDS；实际网络接口按现场查验，历史记录为 `eth0`，不可盲用。
- 雷达：G1 **原厂 Livox MID-360**，不要使用之前不稳定的 Intel RealSense D435i，也不要同时启动另一份 Livox 驱动争用设备。
- `/utlidar/cloud_livox_mid360`：`sensor_msgs/msg/PointCloud2`，实机 publisher=1；一次消息 `width × height=20064`，频率约 8–10 Hz（近似，需要重新测频率）。`frame_id=livox_frame`。
- `/utlidar/imu_livox_mid360`：`sensor_msgs/msg/Imu`，约 200 Hz（用户现场观测，需校验）。
- `/dog_odom`：`nav_msgs/msg/Odometry`，publisher=1，用户现场约 800 Hz（前记录曾更高，须重新测）。实际 `header.frame_id=odom`、`child_frame_id=robot_center`，已经读到有效姿态。还有 `/state_estimator/fusion_odom`，但上次 3 秒内未收到；不要假设可用。
- 已发现 `/unitree/slam_mapping/odom`、`/unitree/slam_mapping/points`、`/unitree/slam_relocation/odom`、`/unitree/slam_relocation/global_map`、`/api/slam_operate/request`、`/slam_info` 等话题：**有 publisher 不等于已有可用地图/定位服务**；只做协议与状态审计，未经确认绝不发送原厂 SLAM 指令。
- 原厂运动 API `/api/sport/request`；本机另有 `unitree_sdk2py.g1.loco.g1_loco_client.LocoClient`。实测有 FSM 501 相关记录，但第三方桥接 README 提到 FSM 500；务必读取实际 `GetFsmId` / SDK 源码并做现场人工确认，**禁止在程序中自动写入固定 500 或 501**。
- Nav2 已安装核心组件：`nav2_amcl`、`nav2_controller`、`nav2_dwb_controller`、`nav2_navfn_planner`、`nav2_regulated_pure_pursuit_controller`、`nav2_costmap_2d`、`nav2_map_server`、`nav2_lifecycle_manager` 等。
- `ros2 pkg prefix nav2_bringup` / `slam_toolbox` / `pointcloud_to_laserscan` 均返回 `Package not found`；`apt-cache policy ros-foxy-...` 此前空输出：APT ROS 源缺失或索引缺失尚未核实。不可直接宣称这些包不可获得。
- 在检查时 `/tf`、`/tf_static`、`/scan`、`/map` 均无话题：这只是**未启动导航栈时的现状**，不表示无法创建。
- 历史传感器时间戳 `1792468090.x` 与 `time.time()` 偏差约 **+4883 秒（约 81 分钟）**。用户后来仅执行了 `sudo apt install ntpdate -y`、查看了 `date`；**安装工具不等于成功同步时间**。必须在本次环境重新测量，不能沿用固定 4883 秒修正。
- 最重要的新实测：**MID-360 在机器人上倒装，未校准时 RViz 出现地面朝天**。可能需要旋转 180°，但绕 X/Y 轴、原始点云坐标定义、实际平移安装高度必须经真实标定或 URDF 核查，不能照抄臆测变换。

## 2. 本地文件与已有代码：先检索，不允许重复开发

- 用户 Windows 本地桥接包绝对路径：`E:\GDPS\competition\unitree_g1_ros2-main.zip`。请确认该文件真实存在，解压到当前工作区的第三方目录或 `external/`，保存 ZIP SHA256 和来源/许可；不要原样将压缩包覆盖当前项目。
- 上游公开桥接仓库：`https://github.com/SimonR99/unitree_g1_ros2`，其中 `src/g1_ros2_bridge/` 有 `robot.launch.py`、`odom_bridge.py`、`cmd_vel_bridge.py`、`description.launch.py`、G1 29-DOF URDF 等。以**本地 ZIP 内容为准**，若需要与上游比对先确认其 commit/ref。
- 特别危险的上游默认值：`robot.launch.py` 里 `dry_run` 默认 `false`，`enable_camera` 默认 `true`，`enable_cmd_vel`/`enable_loco` 默认 `true`；`cmd_vel_bridge.py` 里最大速度默认约 `0.6/0.4/0.6`，并依赖 `Move(...)`/`StopMove()`。本轮要避免其默认启动原厂 D435、默认发运动命令，以及与 G1 既有 `/dog_odom` / TF 冲突。**不要直接运行上游 robot.launch.py 的默认配置**。
- 用户现有项目优先查找 Git remote 和目录；历史仓库为 `lansijian/gdps-2026-embodied-ai`（GitHub），其中已有 `shared/robot_control/g1/adapter.py`、`motion_lock.py`、`loco_backend.py` 和 `shared/navigation/ros2_ws/src/gdps_g1_navigation/`。这些模块曾通过单元测试，但**未因此通过真实导航验收**。不得把以前的模拟避障作为本次核心；可以复用其运动互斥、限速、日志和 fail-closed 实现，但必须审计后融合；不能让两个控制桥同时获得权限。
- 先 `git status --short`、`git remote -v`、列出文件树、查已有 `src/` 包名、查看 Python SDK 本机版本和 DDS 初始化方式。新建功能分支，不修改 main。工作区已有本地改动要完整保留。

## 3. 工程构成——实际落地为 ROS 2 Foxy 标准 colcon 工作空间

建议工程根目录 `g1_mid360_foxy_ws/`，使机器人部署目录为 `/home/unitree/g1_mid360_foxy_ws`（真实路径可通过安装参数配置）。`src` 下至少按下列职责分层；可依据现有结构调整具体包名，但需要保留职责与 README：

```
g1_mid360_foxy_ws/
  src/
    g1_nav_bringup/          # ROS 2 launch, ROS 参数、RViz、地图工具
    g1_nav_perception/       # 时间戳诊断/校正、点云修复、传感器健康、scan pipeline
    g1_nav_tf/               # 机器人动静态 TF 适配、验证工具
    g1_nav_bridge/           # 仅隔离的 cmd_vel G1 高层桥接和监控
    g1_nav_config/           # Foxy Nav2/SLAM 参数、坐标标定、现场 site.yaml
    g1_ros2_bridge/          # 第三方桥接原包或安全裁剪的集成版本（遵守许可证）
  scripts/
    preflight.sh
    install_dependencies.sh  # 非交互检测 + 明确安装开关 + 日志
    build_on_g1.sh
    deploy_from_windows.ps1
    smoke_test.sh
    save_map.sh
  tests/
  docs/
    DEPLOY_FOXY_ARM64.md
    FRAME_CALIBRATION.md
    TIME_SYNC.md
    SAFETY_GATES.md
    VERIFICATION_REPORT.md
  third_party.lock
```

要求 `package.xml` / `setup.py` / `setup.cfg` / install 规则完整，launch 文件、YAML、RViz 配置、地图样例正确被安装至 ROS share 目录，`colcon build` 后 `source install/setup.bash` 可通过 `ros2 pkg prefix` 和 `ros2 launch` 找到所有包；兼容 Python 3.8，Foxy launch API 和旧 CycloneDDS。不得使用 Humble/Jazzy 专属配置字段、API 或插件路径。若有 C++ 包，使用 Ubuntu 20.04 arm64 可用工具链。

## 4. 最大风险 A：倒装 MID-360 的实际坐标变换与地面滤除

必须完成两个分开的变换来源：

- 动态 `odom → robot_center`：由 `/dog_odom` 真实 pose 生成，不允许使用静态 TF 假装机器人不会动，不允许把发布单位/姿态不一致的 odom 误写进 `base_link`。
- 若 Nav2 使用 `base_link`：要通过经核验的真实 URDF 或几何外参建立 `robot_center ↔ base_link` 关系；如该机器人实际更适合 `robot_center` 作为 `robot_base_frame`，可在全套 Nav2 参数里统一使用该 frame，避免无意义新 frame。
- `base_link / robot_center → livox_frame`：使用**真实安装位置及旋转**，通过机器人 URDF、厂家图纸或现场静止 RViz 地板法向/xyz 检查校准。明确创建 `extrinsics.example.yaml`，让安装高度 x/y/z 和四元数可配。已知“倒装”只是方向线索，`roll=π`、`pitch=π`、高度 `z=0.4m` 全都是**待验证候选值**，不准硬编码为事实。
- Foxy 版 `static_transform_publisher` 的命令行 RPY 参数顺序存在历史易混淆问题，优先使用经过单元测试的四元数配置、`robot_state_publisher` 或 Python `StaticTransformBroadcaster`；写测试核验 X/Y/Z 轴、地板法向、点云地面高度，不能只看 RViz 颜色“好像正确”。
- 绝不能由本项目用固定 TF 伪造 `map → odom`：这一路由真正的 SLAM/定位模块唯一发布；每对 TF 父子只允许一个明确发布者，启动时检测冲突。TF 树目标 `map → odom → robot_center/base_link → livox_frame`。
- 在**正确变换到机器人或导航坐标系之后**才裁剪点云高度。原建议 `min_height=-2,max_height=2` 只作为校准时 debug 宽窗口；实际过滤范围应来自雷达安装高度、地面平面、G1 踏步/身体范围及现场障碍物高度，既不能把地板当障碍，也不能漏检桌沿和矮障碍。输出可视化及地面/障碍保留率统计。

## 5. 最大风险 B：时钟、时间戳和订阅 QoS

- 建立 `clock_preflight` 只读检测，记录本机 `CLOCK_REALTIME`、ROS `/clock` 是否存在、雷达与 odom header stamp、收包时间、QoS、连续 30 秒偏差分布、跳变与乱序、丢帧。区分恒定偏差、设备时钟、系统时间、网络传输延迟、ROS use_sim_time；禁止把安装 `ntpdate` 误认成已经同步。所有节点强制一致 `use_sim_time=false`，除非实际使用回放仿真时显式切换。
- 在确认真实时钟来源后优先采用非侵入的时间同步；**不得自动执行 `date -s`、`ntpdate -b`、`timedatectl set-time` 或修改机器人 NTP 服务**。需要人工批准系统级改动。
- 如果现场证实设备 stamp 不可信，在隔离的 `timestamp_fixer` 中订阅原始点云 `/utlidar/cloud_livox_mid360`，发布 `/g1_nav/cloud_timed`；采用有明确时间基准、单调性、防未来时间、防过期/跳变、延迟统计的参数化策略，不要简单每帧永久加/减 4883s。对应 odom/TF/IMU 必须一致；单独重戳某个源可能掩盖同步错误并破坏运动补偿。保留原始话题完全不修改。
- 采集频率约 8–10Hz，选择 sensor_data BEST_EFFORT 或兼容的 ROS QoS 并核对实际 publisher；如果 LaserScan 没下游订阅，Foxy `pointcloud_to_laserscan` 可能不处理点云，smoke test 应主动订阅并确认有输出。时间消息未通过门禁则不启动 Nav2。
- 独立超时门禁：雷达点云、里程计、TF、新鲜扫描消息或时钟异常即输出 STOP/INHIBIT，不能因为 tf tolerance 设置 5s 或无限延长 inflation 就掩盖异常。

## 6. 感知：用成熟算法，不再重写一套避障

- 先检查 `ros2 pkg prefix nav2_bringup slam_toolbox pointcloud_to_laserscan`，APT ROS 源及镜像配置、arm64 架构、`rosdep`。编制 `install_dependencies.sh`，提供**先显示拟安装清单，再经显式 install 选项执行**的机制；用 Foxy 精确版本、固定 git SHA / rosdep，不安装 Humble。若 APT 不可用，准备 Foxy 上游源码构建路径与锁定版本；不得让 Codex 用新版 rolling/master 直接编译 Foxy。尽量不重复编译已经存在的 Nav2 核心包。
- 将正确校准且时间可靠的 `PointCloud2` 接入 Foxy 官方 `pointcloud_to_laserscan` 的 `cloud_in`，由它生成 `/scan`；在 launch 里配置 remapping 和 `target_frame`、高程过滤、`scan_time`（由实测频率决定）、`range_min/max`、`angle_increment`。不要随意创建重复 `/scan` 发布者。
- 保留一个仅用于**可视化和代价地图**的点云话题 `/g1_nav/cloud_obstacles`（若需要做地面剔除），同时评估 Foxy Nav2 `VoxelLayer`/`ObstacleLayer` 是否可直接吃正确转换后的 PointCloud2，用于包含桌沿、矮障碍物的 3D 障碍信息；2D 单切片 LaserScan 可能漏检高度不同的障碍。根据 CPU 性能和数据质量择优，别硬加复杂算法。
- MID-360 低频 8Hz 不代表只要无限放大膨胀半径就安全：机器人足迹、最大速度、扫描延迟、制动距离、costmap 更新率、闭环重规划和新鲜度监控必须共同设计。明确机器人盲区、楼梯/跌落边缘和负障碍无法保证被单束扫描检测到：不满足环境条件则保持 STOP，不能声称全环境安全避障。

## 7. SLAM、定位与 Foxy Nav2 全栈配置

- 采用成熟 ROS 2 **Foxy 对应分支**的 SLAM Toolbox async mapping 建图；已知地图可采用经验证的 localization 模式（SLAM Toolbox localization 或 AMCL 选一），二者**不能同时发布 `map→odom`**。支持 `map_saver_cli`/`slam_toolbox` 地图与 pose graph 保存。明确普通 `/map` 保存与 pose graph 的区别。
- Foxy Nav2：`map_server`、`planner_server`（Navfn）、`controller_server`（默认优先已有 DWB 或已安装且确认可用的 Regulated Pure Pursuit）、`bt_navigator`、`recoveries_server`、`lifecycle_manager`、costmap；配置 plugin class 名称必须与本机 Foxy 实际库相符。TEB 是第三方实现，**本轮不作为必装依赖**；Smac 插件仅在本机确有 Foxy 兼容版本时才启用。
- local costmap 必须确实接收 `/scan` 或 `/g1_nav/cloud_obstacles` 并体现动态障碍，global costmap 订阅地图和实际可用的障碍源。初始 conservative 速度目标示例 `vx≤0.10m/s, vy=0, wz≤0.15rad/s`；示例不是硬件认证极限，真实限速必须通过现场确认及软件双重 clamp。
- 所有节点通过 ROS 2 Foxy 生命周期机制正确激活，支持无地图的建图模式、已有地图定位模式、地图暂缺时的明确错误/阻止导航，不创建假地图以“启动成功”。
- 对 ROS 2 的 `/cmd_vel` 消息提供独立命令观测器；演示给 Nav2 目标点以后能够生成合理的路径和速度**但运动桥在 dry-run 时不得发 SDK 写命令**。

## 8. G1 运动桥——最高优先级安全约束

- 对照本地 `unitree_sdk2py` 的真实安装版本检查 `LocoClient` 方法签名，验证是否支持 `SetVelocity(vx,vy,omega,duration)`、`Move(...)`、`StopMove()`，区分 RPC 回执和真实运动；不得照搬第三方桥中可能不适配版本的 `Move`，也不能强制调用固定 FSM 501 或 500。
- **默认 `allow_live=false` / `dry_run=true` / 不初始化写权限 DDS publisher；不发 `rt/arm_sdk`、腿腰底层关节命令。** 干跑时即使收到任意 `/cmd_vel` 和 `/g1/enable` 也不发实机运动。
- 运动桥必须通过唯一 motion lock，限制加速度、速度、指令频率与持续时间；拒绝 NaN/inf、未经授权的 frame、超限指令，维护最后有效扫描/里程计/TF/心跳时间，守护过期命令 STOP；StopMove 是软件停止而非物理急停，独立急停、跌倒保护、现场清场不能省略。
- ROS callback 与 SDK 互相隔离，保证不会因 SDK 阻塞而无法检测数据超时；若无法保证独立守护停止，应 BLOCK LIVE 并在报告标记为未完成的硬门禁。
- 单一运动源原则：不得同时运行既有自写 `gdps_g1_navigation` 桥、SimonR99 上游 `cmd_vel_bridge`、新 `g1_nav_bridge` 的 LIVE 写端。必要时重命名输入话题为 `/g1_nav/cmd_vel_safe` 并清晰标注路径。不得通过静默启用 Nav2 实现现场自动走路。
- LIVE 必须是独立的现场授权过程，除了软件开关，还需核验真实 FSM、独立急停、旁站人员、固定安全场地、可用 TF 与障碍检测、仿真验证及逐级速度测试。本阶段**不要启用**。

## 9. 单命令 Launch 与可迁移部署

至少开发并使这些入口可以被 Foxy `ros2 launch` 发现（如果某阶段依赖缺失，则要明确预检失败原因，不允许假成功）：

```
ros2 launch g1_nav_bringup sensor_check.launch.py
ros2 launch g1_nav_bringup mapping.launch.py
ros2 launch g1_nav_bringup localization.launch.py map:=/home/unitree/maps/site.yaml
ros2 launch g1_nav_bringup navigation_dryrun.launch.py map:=/home/unitree/maps/site.yaml
ros2 launch g1_nav_bringup g1_nav_bringup.launch.py mode:=dry_run map:=/home/unitree/maps/site.yaml
```

总入口参数允许 `mode:=sensor_check|mapping|localization|dry_run`，默认 `dry_run` 且不允许 `mode:=live` 在本次未经授权的版本生效；任一 preflight 不满足条件须阻止 downstream Nav2 / Bridge 进入允许发送速度的状态。每个 launch 必须设计为**单入口集成启动**，不要让用户手动打开多个终端再分别启动四个节点。使用 Foxy 支持的 `launch` action 和明确的节点生命周期检查。

制作 `preflight.sh` 机器诊断与 `install_dependencies.sh` 带审核的安装脚本、`build_on_g1.sh` ARM64 编译脚本、`deploy_from_windows.ps1`（Windows PowerShell，源路径使用 `E:\GDPS\competition\...`；目标 IP 通过配置发现或用户指定，不能假设 192.168.123.164 永远不变）及 `smoke_test.sh` 只读联调脚本。脚本要求错误码可靠、`set -euo pipefail`、依赖检查、幂等、安全备份、可回滚、输出日志到 `logs/`、不破坏 G1 原生服务。每次安装/运行默认禁止运动。

## 10. 验收与测试门槛（必须实际做，不接受“理论上能运行”）

A. 本地/CI：Python 3.8 语法、YAML 校验、包发现、`colcon` / `launch` 测试、关节/数据 topic 不重名、第三方库许可证与 SHA 固定。没有 ROS 环境时允许用 Ubuntu 20.04 Foxy 容器/CI 作兼容性检查，但必须报告 Docker/CI 与真机不同。

B. 传感器：原厂点云、odom 真实订阅，稳定频率和消息时间戳、QoS 无错误；地面在正确方向且地面高度合理；`/scan` 连续有效，测量非 Inf / 非 NaN 返回比例、采样窗口和 P95 端到端延迟。无法确定倒置安装外参时，应生成可视化标定手册并 BLOCK 后续运动，不是自动瞎填 π。

C. TF：真实 `odom → robot_center`、唯一可信的机体 frame、正确 `livox_frame`；地图定位模式唯一 `map → odom`；实际 `tf2_echo` 和 lookup 成功且时间不超前/过旧，无多个父节点或重复发布者。禁用绕过 TF 报错的无界容错。

D. 建图：在不发运动的条件下，借助已有数据或录制回放验证 Slam Toolbox 创建非空地图（注意静止现场地图可能不足以判断建图质量）；能保存和重新加载地图，定位输出可信。

E. Nav2：全局规划有真实地图与目标才标记通过；发布可视化路径，障碍物加入 local costmap，前方障碍/失去 scan/TF/odom/心跳时 safe_cmd 输出零并有可检查的停止原因。测试动态障碍、丢帧、时间跳变、雷达倒置、错误 TF、旧时间戳、QoS 不匹配、地图缺失、重启时禁止运动、虚假下台阶场景限制。

F. Bridge：dry-run 的自动化 mock G1 SDK 中**写调用次数永远为 0**；LIVE 需要用户明确授权以及独立现场测试，不要借“全通过”自动放行。

G. 迁移：完整 ZIP / git 分支、SHA、从 Windows 打包到 arm64 G1 的复制/安装/编译/启动命令，在机器人端实际执行时提供终端日志。没有访问 G1 的话只能标记 `ROBOT_VERIFICATION_PENDING`，不得声称一键真机已通过。

## 11. 工作流程：直接实施，不要停留在方案

1. 审计当前工作区、ZIP、git 仓库、用户修改与上游兼容性；形成 `EVIDENCE_BASELINE.md` 和依赖差异清单。
2. 构建 Foxy workspace 包、第三方桥接安全集成、TF 校准配置、时间戳节点、点云转换、SLAM/ Nav2 参数和 Launch；按功能提交可审计 Git commits。
3. 编写完整可执行安装/构建/迁移脚本、README、故障排查与 rollback。
4. 执行所有当前环境能运行的测试；逐项修复错误直到无可修复失败。缺机器人硬件验证时输出准确的待验证项，不要仿造通过记录。
5. GitHub 若确认正确仓库且拥有推送权限，在不影响旧代码的特性分支推送并创建 PR；不要直接 merge main，不将机器人私密地址、密码、录制示教等数据公开。
6. 最终输出：分支/commit/PR URL（若实际成功），完整文件树，打包文件位置，测试通过/失败数，各个 launch 实际验证情况，G1 上复制粘贴即可运行的部署命令，所有未确认的校准参数清单及 LIVE 授权状态 `DISABLED`。

**一次性交付优先级**：先做到 `ros2 launch` 能真正带起完整 Foxy 的传感器、TF、建图和 Nav2 dry-run，检查配置而不是只给伪代码；绝不为了“看起来一键运行”而篡改真实 TF、时钟、地图，或让真实 G1 在未授权时移动。碰到无法从源代码得知的机器物理安装参数，以 `BLOCKED_NEEDS_CALIBRATION` 明确标记并给最少现场检验步骤。
