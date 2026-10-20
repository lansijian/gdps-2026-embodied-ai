# Stage 3 notice

正式模板已按用户输入落地Y轴180°/z=0.4粗标定，允许调试启动；不代表精度认证。odom->robot_center默认投影z=0，并有base_link/base_footprint别名。现场精标定仍按下述计算/证据流程替换粗值；新启动边界见STAGE3_DEPLOY.md。

# 倒装 MID-360 标定门禁

真实安装平移 xyz、四元数 xyzw、地面参考高度、点云轴向、机体足迹当前全部 UNKNOWN。模板 null 为故意阻断。第三方 URDF 的 livox_joint 约 X 轴 π 只作候选证据；不能证明本机 mid360_link 与 robot_center 的关系。

1. 机器人保持不动、运动桥禁用，记录原厂 PointCloud2 frame、odom frame/child、实际 URDF 版本、安装照片/厂家尺寸。确认 `/dog_odom` 真正是 odom→robot_center，不能把 pelvis/base_link 当成同一个 frame。本工程全套统一 robot_center，不增加虚构 base_link。
2. 在现有 URDF/实测几何中查明 **robot_center→livox_frame** 的完整刚体变换，包含设备原始轴定义及厂方是否已旋转点云。位置和旋转必须同源。填写 site.calibration 的 translation_xyz 与 quaternion_xyzw（单位米、归一化四元数），并记录 evidence_id。extrinsics.example.yaml 说明变换方向，正式节点只读取 site，避免两套外参冲突。
3. 在 RViz 固定 frame=robot_center 显示 `/g1_nav/cloud_timed`、TF Axes。把真实地板点和已知前/左/上参考物标出；确认 +X 前、+Y 左、+Z 上。检查旋转后的地板在实际机器人参考高度，而不是只凭点云颜色。四元数绕 X/Y/Z 的单元测试只证明代码数学正确，不证明现场选轴正确。
4. 从已标记的地板/障碍点导出 CSV (x,y,z，传感器原始坐标)，运行 `python3 scripts/calibration_check.py --site config/site.yaml --floor-csv floor.csv --obstacle-csv obstacles.csv --output logs/calibration.json`。工具使用 NumPy SVD 报告平面倾角和高度、障碍保留率；平面上法向选正只用于倾角统计，不能独自判断前后轴或倒装方向。CSV 必须是实际选择的地板，工具不自动猜地面。
5. 高程窗口先用于受控可视化调试，不能用宽窗口直接放行。根据真实地面高度、G1 身体/脚步包络、矮障碍和桌沿样本确定 min_height/max_height。正式过滤在 **变换到 robot_center 后** 执行。health.filter 输出有限点、低于窗口候选地面点、保留点与比例；低于窗口不等于语义地面。地面高度和保留率必须现场审核，不能自动认证。
6. 每对 TF 仅一个发布者。可配置 tf.odom_owner/livox_owner 为 project 或 external；external 必须已有经过核验的同一变换。`tf2_echo odom robot_center` 应随真实 pose 动态变化；静止录制也不能以静态 TF 替代。`map→odom` 只由 SLAM 或 AMCL 发布；不发布固定 map→odom。rclcpp monitor 按 child/parent/GID 检测重复发布者和环，一旦发现冲突会锁定 INHIBIT，排障后完整重启。

现场验收必须记录 `tf2_echo`、RViz 截图、地面高度/法向、已知物体坐标、单位、发布者 GID、真实时间戳。当前状态：**BLOCKED_NEEDS_CALIBRATION**。不得为了启动而填写 roll=π、pitch=π 或任意安装高度。

robot_center 不假定在地面上。必须测量 filter.ground_z 与 ground_margin；min_height 可以是负值，但必须高于实测地板加留量。否则会漏掉身体原点下方的矮障碍。Nav2 ObservationBuffer 在 odom/map 中做二次高度筛选，因此不能照搬 robot_center 的高程窗口；本工程以已标定的机体点云预滤为准，代价地图仅保留 ±10m 的有限二次包络，不将其称为新的地面标定。

标定用 `rviz2 -d "$(ros2 pkg prefix g1_nav_config)/share/g1_nav_config/rviz/calibration.rviz"`，固定 frame=robot_center。导航用 g1_nav.rviz，固定 frame=map；2D Pose Estimate 必须在 map 坐标系下设置。点云/scan 显示已明确采用 Best Effort；实际 GUI 显示仍待现场验证。
