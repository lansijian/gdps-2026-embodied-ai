# Field fix r2 verification — 2026-10-20

本报告只描述 r2 当前修订。没有上传 GitHub、连接 G1、修改系统时间/原厂服务或发出机器人运动命令。SDK 写通道继续缺失，LIVE 不可启用。原始工作树和 Stage 3 工作树没有改动。

## 本轮已执行

- Windows Python 3.11.4：`python -m pytest tests/test_contracts.py tests/test_scripts.py tests/test_field_fixes.py -q`，**112 passed / 0 failed**。前54项原有合同/打包检查，新增58项现场修复回归。
- 既有仓库 `python -m pytest tests/robot_control tests/navigation -q`：**104 passed / 0 failed**。合计216项通过。
- 9个 Shell 文件经过实际 Git Bash `bash -n`，全部退出0；部署 PowerShell 经过实际 AST parser，无错误。Shell 源码使用 LF。`git diff --check` 通过。
- Python3.8 grammar、7个包 manifest、YAML/XML 与 SDK 无写通道检查随合同测试执行；语法兼容不等于 Python3.8 运行/colcon 构建通过。
- 回归覆盖安全默认值合并（不擦除显式 allow_live=true）、未知外参继续拦截导航、接收时刻明确确认、原始消息不变、原始坏时间诊断保留、主机时钟跳变粘性阻断、QoS对象配置、畸形/大点云拒绝、PGM/PNG超大头/极端分辨率拒绝、launch 自动转换/scan 接线、robot_center 统一、命令隔离、资源监控仅信号自己的进程组。
- ROS API doubles 用于 portable pytest 的回调/launch/QoS接线测试，**没有模拟出真实 DDS 传输证明**。资源监督的进程 API doubles 也不是 Linux 实机监控验收。新增Conda/Python ABI/混合ROS overlay阻断、SDK DDS解析路径检查、FastDDS显式接线及无Cyclone预载、未来mtime修复范围、ZIP epoch/执行权限回归；实际CLI在当前Windows Conda解释器下按预期返回NATIVE_PYTHON_REQUIRED，未初始化ROS。
- 新 ZIP/tar.gz 应由 package_workspace.py 生成，逐文件 manifest 校验后交付；实际 archive SHA256 与本地 commit 记录在压缩包旁的 r2-delivery.json。

## 未执行与未确认

本机没有 rclpy/colcon、Docker 或可用 WSL 发行版。本轮未运行新版 ARM64/Foxy colcon、DDS QoS矩阵、完整SLAM/AMCL/Nav2、RViz、Linux资源监督实跑或G1硬件验证。`tests/ros_field_regression.py` 和 `scripts/test_on_foxy.sh` 已提供，尚未执行；不能写成 passed。机器人现场四条底层链路是用户提供的实测反馈，本轮没有重新采集。

现场 nav2_fixed.yaml、崩溃栈、内核 OOM/cgroup 日志未提供，**bad_alloc 根因 UNKNOWN**。现有代码局部 costmap 3600 cells 没有明显尺寸爆炸；r2 添加输入/地图分配边界、显式全局初始尺寸、减小DWB候选和资源证据采集，但不能据此声称 G1 上崩溃已经排除。默认保留CycloneDDS，增加显式FastDDS诊断入口但未运行原生A/B，不换自写避障。根据用户追加交接文档，补齐Python环境/DDS库路径/时间戳打包遗漏，详见FIELD_HANDOFF_AUDIT_R2.md；外部DDS路径的检出也不等于bad_alloc已归因。

真实xyz/quaternion/地面/footprint/时间同步未知项继续阻断完整导航。默认 sensor_check 只提供 livox_frame 接收时刻预览；receive_time 不证明采样同步，不支持真实运动。现场需要重建新overlay并验证30秒门禁、生命周期、真实地图、Nav2 Action、动态障碍与故障归零。

## 历史基线，仅作追溯

旧基线代码 `7fcbe0c9d3d91d049baaa736c1f7d3c1bd62be7f` 曾在原生ARM64/x86_64的Ubuntu20.04/Foxy容器分别通过54项合同、3项负向启动、27项ROS集成。原报告保留在 history/VERIFICATION_BASELINE_20261020.md，原始摘要在 docs/ci/release.json。那些结果只适用于旧代码，不是r2通过证明。相关退出时RMW卸载缓解也不能直接解释本轮现场bad_alloc。

本轮交付的运行/安装命令见 FIELD_FIX_R2.md。不会为通过测试填写虚构外参、初始位姿或地图。未部署、未push、未创建PR。
