# 明日 G1 现场第一轮逐模块测试顺序（建议）

> 禁止未授权：臂/手 DDS 写、行走 live、离心机启动、厂商服务改动。

1. **网络与仓库** — SSH `unitree@192.168.123.164`，`git pull` 功能分支，`colcon` 仅导航包（若需）。
2. **只读探测** — `python3 scripts/g1/qi_hardware_probe_readonly.py --ros2`，保存 JSON；补全 `hardware_interface_matrix.md`。
3. **相机** — `lsusb`、`v4l2-ctl`、teleimager/厂商图像服务；记录分辨率、CameraInfo、Depth 有无。
4. **Dex3 只读** — SDK2 Python 订阅 `HandState`（不写 `HandCmd`）。
5. **臂状态只读** — 高层 state 示例只订阅；确认与行走控制 ownership。
6. **标定** — 工位 `table_frame`：允许则棋盘/AprilTag；否则托盘/试管架几何；写 `workstation_calib.yaml`，`calibrated: true`。
7. **TF 链** — 腰关节变化前后，相机投影点是否一致（静态工位重投影误差）。
8. **P1 空载** — `GDPS_G1_LIVE` 未设，运行质检 mission dry-run；仅日志与图像证据。
9. **P1 授权接触**（人工）— 单片 01 预抓取→复核→夹持；记录失败码。
10. **P2 单管** — 双手旋盖小角度增量；瓶身固定策略现场确认。
11. **P3 逻辑** — 不配平/未封管必须 SAFE_HOLD；**不启动**离心机直至裁判与设备说明允许。
12. **P5/P6** — 图像证据路径、pending 报告 JSON、禁止伪造 ACK。
