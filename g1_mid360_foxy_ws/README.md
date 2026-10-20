# Unitree G1 MID-360 / Foxy 第三阶段工作空间

目标：Ubuntu20.04 ARM64、系统Python3.8、ROS2 Foxy、CycloneDDS（实机有效overlay `~/cyclonedds_ws`）。设计输入采信用户2026-10-20取证F1–F6，完整新规格在 [STAGE3_SPEC.md](docs/STAGE3_SPEC.md)。此前规格/报告仅供历史追溯，新阶段指令优先。

**G1部署三步与双终端命令：** [STAGE3_DEPLOY.md](docs/STAGE3_DEPLOY.md)。
**修改文件与A–G映射：** [STAGE3_TRACEABILITY.md](docs/STAGE3_TRACEABILITY.md)。
**实机待验证清单：** [STAGE3_G1_PENDING.md](docs/STAGE3_G1_PENDING.md)。
**实际执行的测试与CI证据：** [VERIFICATION_REPORT.md](docs/VERIFICATION_REPORT.md)。

- 单入口先清理旧导航栈，再运行会话offset标定、直接dog_odom投影TF、官方点云转scan、SLAM或AMCL/Nav2。前10帧中位数，期间不转发；30秒不足帧报错。preserve用于已同步场景，receive_time已deprecated。
- 传感器输入BEST_EFFORT/depth5；内部cloud_timed输出BEST_EFFORT/depth10。RViz不订阅完整点云；costmap只消费实时scan，避免完整点云多路扇出。
- 包内DDS模板WhcHigh=2MB/接收缓冲最低30MB。启动检测内核能力，若受限则WARN并记录本次有效副本，不修改sysctl或原XML。已加入OOM缓解措施，**不声称OOM已解决**。
- 每5秒记录本launch后代进程RSS，单进程>2GiB WARN，>4GiB记录并终止。资源信息合并到唯一/g1_nav/health。--nav2-only与--check-only用于隔离排查。
- 标点用Foxy原生/goal_pose；巡航客户端调用官方FollowWaypoints，提供YAML列表/loop/汇总报告。避障核心仍是Navfn/DWB与ObstacleLayer，controller20Hz、local costmap8Hz、scan marking/clearing开启。
- 粗标定Y轴180°/z=0.4按输入落地并保持未精标定状态；无静态odom变换。直接动态odom→robot_center最多100Hz、默认z=0，提供robot_center→base_link/base_footprint别名。
- calibration等非命令安全问题WARN并影响健康，不再阻断节点启动；速度/加速度/命令超时上限仍硬拒绝。默认navigation也不使能真实输出，必须现场完成校准/足迹/环境与急停验证，显式allow_live及真实SDK接口/domain后才可使用SetVelocity后端。不会自动切FSM/起立或控制低层关节。

## 常用命令

```bash
# 一次性构建后，终端1：
bash scripts/start_stack.sh --check-only
bash scripts/start_stack.sh mapping
# 终端2：
bash scripts/start_rviz.sh navigation
```

已有真实地图时，终端1改为：

```bash
bash scripts/start_stack.sh navigation map:=/home/unitree/maps/site.yaml
# 或始终无真实输出的预览入口
bash scripts/start_stack.sh dry_run map:=/home/unitree/maps/site.yaml
```

默认正式站点为config/site.g1_default.yaml；缺失回退example并WARN。不要运行另外的fix_stamp、TF或scan补丁。直接ros2 launch支持sensor_check、mapping、localization、navigation_dryrun、navigation及统一g1_nav_bringup共6个入口。

FastDDS对照（两个终端同选项）：

```bash
RMW_IMPLEMENTATION=rmw_fastrtps_cpp bash scripts/start_stack.sh dry_run map:=/home/unitree/maps/site.yaml
RMW_IMPLEMENTATION=rmw_fastrtps_cpp bash scripts/start_rviz.sh navigation
```

扔纸箱验证法：先dry-run观察scan、代价地图标记/清除、规划更新与速度预览；有现场运动授权和独立急停后，在行进路线放纸箱，要求及时停障并在有安全通路时绕行，移除后恢复。停住不等于绕行闭环通过。真实运动、offset值、OOM效果均必须在G1验收。

## 包组成与消息边界

7个colcon包：g1_nav_bringup、g1_nav_perception、g1_nav_tf、g1_nav_tf_authority、g1_nav_bridge、g1_nav_config、g1_ros2_bridge。后者仅复用经审查的29关节元数据，不运行第三方默认运动launch。

Foxy原版Nav2的隔离输出/g1_nav/cmd_vel_nav2仍为Twist。项目20Hz smoother适配为带robot_center及当前stamp的TwistStamped，bridge默认只收/g1_nav/cmd_vel_stamped；/g1_nav/cmd_vel_safe也是TwistStamped。legacy=false，打开后才支持单独的无头Twist话题。smoother仅做Foxy消息兼容与速度/加速度约束，不是自写避障算法。

SDK后端仅在显式allow_live下惰性初始化，默认测试不导入SDK、不创建DDS运动writer。软件0.1s有限租期和RPC超时不能代替独立物理急停；真实SDK路径必须在现场验证。

仅在隔离测试域运行合成测试：`ROS_DOMAIN_ID=87 G1_NAV_TEST_ONLY=1 bash scripts/test_on_foxy.sh`。绝不能在连接机器人生产域时运行fixtures。
