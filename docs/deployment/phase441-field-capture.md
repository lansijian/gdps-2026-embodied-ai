# Phase 4.4.1｜RGB 独立采集与原始点云兼容性

基线 ee4910927081a3c1e2945b097110420c10ea0bf9。本轮只修复采集兼容性、录包退出和 P6 本地保存/上传语义，不扩展导航、传感器或机械动作。**诊断脚本的 --live 只表示订阅真实消息，不是 LIVE 运动开关。** 不安装依赖、不改服务、不启动任何运动节点。

## 本轮状态含义

- RGB 到达即按数量/采样间隔上限导出原始（未校正）图像 `raw_rgb_*.npy`、`raw_rgb_*.png`，保留 RGB header stamp、bag timestamp（回放时）、分辨率、原始 encoding 与保存的 rgb8 encoding。无需 Depth、CameraInfo 或同步器成功。原始图不被校正图覆盖。
- 有匹配 RGB frame/分辨率且内参有效的 CameraInfo 时，可基于原始 K 做 2D 像素检测；CameraInfo 到达前后顺序、与 RGB 时间不同步均不会丢弃原图。保留 CameraInfo 实际时间和 camera_info_time_matched，不能拿 2D 可用性当作 3D 可用性。
- 三路真实 header 的 RGB-D 同步仍由 Foxy message_filters.ApproximateTimeSynchronizer 完成，只增强已保存的那一帧，不重复计数。Depth 缺失、时间超差、注册来源未知或尺度未知时，3D 保持 UNKNOWN，p_camera/p_base 不生成有效值；Gate D 不生成可执行计划。
- Gate A 的 status/valid_rgb_frames/rgb_status 表示原始 RGB 采集结果；rgbd_status/valid_frames 单独表示可靠 RGB-D。Gate C 明确分开 pixel_2d_status 与 localization_3d_status。
- Gate B 的 streams.pc / scan / odom 分别含 status、errors、采样统计和实际样本。status=LIDAR 原始采集主状态；LIDAR_RAW_OK=true 不代表 Scan/Odom 也健康，完整状态看 all_streams_ok。缺 /scan 记为 scan_status=UNKNOWN，不否定 MID-360 原始点云成果。四方向距离仍是样本 frame_id 下的方向，body_directions_calibrated 永远 false。
- 所有 Gate 仍为 live_motion=false、field_verified=false；Dry-run 的 execute_allowed=false。局部 OK 不授权移动或抓取。
- P6 本地保存完成返回 mission_complete_upload_pending；local_report_saved=true、upload_status=PENDING。不会从本地写入或普通 success=True 推断服务器 ACK。本轮不调用上传服务器。

## Windows：打包、哈希和上传命令

以下地址沿用仓库部署文档的现场示例 **unitree@192.168.123.164**，本轮未连接 G1 核实。若现场连接地址不同，只替换 `$G1`。这些是供人工执行的命令；本轮不会自动上传或部署到 G1。

```powershell
Set-Location E:\GDPS\competition
.\scripts\g1\package_phase44.ps1 -Out .\dist\gdps-s05-phase441-readonly.zip
Get-FileHash .\dist\gdps-s05-phase441-readonly.zip -Algorithm SHA256
Get-Content .\dist\gdps-s05-phase441-readonly.zip.sha256

$G1 = "unitree@192.168.123.164"
ssh $G1 'mkdir -p /home/unitree/gdps-upload-phase441'
scp .\dist\gdps-s05-phase441-readonly.zip .\dist\gdps-s05-phase441-readonly.zip.sha256 "${G1}:/home/unitree/gdps-upload-phase441/"
```

最终 ZIP 已生成时直接执行校验/上传部分；打包器拒绝覆盖旧文件，不要删除旧包后盲目重打。

## G1 Linux：独立目录、只读检查和采集

```bash
cd /home/unitree/gdps-upload-phase441
sha256sum -c gdps-s05-phase441-readonly.zip.sha256
FIELD_ROOT="$(mktemp -d /home/unitree/gdps-phase441-XXXXXX)"
unzip -n gdps-s05-phase441-readonly.zip -d "$FIELD_ROOT"
cd "$FIELD_ROOT"
sha256sum -c MANIFEST.sha256
source /opt/ros/foxy/setup.bash
python3 scripts/g1/check_field_dependencies.py > dependencies.json
cat dependencies.json
ros2 topic list -t > topic_inventory.txt
cat topic_inventory.txt
ros2 bag record --help
```

缺依赖仅记录，禁止自动 apt/pip 安装、升级 ROS 或变更 Livox/导航服务。不要解压进已有导航目录。

先执行下面命令；相机 Topic 仅在唯一无歧义时自动发现。若实际存在多个 RGB Image Topic，人工从 topic_inventory.txt 选择正确的 `sensor_msgs/msg/Image`，追加 `--rgb-topic /真实话题`，CameraInfo 同理。不能把 `/frontvideostream` 未经类型确认当作 ROS Image。

```bash
CAPTURE_OUT="$(mktemp -d "$FIELD_ROOT/capture-XXXXXX")"
python3 scripts/g1/field_gates_centering.py --live --gate all \
  --pc-topic /utlidar/cloud_livox_mid360 --scan-topic /scan --odom-topic /dog_odom \
  --timeout 10 --max-frames 20 --sample-period 0.5 --out-dir "$CAPTURE_OUT"
printf 'Evidence directory: %s\n' "$CAPTURE_OUT"
```

本轮命令**不加** `--registered-depth`，未知注册不能生成可靠 3D。RGB 不存在时 A/C/D 保持 UNKNOWN；只有 RGB 时 A 可成功、C 取决于内参和目标检测、D 保持 UNKNOWN；/scan 不存在时 B 的 raw LiDAR 可以独立成功。all 命令遇到任意 UNKNOWN 返回 1 是预期的部分可用状态，请读取 gates.json 各分项，不能等同“所有数据采集失败”。

只检查 MID-360 原始点云，可单独运行 `--gate B`（指定新的空 --out-dir）；它仍会输出缺 Scan/Odom 的明确状态，LIDAR_RAW_OK 不代表完整导航链通过。没有任何相机数据时不会生成 Mock 图像。

## 可选：人工审核后录制已有 Topic，/scan 可缺失

```bash
# 唯一 RGB/Info/Depth 话题尚未确认时，留空；仅录实际存在且类型受支持的话题。
export RGB_TOPIC='' DEPTH_TOPIC='' CAMERA_INFO_TOPIC=''
export PC_TOPIC=/utlidar/cloud_livox_mid360 SCAN_TOPIC=/scan ODOM_TOPIC=/dog_odom
export OUT="$HOME/gdps_bags/phase441_$(date +%Y%m%d_%H%M%S)"
export DURATION=5
bash scripts/g1/record_field_bag.sh
# 确认打印的列表、QoS、磁盘容量后，才人工执行：
bash scripts/g1/record_field_bag.sh --execute-reviewed
```

要录 RGB 时，只把 RGB_TOPIC 改为已核验的真实 Image 话题即可，不要求 Depth/CameraInfo 同时存在。录制使用 Foxy 的 `ros2 bag record --qos-profile-overrides-path ... -o ... <实际话题列表>`；缺 /scan 直接排除。默认预览，不自动开始。单次 1–60s、磁盘余量检查保持不变。

正常结束向本次 recorder 发 SIGINT，最多等 10s 写回 metadata；必要时仅终止本次子进程并报告失败。INT/TERM 触发 EXIT 清理，清理一次 recorder 并删除临时 QoS 文件，不继续执行“录制成功”分支。metadata 缺失、异常退出或强制终止均不能报告成功。本地隔离模拟命令验证不等于 G1 rosbag2 已实测。

## 提取与回传（不启动机器人控制）

在 G1 运行，按原包实际 Topic 填写 RGB_TOPIC 等变量；缺 Depth/Info 时传空字符串：

```bash
EXTRACT_OUT="$(mktemp -d "$FIELD_ROOT/extracted-XXXXXX")"
python3 scripts/g1/replay_field_extract.py "$OUT" \
  --rgb-topic "$RGB_TOPIC" --depth-topic "$DEPTH_TOPIC" --camera-info-topic "$CAMERA_INFO_TOPIC" \
  --pc-topic "$PC_TOPIC" --scan-topic "$SCAN_TOPIC" --odom-topic "$ODOM_TOPIC" \
  --max-frames 20 --out-dir "$EXTRACT_OUT"
python3 scripts/g1/field_gates_centering.py --evidence "$EXTRACT_OUT/evidence.json" --gate all
printf 'Copy this directory back to Windows: %s\n' "$EXTRACT_OUT"
```

保留原 bag 的 metadata.yaml/全部 db3，派生目录整体拷回 Windows，之后执行：

```powershell
# 将远端路径改为上面打印的准确 EXTRACT_OUT；不填写虚构目录。
scp -r "${G1}:/home/unitree/gdps-phase441-实际后缀/extracted-实际后缀" .\dist\
python scripts/g1/field_gates_centering.py --evidence .\dist\extracted-实际后缀\evidence.json --gate all
```

本轮交付后停止编码，等待真实 G1 的 RGB/CameraInfo、MID-360/odom、TF 与 rosbag2/派生证据。不会因部分 OK 解锁 LIVE，也不会修改机载服务、启动步行或机械臂。

## 本轮本地验证记录

- `python -m pytest -q -rs --junitxml=dist/phase441-tests.xml`：**146 passed, 4 skipped**。
- 新增 10 项采集/录包兼容性用例通过；原有六轮任务流测试补充 local_report_saved 与 upload_status=PENDING 断言。
- 4 项跳过为 Windows 无 rclpy 的 ROS/Foxy 合约测试，以及 3 项无 Pinocchio 的运动学验证，不能算现场通过。
- 录包用例使用隔离的 SYNTHETIC_TEST ROS 命令，验证缺 /scan 的选择、预览不启动 recorder、正常 SIGINT、TERM 清理和异常退出；不运行真实 rosbag2，不连接 G1。
- 录制脚本 `bash -n`、白名单 ZIP 清单/逐文件 hash、Python 3.8 AST 语法与独立解压运行检查通过。Foxy record 参数已对照本地保存的 ros2/rosbag2 foxy 源码（77f5a51b4d5cd70ea6a78d53cffe964e3b9afaf7）确认；机载运行仍未验证。
- 既有现场文档/研究 ZIP 保留；未修改导航、机械动作、机载服务、模型或 LIVE 门禁。交付后停止编码，等待真实数据。
