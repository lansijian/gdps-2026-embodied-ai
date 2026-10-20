# 时间与 QoS 验证

历史约 +4883 秒不是校正参数。安装 ntpdate 不证明同步成功。本工程不改系统时钟、不配置 NTP、不运行 ntpdate/date -s/timedatectl set-time，不改变原话题。

构建后执行：

```bash
ros2 run g1_nav_perception clock_preflight --duration 30 --output logs/clock-preflight.json
```

报告 CLOCK_REALTIME(time.time)、接收 monotonic、各 header stamp 相对接收时间偏差的 min/max/P50/P95、30 秒频率、跳变、乱序、无效数与 publisher QoS/GID。BEST_EFFORT sensor_data 兼容现有雷达/odom publisher，active scan subscriber 触发官方转换器。Foxy 不提供每个传感器包的序号；无法精确辨别 DDS 丢帧与设备未发送，报告的速率/间隔用于诊断，不能声称“丢帧数=0”。

必须核实雷达、odom、IMU 时钟的来源、ROS use_sim_time、系统 epoch 与网络延迟。恒定偏差不等于已经知道原因，三路偏差分布也不能证明采样级同步。先做非侵入排查；任何系统时间/NTP 改动另行现场批准。消息偏差超过 0.3s 过期或超过未来 0.03s 默认阻断；不能扩大到 5 秒掩盖错误。参数有硬上限。

当前只实现 preserve 策略：验证原 stamp 后原样发布 `/g1_nav/cloud_timed`、`/g1_nav/odom`、`/g1_nav/imu`，TF 使用同一 odom header，点云原始数据与话题不修改。任何 fixed_offset/receive_time/auto 策略都会明确 BLOCKED。因为没有真实时钟来源和传输延迟证据，本版本不实现可能掩盖同步错误的重戳。若现场证明设备时间不可信，需要独立设计和验证三源一致的时间映射、漂移/单调性与运动补偿，再审查下一版。

所有节点 use_sim_time=false。SYNTHETIC_TEST CI 生成当前墙钟时间，使用独立 domain=87；不将仿真当作真实传感器证据。RECORDED_REPLAY 需要显式隔离测试开关，本版本不支持直接用旧 bag stamp 冒充当前时间；必须保留原 bag 哈希，专门验证回放时间策略后再接入。

health 中 offset P95 为 header→当前接收时刻的表观延迟，scan 的 P95 反映其链路延迟；只有时钟来源已确认时才可解释为端到端延迟。30 秒门禁还核验频率与窗口内无无效时间消息。处理线程阻塞/丢数据导致 heartbeat 过期时独立 dry bridge 输出零。该线程隔离不能作为真实电机的独立硬件停止证明。
