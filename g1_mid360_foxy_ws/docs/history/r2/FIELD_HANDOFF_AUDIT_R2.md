# 追加交接文档逐项核对（2026-10-20）

已完整读取用户追加的《Unitree G1 (29-DOF) 运动控制与导航系统实机调试交接文档》。这是用户整理的现场记录，并非本轮重新采集的硬件证据。

| 交接项 | 当前处理 |
|---|---|
| Ubuntu20.04/ARM64/Foxy、Conda Python3.12冲突 | **新增**：脚本和直接 launch 均在 ROS 节点初始化前检查系统 `/usr/bin/python3` 3.8、Conda、PYTHONHOME/PYTHONPATH ABI；有污染明确报错，要求 ROS 终端 conda deactivate，不更改 Conda 安装 |
| SDK 专用 CycloneDDS0.10.2、CYCLONEDDS_HOME/LD_LIBRARY_PATH | **新增**：审计实际安装 RMW 的 ldd 路径并记录解析库；发现 SDK 外部 DDS 进入 ROS 默认阻断，要求独立 ROS 终端。显式 G1_NAV_ALLOW_EXTERNAL_DDS=1 仅供已审核诊断且保留警告，不代表兼容性通过；不删除/重编 SDK DDS、不改原厂环境 |
| NoMachine/gdm3/删除 ~/.nx 维护 | 不属于导航运行依赖，不并入一键启动，不执行系统服务停止、删除会话或重启桌面；这些会中断操作员环境 |
| LocoClient 起身、FSM501、BalanceMode、SetVelocity | 继续禁止真实运动；不加入自动 Damp/Lie2StandUp/FSM/BalanceMode。现场动作描述不能替代独立授权与安全保护。仅保留SDK源码审计，无SDK写通道 |
| rt/arm_sdk、索引0–14增益与极简IK | 不并入导航包，不给未知硬件/模型套用kp200/kd5或低层关节接管；已有示教/手臂工作树保持不动 |
| fix_stamp_final.py：BE输入、系统重戳、RELIABLE输出 | 已覆盖：集成 pipeline 完成，不另起同话题补丁。消息副本重戳、原始偏差保留、主机时钟跳变阻断；不使用固定81分钟偏移 |
| 手动静态 odom→base_link→robot_center | 不复制：会把实际里程计伪装为固定基座。使用实测 `/dog_odom` 发布动态 odom→robot_center，外部已有owner则显式配置并核验 |
| base_link→base_footprint 零变换 | 软件全部统一 robot_center，不再需要这个别名；不虚构未测的物理零关系 |
| z=0.4/180° 与站点近似值 | 交接原文明确是“近似外参”，未证明旋转轴/安装高度/足迹。不得自动写入 verified 模板；真实校准仍必需 |
| livox_frame宽高切片、手动SLAM出图 | 已覆盖默认audit预览（无需TF）；完整建图则用校准后的robot_center并过滤真实地面。原始坐标预览出图不等于机体坐标校准/导航安全通过 |
| --plan/--install、七包在现场构建通过 | 记录为用户反馈的旧版本通过，不冒充新版已构建。现有依赖脚本保留；缺RMW不会在安装计划阶段形成循环阻断 |
| Windows文件时间超前、需要touch | **新增**：ZIP统一安全epoch时间并保留shell可执行位；build前只校正本工作空间src/scripts中未来mtime，日志保留原值，不改系统时钟、不改文件内容/地图/原始数据 |
| 四项bug：QoS/site/基座/Nav2 | 前3项已覆盖，补齐具体参数错误信息。Nav2分配边界与资源日志已加；现场bad_alloc根因仍UNKNOWN，不保证已在G1消失 |
| nav2_fixed.yaml/params_file | 本地未收到现场文件，不能声称已审查。本launch始终把本工程Foxy nav2.yaml生成的绝对参数文件传给每个Nav2节点，不加载TurtleBot默认参数 |
| FastDDS A/B 排查 | **新增显式诊断入口** G1_NAV_RMW=rmw_fastrtps_cpp；默认CycloneDDS。所有子节点/两个终端要一致；缺安装库即阻断。不自动安装、不自动切换，真实Foxy/ARM64 A/B未执行 |
| 已列主机IP、SDK路径与已有地图 | 只作用户现场记录；不固化默认IP、不SSH、不覆盖旧工作空间和地图，不连接/迁移到G1 |

## ROS 与 SDK 环境分开

ROS 终端先 `conda deactivate` 直至 CONDA_PREFIX 消失，确认 `python3 --version` 是系统3.8。不要在这两个终端复用 SDK 专用 `export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:...`。环境检查是只读的；不会自动删除库、改服务或清空用户全局环境。

`logs/python-environment-*.json`、`rmw-environment-*.json` 与 launch 的 ROS_ENVIRONMENT 输出包含实际 Python/RMW/依赖库路径。检测到外部DDS并不证明它就是bad_alloc原因，只表明与基线不同、需要单独验证的混用边界。安装在 /usr/local 而没有明确来源标记的DDS仍需人工查构建/包来源，路径审计不等于ABI认证。

## 可选 FastDDS 诊断（未实测）

先用默认CycloneDDS收集日志。若决定在隔离环境A/B，确认机器已有Foxy `rmw_fastrtps_cpp`，不用它替代实测证据，不在本轮自动apt安装。两个终端均显式使用同一选项：

```bash
# 终端1，先只做传感器互通检查
G1_NAV_RMW=rmw_fastrtps_cpp bash scripts/start_stack.sh sensor_check
# 终端2
G1_NAV_RMW=rmw_fastrtps_cpp bash scripts/start_rviz.sh audit
```

完整dry_run仍需要真实site/map，参数与FIELD_FIX_R2.md相同。直接ROS入口支持 `rmw:=rmw_fastrtps_cpp`。FastDDS不应用本工程的CycloneDDS LD_PRELOAD缓解；不要在该终端预先LD_PRELOAD Cyclone库。跨厂商发现/传感器互通、动作服务器、内存与退出行为均需实测，未执行不得称已规避bad_alloc。
