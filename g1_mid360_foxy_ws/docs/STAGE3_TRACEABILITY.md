# 第三阶段 A–G 修改映射与文件清单

设计事实F1–F6来自用户2026-10-20取证，作为输入直接采信。下表“实现”指代码/配置已落地；不代表G1实机已验证。原始规格保存在STAGE3_SPEC.md，待验证项目单列STAGE3_G1_PENDING.md，实际CI结果见VERIFICATION_REPORT.md。

| 指令 | 修改文件（工作空间相对路径） | 当前实现 |
|---|---|---|
| A1 | src/g1_nav_perception/g1_nav_perception/core.py、pipeline.py | OffsetCalibrator：前10帧中位数、10帧均不转发；输出原stamp+会话offset，30帧delta范围>50ms WARN；30秒无足够cloud帧ERROR退出，日志输出实际offset |
| A2–A3 | src/g1_nav_bringup/g1_nav_bringup/launching.py；config/site.g1_default.yaml；src/g1_nav_config/config/site.g1_default.yaml；audit.py | mapping/localization/navigation默认offset，preserve可选、receive_time deprecated；健康检查使用校正后stamp，另保留raw_streams |
| B1 | src/g1_nav_tf/g1_nav_tf/adapter.py；pipeline.py | adapter直接BEST_EFFORT/depth5订阅/dog_odom，最多100Hz，默认z=0、keep_z可选，原样四元数与校正时间；规范化odom也投影供Nav2使用 |
| B2–B3 | adapter.py；src/g1_nav_bringup/g1_nav_bringup/preflight.py；src/g1_nav_tf_authority/src/tf_authority.cpp | 不再以odom_owner控制广播；启动前拒绝已有关键TF边，运行时GID/parent/cycle监控；没有静态odom→robot_center |
| C1 | preflight.py；launching.py | 所有模式最先同步执行旧导航清理，列出匹配PID/命令后SIGINT/SIGTERM；排除当前祖先与原始Unitree DDS/驱动；清理后检查scan/关键TF，keep_legacy只跳过停止，不绕过冲突 |
| C2 | scripts/start_stack.sh；launching.py | --check-only对应check_only:=true，仅清理/验证，不启动传感器/TF/SLAM/Nav2 |
| D1 | src/g1_nav_src/g1_nav_config/rviz/g1_nav.rviz、calibration.rviz、sensor_audit.rviz | 所有默认RViz移除完整点云显示；scan/path不积累历史，显示map/TF/plan/代价地图，不显示cost_cloud/voxel_grid |
| D2 | pipeline.py、adapter.py、audit.py；config/nav2.yaml | 原始传感器订阅BE/depth5；cloud_timed发布BE/depth10；两个costmap只消费scan，去掉第二路完整障碍云订阅；raw原生RELIABLE事实不再混淆 |
| D3 | src/g1_nav_config/config/cyclonedds.xml；dds_profile.py；scripts/prepare_dds.py、common.sh；launching.py | 模板WhcHigh=2MB、MinimumSocketReceiveBufferSize=30MB；进程CYCLONEDDS_URI指向模板或有明确WARN/JSON的本次有效副本。内核受限时读rmem_max或用独立未绑定socket探测并显式限缩，不改sysctl/旧XML；保留回退说明 |
| D4 | src/g1_nav_bringup/g1_nav_bringup/watchdog.py；pipeline.py | 每5秒读取本launch后代RSS，单进程>2GiB WARN，>4GiB记录ERROR/PID/可解析话题后终止，主launch随后结束；经resource_health汇入唯一health；nav2-only单独由watchdog发health |
| D5 | launching.py；start_stack.sh | --nav2-only对应nav2_only:=true，仅Nav2与watchdog，不起感知/SLAM/TF/SDK桥，禁止在该隔离模式使能LIVE |
| D6 | scripts/common.sh；README.md；STAGE3_DEPLOY.md；.github/workflows/g1-mid360-foxy.yml（仓库层） | 显式RMW_IMPLEMENTATION=rmw_fastrtps_cpp对照入口；默认Cyclone。CI增加两个RMW×两个原生架构的矩阵；具体结果不预填 |
| E1 | launch/navigation.launch.py；launching.py；src/g1_nav_bridge/g1_nav_bridge/smoother.py、bridge.py、live_backend.py | 新navigation入口完整链路+AMCL/Nav2+20Hz stamped smoother+桥；提供显式SDK SetVelocity后端，默认allow_live=false，dry_run不能开启。接口/domain需真实传入；不自动切FSM/起立/低层关节 |
| E2 | src/g1_nav_config/rviz/g1_nav.rviz；Nav2原版bt_navigator | Fixed Frame=map，SetGoal发布/goal_pose，直接复用Foxy内置目标接口；有Map/Plan/LocalCostmap/GlobalCostmap/TF，不新增重复目标转发 |
| E3 | src/g1_nav_bringup/g1_nav_bringup/goals.py；launching.py；src/g1_nav_config/config/waypoints.example.yaml；config/nav2.yaml | g1_nav_waypoint_follower客户端读map航点列表，调用Foxy官方/FollowWaypoints（首字母大写），由官方server顺序执行；成功且无漏点时才loop，失败停止，输出JSON汇总；不自动执行示例真实坐标 |
| E4 | config/nav2.yaml；STAGE3_DEPLOY.md；tests/ros_integration.py | 两模式共用官方切片/scan；ObstacleLayer scan marking+clearing；controller20Hz、local update8Hz；纸箱测试方法与停障/绕行的区别明确写出 |
| F1 | smoother.py；bridge.py；launching.py | Foxy原版controller内部仍Twist（不修改/opt/ros ABI），隔离端经smoother统一变TwistStamped，bridge校验robot_center+新鲜stamp；legacy默认false，独立无头话题按需兼容；safe预览同为Stamped |
| F2 | core.py、pipeline.py、launching.py | validate_site只硬拒绝命令速度/加速度/超时；其余site诊断为WARN/健康标志。可启动不代表允许真实运动；非法消息/地图资源边界仍受保护，不将坏数据喂给C++ |
| F3 | audit.py；launching.py | mapping基础门禁只看cloud流量/时间与持续窗口，30秒；不以未精标定/足迹等WARN阻止建图节点启动 |
| G1 | config/site.g1_default.yaml与包内同名正式模板；settings.py；launching.py；start_stack.sh | 按输入写入[0,0,0.4]、q=[0,1,0,0]，顶部粗标定待替换说明；默认offset。包装脚本优先root正式配置，直接launch默认安装副本；缺失回退example+WARN |
| G2 | adapter.py | robot_center→base_link/base_footprint恒等静态别名；与动态odom保持独立，无静态odom |
| G3 | .gitattributes；scripts/package_workspace.py、fix_source_mtime.py、build_on_g1.sh；setup.py；README.md | LF、ZIP epoch/Unix可执行位、src/scripts未来mtime校正、ament entry_points；部署三步；当前环境说明使用~/cyclonedds_ws，旧阶段文档移入history |

## 交付与验证文件

- STAGE3_DEPLOY.md：复制/解压/构建、双终端、保存地图、标点/航点、使能边界、FastDDS/隔离诊断、纸箱测试与回退。
- STAGE3_G1_PENDING.md：offset/OOM/两种真机业务闭环/SDK与资源监控等实机待验证表。
- VERIFICATION_REPORT.md、docs/ci/阶段摘要：本轮实际执行结果、原生ARM64/Foxy代码SHA、CI URL与限制。
- tests/test_stage3.py：offset、TF投影、清理范围、DDS缓冲回退、RSS PID范围、Stamped拒绝、SDK有限租期/过期命令/互斥等合成合同。
- tests/ros_field_regression.py：实际Foxy BE/RELIABLE发布端→offset→官方scan。
- tests/ros_integration.py：合成20,064点负载、SLAM/地图保存/AMCL/Nav2/FollowWaypoints、动态障碍与丢流/时间/TF/布局故障、零SDK写与退出。
- SOURCE_MANIFEST.json：压缩包逐文件SHA256；压缩包旁delivery.json记录代码/测试SHA与归档SHA256。

没有连接G1、没有发真实运动、没有修改原厂服务/驱动/时钟、没有合并main。默认运行不会导入SDK；代码中的可选真实后端必须现场验收，不能用合成或API doubles证明安全。
