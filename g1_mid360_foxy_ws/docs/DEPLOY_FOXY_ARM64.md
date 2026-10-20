# Field fix r2

新版双终端入口与更新时间策略见 [FIELD_FIX_R2.md](FIELD_FIX_R2.md)，本轮测试边界见 [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md)。下文为底层安装/标定/保存地图步骤。不要同时运行独立 fix_stamp.py、TF 或 scan 转换器。

# G1 本地部署（Ubuntu 20.04 ARM64 / Foxy / CycloneDDS）

本版本 LIVE=DISABLED，没有 SDK 写调用路径。真实外参、时间来源、足迹、安全场地未确认时，正式导航入口会报错；这是有效阻断，不能将模板里的 null 改成猜测值。机器人端命令尚未在真实 G1 执行，状态 ROBOT_VERIFICATION_PENDING。

## Windows 打包及复制

源码在本次隔离分支工作树，原工作树及原厂文件不受影响。目标地址必须现场查验后填入；不提供虚构 IP。

```powershell
$Source = 'E:\GDPS\competition\dist\g1-mid360-foxy-20261020\g1_mid360_foxy_ws'
$RobotHost = Read-Host '输入现场核验的 G1 SSH 主机名或 IP'
& "$Source\scripts\deploy_from_windows.ps1" -RobotHost $RobotHost -Source $Source
```

脚本生成带逐文件 SHA256 清单的源码 tar.gz，scp 到临时路径，远端复核压缩包 SHA256，再解压至全新目录。目标存在即失败，不覆盖。需要更新时指定新的 `-Destination /home/unitree/g1_mid360_foxy_ws_release2`，保留旧版本作为回滚。它不安装、不启动节点、不更改服务或时钟。SSH 使用现有主机密钥校验。

也可以在机器人上把特性分支克隆到全新目录，再复制该分支中的 g1_mid360_foxy_ws；不要重置已有仓库。

## 机器人安装、构建、原始传感器审计

```bash
cd /home/unitree/g1_mid360_foxy_ws
bash scripts/install_dependencies.sh --plan
# 人工审核 logs/dependencies.json 中的包来源与精确候选版本，再执行：
bash scripts/install_dependencies.sh --install
bash scripts/build_on_g1.sh
source /opt/ros/foxy/setup.bash
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# 保留原厂已核验的 ROS_DOMAIN_ID / CYCLONEDDS_URI；不要盲设 eth0。
bash scripts/preflight.sh
```

先由 `ip -brief address` 和现有原厂 CycloneDDS 配置确认接口和 domain。旧 CycloneDDS 的配置必须使用该机支持的 XML；本项目不生成新版 `<Interfaces>`，不 monkey-patch SDK。不要再启动第二份 Livox 驱动或原厂 bridge robot.launch.py。

预检退出非零需要读日志解决原因，不能忽略。SDK audit 只解析安装源码/方法参数，不导入 SDK、不建立 DDS，也不调用 GetFsmId；现场读取真实 FSM 仍须原厂只读流程和旁站确认，禁止自动切换 500/501。

APT 未找到候选时不修改系统源、不安装其他 ROS 发行版。先检查日志中 ROS 源、arm64 和索引状态；系统级修复由现场审核执行。源码备选：

```bash
python3 scripts/fetch_foxy_sources.py          # 仅显示缺失包及固定 SHA
python3 scripts/fetch_foxy_sources.py --fetch  # 明确下载，固定 detached commit
# 对缺失源码先审核依赖模拟结果；不要重编译已安装的 Nav2 核心：
rosdep install --simulate --from-paths external_sources --ignore-src --rosdistro foxy
# 只有审核完成、依赖已满足后，指定缺失包（例子中按实际目录调整）：
colcon build --base-paths src external_sources/slam_toolbox external_sources/pointcloud_to_laserscan --executor sequential
```

源码 fallback 的 ARM64 编译、rosdep 可得性未验证。若缺的是 nav2_bringup，先用 `colcon list --base-paths external_sources/navigation2` 核对，选择 `--packages-select nav2_bringup`，不要默认构建整个 Navigation2。

## 配置与一键 Launch

```bash
mkdir -p config
cp src/g1_nav_config/config/site.example.yaml config/site.yaml
export G1_NAV_SITE="$PWD/config/site.yaml"
ros2 launch g1_nav_bringup sensor_check.launch.py
```

该入口在未校准时仍订阅原厂 cloud/odom/IMU 并发布健康诊断；不会发布猜测的静态 TF，不会启动 Nav2。按 FRAME_CALIBRATION.md 和 TIME_SYNC.md 完成现场只读验证后，填写真实数值和证据 ID，保留 allow_live=false/dry_run=true。足迹与高程窗口、scan_time 都必须实测。

一次只启动一个入口；每个入口自身集成传感器、TF、scan 和必要的下游，不需要用户手工拆成多个节点终端。切换模式先 Ctrl-C 完整退出旧 launch。以下命令是互斥的运行选项：

```bash
ros2 launch g1_nav_bringup mapping.launch.py
ros2 launch g1_nav_bringup localization.launch.py map:=/home/unitree/maps/site.yaml
ros2 launch g1_nav_bringup navigation_dryrun.launch.py map:=/home/unitree/maps/site.yaml
ros2 launch g1_nav_bringup g1_nav_bringup.launch.py mode:=dry_run map:=/home/unitree/maps/site.yaml
```

mapping 仅启动 SLAM，不启动 AMCL。localization/dry_run 使用真实 occupancy map 与 AMCL，不启动 SLAM。连续 30 秒传感器、时间、scan、TF 检查成功后才启动下游；60 秒未满足则关闭整个入口。AMCL 仍需在 RViz 用 **2D Pose Estimate** 提供现场确认的初始位姿，不能自动填原点。随后才可用 **Nav2 Goal** 发送 dry-run 目标。没有 map→odom、有效地图或活动生命周期时，规划不算通过。即使形成路径和速度，本版本也绝不驱动真实 G1。

```bash
rviz2 -d "$(ros2 pkg prefix g1_nav_config)/share/g1_nav_config/rviz/g1_nav.rviz"
bash scripts/smoke_test.sh
ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
ros2 lifecycle get /planner_server
ros2 lifecycle get /controller_server
ros2 lifecycle get /bt_navigator
ros2 topic echo /g1_nav/command_observer
```

smoke 为主动 scan/TF/时间门禁，不替代地图、规划和硬件验收。另行检查 `/plan`、`/local_costmap/costmap`、`/global_costmap/costmap` 与 `/g1_nav/cmd_vel_nav2`。禁止为通过检查而造图、伪造 TF 或扩大时间容差。

## 地图保存和回滚

```bash
bash scripts/save_map.sh /home/unitree/maps/site_20261020 --pose-graph
```

保存 occupancy YAML/PGM 用于本工程 AMCL；posegraph/data 用于 SLAM Toolbox 后续继续建图，它们不是同一种文件，不能互换。本次定位选择 AMCL，不声称已实现 pose graph reload 定位。脚本拒绝覆盖已有地图。地图丢失时定位/导航必须失败。

定位/导航退出前先运行 `ros2 run g1_nav_bringup shutdown`（纯定位加 `--localization-only`），通过 Nav2 lifecycle manager 完成去激活与清理，再 Ctrl-C。它只管理本项目的 Nav2 节点，不能作为真实机器人的紧急停止。

回滚：Ctrl-C 停止本项目 launch，检查无残留本项目进程，再使用保留的旧工作空间。没有本工程 systemd 开机项，没有原厂服务修改，不需要卸载 SDK/驱动/ROS。日志和地图先保留，不执行破坏性清理。本轮没有向真实机器人复制或执行上述命令。
