# Phase 4.4 验证与交付记录（2026-10-17）

基线：846110ed457c514a3394e380b886cab6a51869fd；分支 feat/quality-inspection-agent。开始时已有相关未提交实现，本轮在其基础上审查修复。现场旧文档、研究 ZIP、其他未跟踪交接文件保留原位，不混入本提交。

## 实现与严格验证

- 光学坐标：optical (right,down,forward) → base (forward,left,up)；背后目标返回 INVALID_TARGET_BEHIND_CAMERA/NaN 而非零误差。左右候选位移实际重投影选方向；相机 yaw/pitch/translation 组合、反 bearing 例子均覆盖。
- 严格闭环：默认 8 次合成更新，绝对像素误差 125→65，改善 60px，到达次数上限仍未居中，明确不报成功。另有最多 20 次的收敛回归，要求至少两次更新、每次严格改善、最终 <15px、总改善 >100px，无 `or ok` 等宽松断言。
- RGB/Depth/CameraInfo 各自真实 header stamp；缺失、NaN、超差、分辨率不符、单位/注册未确认均拒绝可靠距离。未知外参/FOV/对应关系不许比较或融合；本轮跨传感器 fusion 始终禁用，即使对照允许也不自动融合。
- 状态流唯一实例 ID，实际遍历 35 个步骤访问完成六轮 P1/P2/REPEAT_6 与 P3–P6；覆盖第二次稳定站立、失败重试、恢复证据、超时、安全暂停和完成幂等。
- 控制器 monotonic、递增帧与非空同目标 ID、观测/确认移动计数分离、目标丢失/误差增大/方向异常锁定 SAFE_HOLD。视觉居中不直接授权抓取；标定源文件/TF/深度/TCP/verified URDF FK/工作空间证据共同门禁。
- Gate A–E 共享只读采集与派生证据分析，单 Gate 异常隔离；图像限量，源与回放明确标注，永不自动 FIELD_VERIFIED。独立诊断目录中可运行，无需导航/硬件运动包。

## 完整统计

`python -m pytest -q -rs --junitxml=dist/phase44-tests.xml`：**136 passed, 4 skipped**。

跳过：1 项 ROS/Foxy 实际 API 合约测试（Windows 没有 rclpy）；3 项 Pinocchio/G1 IK 相关测试（未安装 Pinocchio）。这些不算现场通过或 G1 IK 已验证。

附加检查：录制脚本 `bash -n` 通过；诊断 ZIP 逐文件 SHA256、Python 3.8 AST 语法、独立目录导入/运行、缺数据 UNKNOWN、异常 Gate 隔离、白名单不含运动入口/缓存/密钥检查通过。Python 3.8 仅做语法兼容性检查，并非在本机运行 Python 3.8 或 ROS/Foxy 集成。

## 交付位置

- 完整操作单及最短现场顺序：`docs/deployment/phase44-field-replay.md`。
- 官方 REUSE / KEEP / REPLACE_LATER / UNSUPPORTED 表、精确上游 SHA、源码路径：`docs/research/phase44-reuse.md`，同目录 source-refs/source-audit JSON。
- 白名单打包：`scripts/g1/package_phase44.ps1` / `.py`；最终提交后生成 `dist/gdps-s05-phase44-readonly.zip`，旁置 `.zip.sha256`。ZIP 的 BUNDLE.json 对应源 commit，MANIFEST.sha256 对应实际文件内容。ZIP 与 JUnit 是本地交付物，不纳入 Git 二进制提交。
- 只读采集与 Gate：`scripts/g1/field_evidence.py`、`field_gates_centering.py`。
- 真实 rosbag2 录制与 G1 提取：`record_field_bag.sh`、`replay_field_extract.py`。原包/QoS/时间戳保留，不假定 Windows 有 ROS 反序列化环境。

## 现场未验证事项

本机为 Windows，无 ROS2/rclpy。仓库日志有 2026-10-16 的 Topic 发现清单（仅证实当时名称存在），未找到可供本轮使用的 .db3/metadata.yaml/.mcap/RGB-D NPY 实测数据。故真实采集、rosbag2 录制/提取、机载 Python3.8/官方 ROS 模块的运行兼容性、相同目标前后实际改善均为 **UNVERIFIED**。不声称今天采集的数据已被成功回放。

需现场取得：RGB/Depth/CameraInfo 真实 Topic/类型/时间戳，深度尺度与注册来源，MID-360/Scan/odom 原始数据，完整 TF 与时钟，机器人准确配置、可信关节/URDF/TCP/工作空间标定。最短顺序为新目录校验与依赖检查 → 静止 A/B/E → 5s/20s rosbag2 → G1 提取 → Windows C/D → 同一目标视野左右两段短包。已独立授权取得的移动前后数据可追加比较；本轮未启用真机运动、未安装/升级 ROS、未更改 Livox 或导航部署。
