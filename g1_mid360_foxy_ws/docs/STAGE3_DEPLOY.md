# 第三阶段 G1 部署与双终端操作

设计输入为 STAGE3_SPEC.md 中 F1–F6（用户2026-10-20实机取证）。原始两个话题发布端均为RELIABLE；本项目传感器订阅统一BEST_EFFORT。有效DDS环境为 `~/cyclonedds_ws`，保留其自编译rmw，不重装原厂驱动/SDK。新包只对本栈进程设置调优XML，不修改旧XML、系统时钟或sysctl。

## G1 部署三步

先将 `g1-mid360-foxy-stage3-20261020.zip` 复制到机器人家目录。选择全新目录，避免覆盖旧工作空间。以下命令在G1执行，本次开发没有远程执行它们。

第一步：解压（目录存在时停下并换新目录）：

```bash
cd ~
mkdir g1_mid360_foxy_ws_stage3_20261020 && \
  unzip g1-mid360-foxy-stage3-20261020.zip -d g1_mid360_foxy_ws_stage3_20261020
cd ~/g1_mid360_foxy_ws_stage3_20261020
```

第二步：原生环境、文件时间和构建：

```bash
# 若处于Conda，先重复执行 conda deactivate 直至退出所有Conda环境。
python3 --version                    # 必须为系统Python3.8
source /opt/ros/foxy/setup.bash
test ! -f ~/cyclonedds_ws/install/setup.bash || source ~/cyclonedds_ws/install/setup.bash
find src scripts -type f -exec touch {} +
chmod +x scripts/*.sh
bash scripts/build_on_g1.sh
```

`touch` 仅改变新解压源码时间，不改系统时钟、地图或原始数据；构建脚本还会记录并校正未来mtime。Python节点采用ament entry_points安装，生成的可执行入口无需手工`python node.py`。若缺依赖，仍先 `bash scripts/install_dependencies.sh --plan`，审核精确候选后才执行 `--install`，不更新整个系统。

第三步：清理体检，再一键建图：

```bash
bash scripts/start_stack.sh --check-only
bash scripts/start_stack.sh mapping
```

第二个终端：

```bash
cd ~/g1_mid360_foxy_ws_stage3_20261020
bash scripts/start_rviz.sh navigation
```

默认会先列出并终止明确匹配的旧SLAM/scan/Nav2/g1_nav进程，等待退出，再检测 `/scan` 和待发布TF边是否已有owner。保护当前launch及其祖先进程，不匹配原始宇树DDS/雷达驱动。无法停止、旧服务重新拉起或有剩余TF冲突会明确失败，不能把这种状态当成清理成功。不会自动修改systemd服务。遇到其他UID的明确导航PID时，仅尝试sudo -n对该PID发信号，不弹密码框；没有免密权限则列出UID/PID并失败，不隐瞒残留。`keep_legacy:=true`仅跳过终止，**不会绕过重复发布检查**。

默认site为新工作空间 `config/site.g1_default.yaml`。直接 `ros2 launch` 默认使用包内安装副本；手工改了root配置后请始终显式传 `site:=$PWD/config/site.g1_default.yaml` 或使用start_stack。正式模板是粗标定Y轴180°、z=0.4，明确未精标定，不标记已验证。缺正式文件则回退example并WARN，不猜测缺失外参。未确认足迹使用明确标记的临时圆半径配置启动Nav2，健康标志继续抑制真机输出，不能将该圆当成已测足迹。

建图等待基础cloud持续健康30秒；offset前10帧不转发，标定后日志出现 `OFFSET_CALIBRATED cloud offset_s=...`。每次启动重新标定，不复用69.8/4883。30秒不足10帧会报错并结束；窗口delta变化超过50ms会WARN。odom/IMU也独立映射到系统时钟域，保留各自原始时间诊断。TF直接来自 `/dog_odom`，最多100Hz、z投影为0，四元数透传；`keep_z:=true`可保留真实z。

## 保存地图，然后切换导航

可在RViz终端暂时执行保存，再恢复RViz，不需要常驻第三终端：

```bash
bash scripts/save_map.sh /home/unitree/maps/site_stage3 --pose-graph
```

停止mapping后，在终端1启动实际机器人模式入口（默认运动仍关闭）：

```bash
bash scripts/start_stack.sh navigation map:=/home/unitree/maps/site_stage3.yaml
```

终端2继续使用 `bash scripts/start_rviz.sh navigation`。RViz Fixed Frame=map；用2D Pose Estimate设置真实初始位姿，再用2D Nav Goal标点（`/goal_pose`，Foxy bt_navigator原生接收）。显示map、plan、local/global costmap和TF，不显示任何完整点云/cost_cloud/voxel_grid。

dry-run入口：

```bash
bash scripts/start_stack.sh dry_run map:=/home/unitree/maps/site_stage3.yaml
```

两入口均为同一感知链路、AMCL、Navfn/DWB、20Hz速度smoother和Stamped bridge；`navigation`允许显式开启SDK后端，`dry_run`永远不启用。Nav2本身是Foxy原版，原生内部输出仍为Twist；隔离话题 `/g1_nav/cmd_vel_nav2` 只有一个受信controller writer，由本工程smoother加时间戳/机体frame并限加速度，输出 `/g1_nav/cmd_vel_stamped`。bridge默认只收TwistStamped，错误frame/旧stamp拒绝并WARN。`legacy:=true`才兼容单独的 `/g1_nav/cmd_vel_legacy` 无头Twist，默认false。

本项目smoother是Foxy速度消息适配与限加速度器；不是移植新版Nav2 velocity_smoother包，也不替代Nav2避障算法。`/g1_nav/cmd_vel_safe`同样是TwistStamped。

## 真实运动使能条件

粗标定/未确认足迹等字段不再阻断节点启动，但保留WARN和健康状态；这与允许机器人行走是两个边界。默认allow_live=false，不导入/初始化SDK。site.live保留兼容默认值，不是本阶段的硬件使能入口；请保持模板旧值，实际使能只能通过navigation的显式launch参数，健康不满足仍拒绝输出。

现场精标定、真实足迹/场地/盲区审核、时间标定与独立急停确认完成后，填写真实证据，现场操作员才可显式使能。接口/domain不提供虚构默认值：

```bash
# 由现场填写已核实的值；本次开发不执行此命令。
export G1_SDK_INTERFACE='现场确认的接口名'
export G1_SDK_DOMAIN='现场确认的SDK domain数字'
bash scripts/start_stack.sh navigation map:=/home/unitree/maps/site_stage3.yaml \
  allow_live:=true sdk_interface:="$G1_SDK_INTERFACE" sdk_domain:="$G1_SDK_DOMAIN"
```

后端仅调用高层SetVelocity，0.1s有限租期，RPC超时/错误粘性抑制，速度≤0.1m/s、角速度≤0.15rad/s；不调用FSM/BalanceMode/起立/趴下/低层关节。SDK调用在独立worker，桥定时器不等待RPC。短租期不是已验证的独立物理急停，租期与SDK超时效果必须在G1验收。默认包不能声称已验证真实输出。

## 航点巡航

复制并用真实地图内可达点替换 `waypoints.example.yaml`，顶层frame_id必须为map：

```bash
bash scripts/start_stack.sh navigation map:=/home/unitree/maps/site_stage3.yaml \
  waypoints_file:=/home/unitree/maps/patrol.yaml loop:=false
```

`g1_nav_waypoint_follower`调用Foxy官方 `/FollowWaypoints` action（注意Foxy此名称大写，不能照新版写成/follow_waypoints）顺序执行列表；loop=true只在整轮成功且无missed waypoint时重复。拒绝/失败/漏点会停止循环并输出JSON报告，默认 `~/.ros/g1_nav-waypoints.json`。不自动执行示例坐标。标点与航点不要同时派发任务。

## OOM隔离与回退

```bash
bash scripts/start_stack.sh --nav2-only map:=/home/unitree/maps/site_stage3.yaml
```

只启动Nav2与资源监控，不起感知/SLAM/TF/SDK桥；缺外部TF/scan时不可视为完整导航验收。watchdog每5秒记录本launch后代RSS；单进程>2GiB WARN，>4GiB记录ERROR/可解析话题归属并终止该进程，launch随之失败退出。日志在logs/resources-stage3-*.jsonl；正常链路将resources合并入唯一 `/g1_nav/health`，nav2-only由watchdog直接发布该健康话题，不制造两个health publisher。

调优XML包含WhcHigh=2MB、MinimumSocketReceiveBufferSize=30MB；它们是缓解旋钮，**不是总RSS硬上限**。新进程日志打印实际RMW/ldd和配置路径。启动读取rmem_max；容器隐藏该文件时，用独立未绑定UDP socket探测允许缓冲。若不足30MB，会WARN并生成本次受限副本，记录requested/applied，不修改模板或sysctl。若仍无法初始化，应核对实际DDS版本/内核限制，使用明确的dds_config路径调整。若需要保留旧XML中的网卡/Peers配置，把其相应节点合入调优文件副本并通过 `dds_config:=/absolute/site.xml` 使用，不盲用网卡名。

FastDDS对照实验（两终端一致，库已由实机反馈确认安装）：

```bash
RMW_IMPLEMENTATION=rmw_fastrtps_cpp bash scripts/start_stack.sh dry_run map:=/home/unitree/maps/site_stage3.yaml
RMW_IMPLEMENTATION=rmw_fastrtps_cpp bash scripts/start_rviz.sh navigation
```

最终CI中FastDDS两组未完成集成（ARM64航点超时、x86生命周期关闭超时）；它目前仅作为诊断对照，不作为已验证替代。详见VERIFICATION_REPORT.md。

同一运行不要混用RMW或预载另一家库。回退只需停止新栈，重新使用保存的旧CYCLONEDDS_URI/工作空间；不改厂商服务。OOM效果、实际自编译DDS版本和FastDDS互通仍须G1对照，不能称OOM已解决。

## 扔纸箱验证法与停止

先dry-run看实时 `/scan`、局部代价地图标记/清除、规划更新及速度预览；有现场运动授权与急停保护后，在行进路线放置纸箱，要求及时减速/停止并在有安全通路时绕行，移走后清除占据。controller=20Hz，local costmap更新8Hz，ObstacleLayer实时scan marking/clearing开启。不能把“停住”单独记作“绕行闭环通过”；楼梯/负障碍/足部盲区仍要单独验证。

在RViz终端执行 `ros2 run g1_nav_bringup shutdown` 后，再在终端1 Ctrl-C。它是本栈的生命周期清理，不是机器人硬件急停。
