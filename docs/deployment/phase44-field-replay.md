# Phase 4.4｜独立只读采集与回放操作单

本包仅订阅、保存证据、分析与 Dry-run。没有运动 SDK、发布器、服务调用、LowCmd/HandCmd/SportCmd/SetVelocity 入口。不要使用 Phase 4.1 旧 ZIP；不要覆盖现有导航目录。Windows 不需要 ROS，也不直接反序列化 ROS 消息。

## Windows 打包与校验

在本仓库 PowerShell：

```powershell
Set-Location E:\GDPS\competition
python -m pytest -q
.\scripts\g1\package_phase44.ps1 -Out .\dist\gdps-s05-phase44-readonly.zip
Get-FileHash .\dist\gdps-s05-phase44-readonly.zip -Algorithm SHA256
Get-Content .\dist\gdps-s05-phase44-readonly.zip.sha256
```

白名单在 `scripts/g1/package_phase44.py`：只收录本轮采集/回放脚本、所需 gdps_qi 模块、shared/navigation 的纯感知模块及操作文档；不递归收录整个仓库。ZIP 使用 LF/无 BOM，带逐文件 MANIFEST.sha256 和 BUNDLE.json。已有 ZIP 拒绝覆盖，复打包请换输出文件名。生成后把 ZIP 和 `.zip.sha256` 人工拷到 G1 的同一目录。

## G1 Linux 独立解压与依赖检测

```bash
cd ~/Downloads  # 改为实际接收文件目录
sha256sum -c gdps-s05-phase44-readonly.zip.sha256
FIELD_ROOT="$HOME/gdps-phase44-$(date +%Y%m%d-%H%M%S)"
mkdir "$FIELD_ROOT"
unzip -n gdps-s05-phase44-readonly.zip -d "$FIELD_ROOT"
cd "$FIELD_ROOT"
sha256sum -c MANIFEST.sha256
source /opt/ros/foxy/setup.bash
python3 scripts/g1/check_field_dependencies.py > dependencies.json
cat dependencies.json
ros2 bag record --help
ros2 bag play --help
ros2 topic list -t > topic_inventory.txt
ros2 pkg prefix tf2_ros
ros2 pkg prefix message_filters
ros2 pkg prefix cv_bridge
ros2 pkg prefix image_geometry
ros2 pkg prefix pointcloud_to_laserscan  # 缺失只记录，不安装
```

依赖：Ubuntu 20.04 / ROS2 Foxy，系统 Python3（通常 3.8）；numpy、OpenCV(cv2)、PyYAML、rclpy、sensor_msgs、nav_msgs、tf2_msgs、sensor_msgs_py、rosidl_runtime_py、message_filters、cv_bridge、image_geometry、tf2_ros，rosbag2 SQLite 存储/录放 CLI。工具不运行 apt/pip，不升级 ROS，不改设备服务。Windows 离线分析只需 numpy 与 OpenCV；pytest 用于开发测试。

缺依赖时先保存探测报告。不要为了本包替换机载已有 Livox/ROS。若没有 rclpy 或消息类型支持，应在 G1 导出后再拷回 Windows。

## 审核 Topic 后执行 Gate A–E

先查看实际类型和 QoS；以下路径是占位变量，不能直接照抄假定存在：

```bash
RGB=/现场实际的RGB话题
DEPTH=/现场实际的已注册Depth话题
INFO=/现场实际的RGB相机参数话题
PC=/utlidar/cloud_livox_mid360
SCAN=/scan
ODOM=/dog_odom
ros2 topic info "$RGB" --verbose
ros2 topic info "$DEPTH" --verbose
ros2 topic info "$INFO" --verbose
ros2 topic info "$PC" --verbose
ros2 topic info "$ODOM" --verbose
```

PC 必须是 `sensor_msgs/msg/PointCloud2`，不能把 Livox CustomMsg 当 PointCloud2。CameraInfo 必须属于所选 RGB 图像；Depth 必须有驱动/标定资料证明已注册到 RGB。不同 frame 或仅分辨率一致均不足以证明注册。

```bash
python3 scripts/g1/field_gates_centering.py --live --gate all \
  --rgb-topic "$RGB" --depth-topic "$DEPTH" --camera-info-topic "$INFO" \
  --pc-topic "$PC" --scan-topic "$SCAN" --odom-topic "$ODOM" \
  --registered-depth --registration-source '现场驱动注册配置及标定记录的实际引用' \
  --depth-scale 0.001 --timeout 20 --max-frames 60 --sample-period 0.5 \
  --base-frame robot_center --camera-frame camera_color_optical_frame \
  --lidar-frame livox_frame --out-dir field_capture
```

`--depth-scale 0.001` 仅在 16UC1 单位已确认是毫米时保留；否则删除，未知单位不会被换算。32FC1 按 ROS 米制读取。frame 参数也须根据 TF 实际名称调整。无人工指定时只会采用唯一无歧义的相机 Topic，不会猜多个候选中的一个。

任意 Gate 独立执行，将 `--gate all` 换成 `--gate A`、`B`、`C`、`D` 或 `E`。`--live` 表示订阅实时数据，**不授权运动**。默认 10s，硬上限 120s；图像默认最多 20 组，最大 200 组。保存原始/校正后 RGB、原始/米制 Depth NPY、PNG、原始 K/D/R/P、各自 header stamp、消息计数和 QoS。

| Gate | 实际行为 | UNKNOWN / 拒绝条件 |
|---|---|---|
| A | 三路 header 同步；有效帧数、时间差、帧频、深度有效率、真实有限图像样本 | 缺数据/参数/单位/注册来源，时差超 50ms 或分辨率不匹配 |
| B | MID-360 点云与 Scan 各自四扇区距离/有效点数，header 时间/频率/间隔/倒序，odom 前后差 | 缺流、无有效点、odom 不足或 frame 改变。方向仍在传感器 frame，外参未验证不能冒充机体方向 |
| C | 保存图像的唯一 Hough 圆候选像素偏差、ROI 中位深度/标准差、重复性统计 | 无唯一候选、内参缺失、不可靠深度；圆候选不等于已识别样品 ID |
| D | 真实/回放 3D 目标在左右 SE(2) 候选位移下重投影，输出方向、误差预测和 Dry-run 速度数字 | 无可靠深度/真实 TF 则 UNKNOWN。命令永远 execute_allowed=false，不判定障碍授权 |
| E | 订阅现有 /tf 与 /tf_static；官方 tf2 查询所见边及 base-camera/lidar/odom 链；逐帧相机 TF 可用率、缺失、动态 age/stale | 缺链或过期，禁止 identity 填充；静态链可零时间戳，动态链不能冒充静态 |

实时数据标 REAL_SENSOR，提取/重放标 RECORDED_REPLAY，无输入模板标 SYNTHETIC_TEST。脚本永不自动写 FIELD_VERIFIED。部分 Gate 失败独立保留；任何 FAIL/UNKNOWN 使 CLI 非零退出，不能把退出码忽略当通过。

## 官方 rosbag2 录制（先预览，再人工执行）

```bash
export RGB_TOPIC="$RGB" DEPTH_TOPIC="$DEPTH" CAMERA_INFO_TOPIC="$INFO"
export PC_TOPIC="$PC" SCAN_TOPIC="$SCAN" ODOM_TOPIC="$ODOM"
export OUT="$HOME/gdps_bags/static_$(date +%Y%m%d_%H%M%S)"
export DURATION=20
bash scripts/g1/record_field_bag.sh
# 人工核对实际存在的话题、类型、QoS、可用容量和打印列表后：
bash scripts/g1/record_field_bag.sh --execute-reviewed
```

只录存在且为白名单传感器类型的 Topic，JointState 存在才加入；/tf_static 使用 transient_local QoS override。单次 1–60s；开始及每秒检查磁盘剩余量，默认保留 2GiB，结束发送 SIGINT 给本次 recorder 并检查 metadata。持续大点云可能短时高速写盘，因此先录 5s 测大小，再决定 20s；保留 metadata.yaml、所有分片和原始 header 时间。不会启动 DDS 运动接口或修改服务。

## G1 提取，再到 Windows 使用同一数据

```bash
python3 scripts/g1/replay_field_extract.py "$OUT" \
  --rgb-topic "$RGB" --depth-topic "$DEPTH" --camera-info-topic "$INFO" \
  --pc-topic "$PC" --scan-topic "$SCAN" --odom-topic "$ODOM" \
  --registered-depth --registration-source '现场真实注册记录' --depth-scale 0.001 \
  --max-frames 60 --sample-period 0.5 --out-dir extracted_static
python3 scripts/g1/field_gates_centering.py --evidence extracted_static/evidence.json --gate all
```

Foxy 原始 SQLite 分片只读打开，按录包 timestamp 合并消息，ROS CDR 由 G1 的 `rclpy.serialization.deserialize_message` 及已安装消息定义解析；不自研录包格式。导出 header 时间、bag 纳秒时间、metadata/QoS，默认最多扫描 200000 条，截断会报告并非零退出。保留整个原包；JSON/NPY 是派生分析资料。提取不会发布任何消息，也无需启动 rosbag play。

如需标准 ROS 重放做现场交叉检查，在隔离 ROS_DOMAIN_ID 的两个终端用同一个值，避免现有运动消费者接收到回放消息：

```bash
# 终端1，独立诊断域；此域不启动任何机器人控制节点
export ROS_DOMAIN_ID=88
python3 scripts/g1/field_gates_centering.py --live --recorded-replay --gate all \
  --rgb-topic "$RGB" --depth-topic "$DEPTH" --camera-info-topic "$INFO" \
  --registered-depth --registration-source '原录包注册记录' --depth-scale 0.001 \
  --timeout 30 --max-frames 60 --out-dir replay_capture
# 终端2，同一个独立诊断域；在终端1等待订阅期间执行
export ROS_DOMAIN_ID=88
ros2 bag play "$OUT"
```

只使用 Foxy `ros2 bag play` 的实际 API，不依赖新版 --clock。实时订阅回放的 TF 时效参考会按回放数据时间；原始提取是推荐路径。隔离域值需人工确认未被现场其他控制节点使用。

拷回整个 `extracted_static/` 后，Windows：

```powershell
python scripts/g1/field_gates_centering.py --evidence E:\现场数据\extracted_static\evidence.json --gate all
```

同一段数据可用于深度重复性、左右像素/光学方向、四扇区距离、TF 可用率/时延/缺失、视觉居中 Dry-run，以及按消息时间 100ms 内匹配 odom 的前后像素误差/位移比较。重复性只在同一目标静止时有意义；Hough 圆候选不提供可靠跟踪 ID，前后比较必须人工复核保存图像是同一目标，报告明确标 UNVERIFIED，不能据此授权抓取。

## 抓取与腰部边界

本轮不执行抓取或腰部动作。控制器用 monotonic 限时，观测次数与 `moved_since_last` 确认次数分开；SAFE_HOLD 必须显式 reset 才可退出。三次连续观测必须有相同非空 object_id 和递增帧时间；建议次数不算移动次数。腰部只给不可执行预览提示；没有可信关节、URDF FK、方向限制和高层接口不计算可执行腰部角度。

ManipulationReadyGate 额外要求带来源文件 SHA256 的 evidence bundle、真实标定 YAML、TCP 测量 YAML、相同机器人 URDF 与工作空间检查资料、G1_URDF_VERIFIED 的 FK provider、逐链 TF 时间证据、可靠深度和实际 TCP FK 残差。布尔量全 True 也不足以通过。evidence JSON 需有 data_source=REAL_SENSOR、calibration_id、stamp，以及 calibration/tcp/urdf/workspace_check 四个 `{path,sha256}`；文件由现场审核产生，不提供假定已标定模板。TCP YAML 包含 source、calibration_id、T_wrist_tcp；workspace_check 包含 backend、reachable、target_base、fk_residual_m、urdf_sha256、tcp_sha256、joint_positions、side、base_frame。外部检查资料不能取代实际 verified URDF FK 复核。

## 最短现场顺序

1. 独立目录校验 ZIP/逐文件 hash，保存依赖探测、Topic 类型/QoS、真实 frame 名。
2. 机器人静止运行 A、B、E；若注册、单位或 TF 缺失，保留 UNKNOWN 和原始消息证据，不补假值。
3. 先录 5s 检查体积，再录 20s 同一静止目标；G1 提取，Windows 重跑 A–E，检查真实样图与深度重复性。
4. 将同一目标放在视野左侧、右侧，分别录短包，人工核对 D 重投影方向；无需机器人运动。
5. 若已有经过独立授权采得的移动前后包，做 odom/像素误差比较。本轮不触发移动；没有这些数据则前后实机改善保持 UNVERIFIED。

还需现场资料：实际 RGB/Depth/CameraInfo Topic 与尺度/注册来源、MID-360 frame/高度带、完整动态及静态 TF、统一时钟、机器人型号/URDF、可信关节姿态、TCP 和工作台标定、工作空间核查，以及具有相同 target_id 的前后数据。没有提供真实 bag 时，本地回归通过不等于现场通过。
