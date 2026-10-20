# 现场修订 r2：双终端启动

本轮仅本地修改、测试与打包，没有上传 GitHub、连接 G1 或允许运动。核心仍是官方 Foxy SLAM Toolbox、pointcloud_to_laserscan 与 Nav2 Navfn/DWB。没有 Unitree SDK 写通道；速度仅发布到隔离的 `/g1_nav/cmd_vel_nav2` 和 `/g1_nav/cmd_vel_safe`，机器人不会行走。

## 安装一次，两个终端使用

解压到全新目录，重建并 source 新 install；不要继续加载旧 overlay。新ZIP使用安全epoch文件时间，构建前会仅校正src/scripts未来mtime，不改系统时间或文件内容。示例目录自行对应实际路径：

```bash
cd ~/g1_mid360_foxy_ws_r2
bash scripts/install_dependencies.sh --plan
# 审核精确候选；若确有缺失再安装：
bash scripts/install_dependencies.sh --install
bash scripts/build_on_g1.sh
```

两个ROS终端先 conda deactivate，直至退出Conda并使用系统Python3.8。不要复用SDK终端专用的CycloneDDS0.10.2 LD_LIBRARY_PATH。启动会只读检查Python/混合ROS overlay及实际RMW依赖库，异常即阻断，详见 FIELD_HANDOFF_AUDIT_R2.md。

保留现场已核验的 ROS_DOMAIN_ID/CYCLONEDDS_URI，不猜接口、不改服务/时钟。停止自己上次启动的 fix_stamp.py、TF、scan 转换器和 SLAM/Nav2，避免重复 publisher；不要停原厂驱动/服务。

默认只读检查不需要 site.yaml。终端 1：

```bash
cd ~/g1_mid360_foxy_ws_r2
bash scripts/start_stack.sh sensor_check
```

终端 2：

```bash
cd ~/g1_mid360_foxy_ws_r2
bash scripts/start_rviz.sh audit
```

自动集成原始输入、接收时刻转换、官方 scan、健康诊断。未标定时预览固定在 livox_frame，不保证地面朝向，不发布猜测 TF、不启导航。健康会保持 BLOCKED_NEEDS_CALIBRATION，同时提供实际收包计数。缺少 live/data_source 等字段会合并安全默认值。已有不合法/未验证高度窗口不阻断审计；审计扫描使用固定有界预览窗口，不作为避障标定结果。

日志必须显示 `revision=field-fix-r2`、真实 site 路径、base=robot_center、raw topic 和 QoS。看不到该标记说明仍在用旧版本。raw 输入是 `/utlidar/cloud_livox_mid360`，`/g1_nav/cloud_timed` 是内部输出，不需要手工喂它。

## 完整避障 dry-run，仍为两个终端

将已实测的参数迁入新模板；不填写猜测值：

```bash
mkdir -p config
cp src/g1_nav_config/config/site.example.yaml config/site.yaml
# 填写真实 calibration/filter/timing/robot 和证据；live 保持禁止。
# 接收时刻策略：timing.strategy=receive_time，receipt_time_acknowledged=true。
```

时间策略边界见 TIME_SYNC.md。真实外参、过滤参数、时间适用性与足迹不明确时完整导航仍阻断。

终端 1（使用你们已保存的真实地图）：

```bash
cd ~/g1_mid360_foxy_ws_r2
bash scripts/start_stack.sh dry_run "$PWD/config/site.yaml" /home/unitree/maps/site.yaml
```

终端 2：

```bash
cd ~/g1_mid360_foxy_ws_r2
bash scripts/start_rviz.sh navigation
```

传感器、stamp、TF、scan、健康门禁、map_server/AMCL、Navfn/DWB、SDK-free bridge 均由一个 launch 管理。连续30秒传感器/TF/时间健康后才启动下游，60秒不满足则退出。RViz 用 2D Pose Estimate 设置真实初始位姿，然后 Nav2 Goal 检查路径与预览速度。缺少 map→odom、有效地图、生命周期或遇动态障碍时预览归零；任何时候都不驱动真机。

没有地图时，终端1先用 `bash scripts/start_stack.sh mapping "$PWD/config/site.yaml"`，终端2仍用 navigation；用原有 save_map.sh 保存后退出 mapping，再切换 dry_run。不伪造地图/初始位姿，不同时启 SLAM 与 AMCL。切换前可从 RViz 终端执行 `ros2 run g1_nav_bringup shutdown` 完成 Nav2 生命周期清理，再在终端1 Ctrl-C。

等价的完整 ROS 启动入口（不含包装脚本的资源监控）：

```bash
source /opt/ros/foxy/setup.bash
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 launch g1_nav_bringup navigation_dryrun.launch.py site:="$PWD/config/site.yaml" map:=/home/unitree/maps/site.yaml
```

## bad_alloc 的实际处理范围

本地没有现场 nav2_fixed.yaml，未宣称审查那份文件。已有局部代价地图3×3m、0.05m，仅3600 cells，并非巨大地图。r2 全局初始值显式20×20m、0.05m、160000 cells；StaticLayer 后续按真实地图调整。

启动 C++ 前检查真实 PGM/PNG header：每边≤4096像素、总≤4000000 cells、文件≤64MiB、分辨率0.02–0.2m、物理边长≤200m。局部网格≤250000 cells。超限拒绝，不偷偷修改真实地图。坏布局/超大点云同样拒绝。scan 角步长限制在0.003–0.05rad，避免异常大扫描分配；高度错误报告具体不等式，scan_time 允许0.05–0.3s。所有 use_sim_time=false；DWB 采样20×20降至10×10，关闭轨迹 debug/Groot。

SLAM/AMCL/costmap/BT/recoveries 统一使用实机 robot_center，消除 base_footprint 依赖；没有添加未经测量的 base_link→base_footprint 零变换。不要绕过本入口加载 TurtleBot 官方默认配置。

保留 CycloneDDS，统一子进程 RMW 与已安装库，保留原有卸载缓解，不改 Cyclone XML/内存池、不切自写导航。本轮没有证明现场 bad_alloc 的根因，也没有证明在 G1 已消失。12G 主机空闲不能排除 cgroup/地址空间限制、尺寸错误、混合版本/DDS 解码异常；已增加显式 G1_NAV_RMW=rmw_fastrtps_cpp 诊断选项（两个终端一致），默认不切换。真实Foxy/ARM64 A/B未执行，步骤见 FIELD_HANDOFF_AUDIT_R2.md。

start_stack 自动保存 `logs/stack-*.log` 与 `logs/resources-*.jsonl`：meminfo、进程限制、cgroup v1/v2 内存/事件、本工程子进程 RSS、退出码、可读取的内核日志。dmesg 无权限会记录 UNAVAILABLE，不使用 sudo。RSS 总和会重复计算共享页；连续3次超过4096MiB仅关闭本次 launch 进程组，保留日志，不终止原厂进程。它不能保证拦截瞬时大分配，已知输入由前置尺寸门禁保护。下游节点意外退出也会关闭该 launch。

如现场仍崩溃，需保留这两类日志、实际地图 YAML/image、nav2_fixed.yaml、`dpkg-query -W 'ros-foxy-*'` 和同域其他 ROS 参与者的版本信息，再根据异常栈/cgroup事件判断。

## 隔离 Foxy 测试

本轮实际结果与未验证项见 VERIFICATION_REPORT.md。新版 ARM64 colcon/DDS/完整 Nav2/RViz 尚未在本地执行。随包提供真实通信回归，仅在与机器人隔离的 Foxy 环境使用：

```bash
export ROS_DOMAIN_ID=87 G1_NAV_TEST_ONLY=1
bash scripts/test_on_foxy.sh
```

该脚本发布 SYNTHETIC_TEST 数据，禁止在生产机器人域使用。覆盖实际 BE/RELIABLE 两种原始发布端→集成接收时刻转换→官方 /scan，及原有 SLAM/保存地图/AMCL/Nav2/动态故障注入。不能将尚未执行写成 passed。
