# Safety gates and LIVE status

**LIVE: DISABLED. ROBOT_VERIFICATION_PENDING. BLOCKED_NEEDS_CALIBRATION.**

本轮没有 LocoClient 写实例、Unitree DDS writer、FSM 服务、起立/趴下或低层关节命令。mode=live、allow_live=true、dry_run=false 在启动时失败；任意 `/g1/enable` 不会改变权限。/g1_nav/cmd_vel_nav2 为隔离的 Nav2 观测输入，Twist 固定解释为 robot_center 中的平面速度；无 frame header，不接受其他坐标语义。/g1_nav/cmd_vel_safe 只是独立预览出口，不接机器人。

启动 gate 要求真实校准证据、时钟证据、高程窗口与频率、实际足迹、负障碍/盲区审核和受控安全环境。连续 30 秒 cloud/odom/IMU/scan、TF、publisher 唯一性及时间检查通过，才启动 SLAM/AMCL/Nav2。真实地图文件缺失/无效立即报错。mapping 和 localization 的 map→odom 发布者互斥；TF GID 冲突/多父/环会持续阻断至重启。任何 /clock 存在时本版本也阻断，避免混用仿真时钟。

运行 gate 使用本地 monotonic 检测 .3 秒 health 心跳、.25 秒命令超时，scan/odom/IMU 超过 .4 秒失效，TF stamp 默认超过 .3 秒失效。无效/NaN/Inf、非平面、横向或超限命令拒绝为零，速度再限制至 vx .1、vy 0、wz .15；加速度 .05m/s²/.1rad/s²。非零预览只在健康且无保守近障阻断时出现；STOP 不使用慢减速以掩盖超时。近障余量计算依赖已核验足迹、延迟、制动假设，仅作 dry-run 保护观察，不是硬件制动认证，也不替代 DWB 和 Nav2 costmap 避障算法。

共享 `gdps_g1_motion.lock` 防止协作的旧控制源同时占用；无法阻止不遵守锁的第三方程序。TF/health/cmd_vel publisher 数异常会 INHIBIT，但不能把 ROS graph 检查当成排他硬件权限控制。不得同时运行旧 gdps_g1_navigation、原厂 SimonR99 cmd_vel_bridge 或其他 LIVE 写端。dry bridge 从启动到退出一直不调用 SDK，包括 StopMove；软件 StopMove 本身也不是物理急停。

未来 LIVE 必须另行实现并验证：真实 SDK 版本/SetVelocity/Move/StopMove/GetFsmId 签名与 RPC 状态；现场 FSM 人工确认（不固化 500/501）；独立硬件急停与跌倒保护；旁站人员/清场；安全场地；扫描盲区/台阶/负障碍限制；仿真故障测试；独立于 ROS 和阻塞 SDK RPC 的停止守护；唯一运动权限；逐级速度与制动实测。当前所有这些门禁 **未完成，无法启用 LIVE**。

MID-360 8–10Hz 和 2D 投影不能证明楼梯、玻璃、镜面、负障碍或全环境动态避障安全。ObstacleLayer 同时使用 LaserScan 和经过校准的 3D 点云高程窗口，仍可能遗漏窗口以外物体。CPU 性能、真正扫描端到端延迟、刹车、足迹和局部规划效果必须在 G1 实测后复审。

为防止旧 LIVE 桥意外收到全局 cmd_vel，controller_server 的 cmd_vel 输出硬重映射到 `/g1_nav/cmd_vel_nav2`，回收动作输出隔离到 `/g1_nav/recovery_cmd_vel_disabled`。本项目不发布全局 `/cmd_vel`；safe 仍只是预览。运动锁占用或 dry bridge 退出会关闭整个集成入口，不能在桥失效时悄悄留下 Nav2 自动发布。

下游启动还要求 odom 没有既存父 TF，避免覆盖原厂或其他地图系统的 map→odom。检测到已有父关系时输出 EXISTING_ODOM_PARENT 并阻止下游；不会自动停止或修改原厂 SLAM。
