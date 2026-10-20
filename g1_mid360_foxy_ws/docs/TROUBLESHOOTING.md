# Stage 3 现场排查

以STAGE3_SPEC.md F1–F6为已确认设计输入；OOM按数据面根因实施缓解，不重新归咎已排除的正常costmap尺寸或/dev/shm。

1. 先bash scripts/start_stack.sh --check-only，读LEGACY_PREFLIGHT/PREFLIGHT_RESULT。旧服务重启导致残留时保留PID和服务归属，不用pkill python、不停原厂DDS。keep_legacy不会绕过冲突验证。
2. 没有OFFSET_CALIBRATED：前10帧不转发是正常标定；30秒未完成是失败，应检查raw话题实际收包、RMW/domain/接口。不要抄固定偏差。
3. DDS接收缓冲30MB被内核拒绝：启动会WARN并生成受限有效XML，保留requested/applied值。不自动sysctl；可选显式dds_config保留现场接口/Peers。旧自编译rmw来自~/cyclonedds_ws，不能仅因是自编译就拒绝。
4. Python启动失败：退出Conda，系统Python3.8，不混入其他ROS发行版overlay。看python/rmw环境JSON和ldd实际路径。
5. OOM/内存增长：读resources-stage3 JSONL，关注最先增长的PID/发布话题。--nav2-only分离感知，FastDDS按README用同场景对照。缓解效果只能在G1长时间负载和dmesg/RSS证据下判断。
6. /scan正常但无map：检查动态odom→robot_center（z投影、corrected stamp）、robot_center→livox_frame及aliases，不能加静态odom顶替。mapping只等cloud流，TF/scan问题会由SLAM/health继续诊断。
7. Nav2无路径：确保真实map YAML/图像，AMCL ACTIVE且设置真实初始位姿，map→odom存在，所有生命周期ACTIVE。Foxy Goal Tool使用/goal_pose原生入口，不另起重复转发器。
8. bridge为零：核对TwistStamped类型/frame/stamp、健康warnings、map_ready、obstacle_stop和publisher唯一性。粗标定/未知足迹时零输出是预期，不要强改healthy伪造安全状态。
9. 原生Foxy launch在部分异步失败场景可能返回0；start_stack包装脚本还检查failure标记并返回2。以明确错误/节点退出日志与标记为准，不能仅看shell状态。
