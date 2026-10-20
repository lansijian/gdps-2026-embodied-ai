# 时间与 QoS 验证

历史约 +4883 秒不是校正参数。安装 ntpdate 不证明同步成功。本工程不改系统时钟、不配置 NTP、不运行 ntpdate/date -s/timedatectl set-time，不改变原话题。

构建后执行：

```bash
ros2 run g1_nav_perception clock_preflight --duration 30 --output logs/clock-preflight.json
```

报告 CLOCK_REALTIME(time.time)、接收 monotonic、各 header stamp 相对接收时间偏差的 min/max/P50/P95、30 秒频率、跳变、乱序、无效数与 publisher QoS/GID。BEST_EFFORT sensor_data 兼容现有雷达/odom publisher，active scan subscriber 触发官方转换器。Foxy 不提供每个传感器包的序号；无法精确辨别 DDS 丢帧与设备未发送，报告的速率/间隔用于诊断，不能声称“丢帧数=0”。

必须核实雷达、odom、IMU 时钟的来源、ROS use_sim_time、系统 epoch 与网络延迟。恒定偏差不等于已经知道原因，三路偏差分布也不能证明采样级同步。先做非侵入排查；任何系统时间/NTP 改动另行现场批准。消息偏差超过 0.3s 过期或超过未来 0.03s 默认阻断；不能扩大到 5 秒掩盖错误。参数有硬上限。

r2 支持 preserve 与显式 receive_time 两种 dry-run 策略。preserve 验证原 stamp 后原样发布。receive_time 必须配置 receipt_time_acknowledged=true：在 cloud/odom/IMU 回调入口采集主机墙钟，修改消息副本的 header，保留原始消息及话题。独立 raw_streams 保留原始时间偏差、乱序和跳变；sampling_sync_verified 始终 false。主机墙钟与 monotonic 增量差超过 jump_s 或倒退时，粘性阻断全部接收时刻输出，须排查后重启。fixed_offset/auto 仍拒绝。

无参数 sensor_check 自动加载 sensor_audit.yaml，采用接收时刻且不设置任何 verified，预览扫描保持 livox_frame，不造外参、不启 SLAM/Nav2。完整导航仍要求外参、时间、过滤参数和环境的真实证据。该策略下 timing.verified=true 只能表示现场审核了输入排队/传输延迟和三源对齐的 dry-run 适用性，不能代表采样同步。无法从错误 header 推断设备/网络滞留时间，不做 deskew；不确定时保持未验证并阻止导航。

接收时刻模式的规范化 stream offset 只反映本进程之后的延迟；原始 offset 在 raw_streams 中。原始 clock_preflight 遇到坏 stamp 仍应失败，不能因预览能显示就宣称同步通过。sensor inputs 使用明确 BEST_EFFORT KEEP_LAST depth=5，兼容 BEST_EFFORT 与 RELIABLE 发布端；内部 cloud_timed 使用 RELIABLE depth=2，兼容两类订阅。TF 静态订阅保留可靠 TRANSIENT_LOCAL，不能一律改为传感器 QoS。兼容规则见 https://docs.ros.org/en/foxy/Concepts/About-Quality-of-Service-Settings.html 。

所有节点 use_sim_time=false。SYNTHETIC_TEST CI 生成当前墙钟时间，使用独立 domain=87；不将仿真当作真实传感器证据。RECORDED_REPLAY 需要显式隔离测试开关，本版本不支持直接用旧 bag stamp 冒充当前时间；必须保留原 bag 哈希，专门验证回放时间策略后再接入。

health 中 offset P95 为 header→当前接收时刻的表观延迟，scan 的 P95 反映其链路延迟；只有时钟来源已确认时才可解释为端到端延迟。30 秒门禁还核验频率与窗口内无无效时间消息。处理线程阻塞/丢数据导致 heartbeat 过期时独立 dry bridge 输出零。该线程隔离不能作为真实电机的独立硬件停止证明。
