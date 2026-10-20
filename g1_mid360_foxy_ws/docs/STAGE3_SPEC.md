【第三阶段终版修改指令 —— 基于实机取证结论，直接采信以下事实，不要重新设计推翻】

═══ 实机已验证事实（取证日期 2026-10-20，作为设计输入） ═══

F1. 时间偏差：MID-360 点云时间戳与系统时钟存在固定偏差（本次上电 69.8s，上次 4883s，
    每次上电变化，会话内 800 帧零漂移）。禁止硬编码任何偏差值，必须运行时自动标定。
F2. QoS 实况：/utlidar/cloud_livox_mid360 与 /dog_odom 的发布者均为 RELIABLE（宇树原生
    进程 _CREATED_BY_BARE_DDS_APP_）。所有订阅端一律 BEST_EFFORT 即可兼容。
F3. /dog_odom：nav_msgs/Odometry，header.frame_id=odom，child_frame_id=robot_center，
    约 800Hz，pose.position.z≈0.735 为机身中心离地高度（2D 导航需投影到地面）。
    帧名与本项目 robot_center 命名天然一致，直接对接。
F4. OOM 已实锤（dmesg 记录 planner_server 4.1GB / waypoint_follower 7.0GB /
    controller_server 12.4GB / rviz2 14.2GB / ros2 cli 14.2GB 被内核 OOM-kill）。
    根因定性为数据面：大点云消息 × RELIABLE 发布 × 多订阅（rmw_cyclonedds 上游 issue
    #292 同款问题）。costmap 参数正常（3×3/20×20@0.05），/dev/shm 7.6G 富余，均排除。
F5. 机器人实际生效的 DDS 是 ~/cyclonedds_ws（含自编译 rmw_cyclonedds_cpp 与
    cyclonedds.xml），~/cyclonedds-0.10.2 为闲置副本。现有 xml 无任何内存控制配置。
F6. 机器人开机常驻一套旧导航栈（slam_toolbox / pointcloud_to_laserscan / nav2 全家 /
    旧 g1_nav pipeline），其 /scan 因 TF 时间戳不匹配而零输出。新栈启动前必须清理。

═══ 任务 A：时间戳 offset 策略（P0）═══

A1. g1_nav_pipeline 的 prepare() 新增第三种时间策略 "offset"：
    - 前 10 帧：计算 delta = t_now - t_lidar，取中位数作为 offset，期间不转发
    - 标定完成后 log 输出 offset 值；之后每帧 stamp = 原始stamp + offset
    - 滚动监测最近 30 帧 delta，若波动 > 50ms 打 WARN（可能是漂移而非固定偏差）
    - 若 30 秒内收不到足够帧，明确报错退出，不许静默
A2. mapping / localization / navigation 三种模式默认 time_strategy := "offset"
    （"preserve" 保留给时钟已同步场景，"receive_time" 标记 deprecated）
A3. timing 校验基于校正后的时间戳执行，避免 offset 模式被自己的健康检查误杀。

═══ 任务 B：odom TF 直接对接 /dog_odom（P0）═══

B1. g1_nav_tf adapter 订阅 /dog_odom（BEST_EFFORT, depth≤5），降频到 100Hz，
    广播 odom -> robot_center 动态 TF：
    - pose.position.z 强制置 0（可配参数 keep_z 控制是否投影）
    - 四元数原样透传
    - TF 时间戳使用校正后的消息时间戳，与点云时钟域对齐
B2. 去掉 tf.odom_owner=project 的条件门槛——TF 广播无条件启动。
    （原因：F3 已实机验证 /dog_odom 可用且帧名匹配，旧版条件门禁会阻碍一键启动）
B3. 严禁任何静态 odom->robot_center TF 与动态广播并存（启动预检测重复 broadcaster）。

═══ 任务 C：旧栈清理预检（新增，部署级 P0）═══

C1. 新增 preflight 清理步骤（g1_nav_bringup 所有模式启动时最先执行）：
    - 检测并终止残留节点：slam_toolbox、pointcloud_to_laserscan、nav2 全套
      (planner/controller/bt_navigator/waypoint_follower/recoveries/costmap)、
      旧 g1_nav_* 各节点
    - 提供 launch 参数 keep_legacy:=false 控制；检测到残留时先 WARN 列出再杀
    - 清理后验证 /scan、/tf 无重复发布者才继续启动
C2. --check-only 模式：只跑预检+清理验证，不启动建图/导航，用于部署后快速体检。

═══ 任务 D：OOM 数据面防御（重点重写）═══

D1. RViz 配置减配（g1_nav.rviz）：
    - 禁止订阅原始点云 /utlidar/cloud_livox_mid360；点云显示只允许
      降采样后的话题（或干脆只显示 /scan + map + TF + 路径）
    - 所有显示话题 decay time ≤ 5s；点云 size 0.03、style Points（非 Boxes/Squares）
    - 不显示 costmap 的 /cost_cloud、/voxel_grid 等高频辅助话题
D2. 所有点云订阅 QoS：BEST_EFFORT + depth ≤ 5；/g1_nav/cloud_timed 发布 depth 提到 10。
D3. 新增调优版 cyclonedds 配置并随包分发（g1_nav_config/config/cyclonedds.xml），
    参考上游 issue 的调优项，至少包含：
    <Internal>
      <Watermarks><WhcHigh>2MB</WhcHigh></Watermarks>
      <MinimumSocketReceiveBufferSize>30MB</MinimumSocketReceiveBufferSize>
    </Internal>
    （数值需实机验证后微调；xml 顶部注释写明每个旋钮的作用和回退方法）
    launch 启动前 export CYCLONEDDS_URI 指向包内该文件。
D4. 新增轻量 watchdog 节点（并入 g1_nav_bringup 或独立小包）：
    - 每 5s 读取本 launch 内各子进程 RSS（/proc/<pid>/status）
    - 单进程 > 2GB 打 WARN；> 4GB ERROR 并终止该进程、报告话题归属
    - 输出到 /g1_nav/health，便于事后定位"谁先漏"
D5. navigation 模式提供分阶段启动参数：--nav2-only（只起 Nav2 不起感知/SLAM），
    用于隔离定位哪个进程先膨胀。
D6. README 写明 fastrtps 对照实验：RMW_IMPLEMENTATION=rmw_fastrtps_cpp
    （实机已装 librmw_fastrtps_cpp.so），用于二分定位 rmw_cyclonedds 的嫌疑。

═══ 任务 E：两种导航模式 + 动态避障（业务需求）═══

E1. 新建 navigation.launch.py（真机模式，区别于 dryrun）：
    完整传感器链路 + AMCL + Nav2 全栈 + velocity_smoother -> bridge 实机输出。
E2. RViz 标点导航：g1_nav.rviz 配置 2D Nav Goal Tool（/goal_pose），Fixed Frame=map，
    显示 Map/Path/Plan/LocalCostmap/GlobalCostmap/TF。
E3. 新建 g1_nav_waypoint_follower：
    - 参数 waypoints_file（YAML：[{x,y,yaw},...]，frame_id=map）+ loop 参数
    - 逐点调用 nav2 FollowWaypoints action，结束输出汇总报告
    - 附 waypoints.example.yaml
E4. 动态避障硬性要求（两种模式都必须）：
    - local_costmap ObstacleLayer 订阅实时 /scan（marking+clearing 开启）
    - 确认切片节点（pointcloud_to_laserscan）与 mapping 模式共用同一链路/话题
    - controller 频率 ≥ 20Hz，local costmap update_frequency ≥ 5Hz
    - README 写"扔纸箱验证法"：机器人行进路线上放置障碍物，应实时绕行

═══ 任务 F：消息升级与校验降级 ═══

F1. bridge 输入升级 TwistStamped：校验 header.frame_id==robot_center，
    非 robot_center 拒绝并 WARN；legacy 参数（默认 false）兼容无头 Twist。
    velocity_smoother/Nav2 输出端同步升级。
F2. core.py 完整校验：仅安全类字段（速度/加速度上限、命令超时）失败才 Block；
    其余（外参一致性等）降级为 WARN + 影响健康状态位，不阻断启动。
F3. mapping 模式 30s 健康门禁只要求"cloud 在流"级别的基础项。

═══ 任务 G：外参落地与部署 ═══

G1. 生成 config/site.g1_default.yaml（正式模板，非 example）：
    - translation_xyz: [0.0, 0.0, 0.4]
    - quaternion_xyzw: [0.0, 1.0, 0.0, 0.0]  （绕Y轴180°，粗标定值）
    - time_strategy: offset
    - 顶部注释注明需现场精标定后替换
    统一入口 site 参数默认指向该文件，缺失回退 example + WARN。
G2. TF adapter 追加发布恒等别名 TF：robot_center->base_footprint、
    robot_center->base_link（兼容 AMCL/Nav2 插件默认寻找的基座名）。
G3. 部署三件套：LF 行尾统一、Python 节点 chmod +x + entry_points 校验、
    README"G1 部署三步"（解压 -> touch 修时间戳 + colcon build -> 一键启动）。
    环境说明按 F5 修正：CYCLONEDDS 相关路径写 ~/cyclonedds_ws，删掉对
    ~/cyclonedds-0.10.2 的引用。

═══ 交付要求 ═══

完成后输出：修改文件清单 + 与 A~G 的逐项映射 + 一张"实机待验证项"清单
（明确标注哪些只能上 G1 验证：offset 标定值、OOM 防御效果、两种导航闭环）。
不许自测通过话术，不许声称解决了 OOM——只能说"已部署缓解措施"。
