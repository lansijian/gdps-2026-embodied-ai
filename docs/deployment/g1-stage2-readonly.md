# G1 S05 第二阶段：只读采集与离线审查

基线 `7e6bdb62e39b7b5d98c6d393a4808b8abeaf03ba`，新分支 `codex/g1-field-baseline-stage2-20261017`。本次没有连接 G1、没有部署 PC2、没有切换 FSM、没有启动无阻力示教或任何运动发布。

## 交付内容与证据边界

- `g1_motion_diag_readonly.py`：只读 status/watch；旧 SDK 无公开 GetFsmId 时用注册的 `_Call(7001,"{}")`。当前 SDK 公开 getter 同样封装 7001，失败不尝试写 FSM。7002/7003 分开报告错误。SDK API 版本不当作机器人固件版本。
- `g1_arm_readonly_capture.py`：只订阅 `rt/lowstate`，记录臂 15–28、腰 12–14 的 q/dq/tau_est、mode_machine、IMU rpy、原始 tick，以及主机接收 Unix/monotonic 时间。tick 没有假定秒制，也不是高层 FSM。单次最多120s、50Hz，拒绝覆盖，Ctrl+C 关闭订阅并保留已写入数据及报告。重复/回退 tick、非有限值、过期回调独立计数；重启/计数器溢出需另开采样会话。
- `analyze_teach_trajectory.py`：只读源 JSONL，质量检查后导出逐关节因果 Kalman 估计。过程方差按真实采样间隔计算；不插值外推，不生成指令。默认质量阈值 max_gap=.25s、臂单步=.5rad、腰单步=.15rad 仅用于筛选数据，不是认证安全边界。原始数据不变，输出关联 SHA256。机械关节范围可由 `validate_session(..., joint_limits=已核验的17关节映射)` 独立检查，默认 UNKNOWN。
- `TeachingPreview` 组合现有 TF、RGB-D、TargetCenteringController 与 ManipulationReadyGate，锁定目标、复核标定/深度/TCP/FK来源；只能输出 CENTER_PREVIEW、BODY_READY_BLOCKED、POSE_REVIEW_PENDING、SAFE_HOLD，不发送命令、不宣布抓取成功。
- 延续原 G1MotionAdapter/MotionLock/dry-run 的安全门禁改动：非零命令默认无权限，异常续约停止旧请求、finally 尝试停止、非零 RPC 不被停止返回码掩盖。watchdog 仍是协作式轮询，没有独立实时或防跌倒保证。本包白名单排除 adapter、loco_backend、Mock 和所有运动入口，不能从包内启用 LIVE。
- 历史源代码包包含27条记录、27个原样代码块，全部 `.py.txt`；原始粘贴全文与索引哈希可核验。事故代码不可执行、不可部署；“已保存/未保存/未实测/口述”原始状态不改写。

本地 SDK 源码依据：`.research/unitree_sdk2_python` 的 commit `814556d15970dd2ecf1c9984e845ca02ab07e206`，`unitree_sdk2py/g1/loco/g1_loco_client.py` 的 GetFsmId/API7001，`rpc/client.py` 的 API 版本查询，HG LowState IDL 及 core/channel.py 的 Subscriber.Close。它不是 PC2 已安装 SDK 的版本证明，PC2版本/固件待真实只读回报；不安装或覆盖 SDK。

## 流程与后续控制权合同

| 顺序 | 当前实现或审查条件 | 不满足时 |
|---|---|---|
| PRECHECK / OBSERVE_TARGET | 分别采集FSM、LowState、相机；保持真实时间与同一目标ID | UNKNOWN/SAFE_HOLD |
| CENTER_PREVIEW | 复用几何重投影建议，深度/TF必须可信；RGB单独保存不代表3D可用 | 不建议运动 |
| VERIFY_STOP / BODY_READY | 独立odom、IMU、关节鲜度及姿态；像素居中不能替代可达性 | BODY_READY_BLOCKED |
| TEACH_PREVIEW | 只读记录→质量检查→Kalman；旧臂-only记录允许分析，但full_telemetry=false | 不批准回放 |
| ARM_PREGRASP / FINAL_VISUAL_SERVO / GRASP / RETRACT | 未来：厂家支持模式、可靠防跌落装置、已校准URDF/FK/TCP、自碰撞、仿真及人工逐阶段审批 | 本轮全部禁止执行 |

未来动作必须继续使用已有独占 MotionLock，行走、ArmAction、arm_sdk、手部控制一次只允许一个动作所有者；现有文件锁不证明厂商 SDK lease/其他进程/底层控制器无竞争。后续 arbiter 审批设计：先独立停止证据→撤销旧所有者→只读核验模式/lease→人工授权新所有者；不确定即不授予新所有者，不自动 Debug/501/801/6，不创建第二套运动通道。

权重1.0保留为动作阶段的历史经验目标，不声称本次已实现 ArmSDK 控制器。以后接管应从当前可信读数做有限速率渐变、动作中监测关节/腰/IMU、退出受控交接；姿态告警必须允许请求退出，不能沿用事故脚本“倾角守卫同时拦住权重归零”的共用 write 路径。退出与释放不等于防跌倒；腰 kp/kd、力矩边界、接管/退出时长尚无核验默认值，尤其不得硬编码 kp=150。

## 依赖与离线命令（不安装）

Python3.8+。关节采集需要 PC2 **已安装**的 unitree_sdk2py/CycloneDDS 与确认过的 HG LowState 型号/网卡；轨迹分析仅标准库。既有相机/TF Gate 需要 NumPy、OpenCV、PyYAML、ROS2 Foxy、rclpy、message_filters、cv_bridge、image_geometry、tf2_ros、sensor_msgs_py、rosidl_runtime_py。缺依赖报告失败，不自动 apt/pip、不改服务。

Windows 仓库内：

```powershell
Set-Location E:\GDPS\competition
python -m pytest tests/ -q -rs --junitxml=dist/g1-stage2-tests.xml
python scripts/g1/g1_motion_diag_readonly.py status --mock --out dist/status-synthetic.json
# 把 G1 已采集 JSONL 拷回本地后（不需要 Windows ROS）：
python scripts/g1/analyze_teach_trajectory.py dist/arm-observation.jsonl --out dist/arm-analysis.json
# 提交后白名单打包，已有包拒绝覆盖：
python scripts/g1/package_g1_stage2.py
Get-FileHash dist/g1-stage2-delivery/*.zip -Algorithm SHA256
```

## 人工现场只读命令（本轮没有执行）

不自动上传、不部署到 PC2。若后续单独批准使用，人工在独立新目录解压只读 ZIP，核验 SHA256 与 MANIFEST，不覆盖导航目录。历史源码 ZIP 仅存档审阅，不上机器人。

```bash
# 在获准使用的 Linux 离线/现场环境；ZIP 的短SHA按实际文件名填写
sha256sum -c g1-stage2-readonly-实际短SHA.zip.sha256
FIELD_ROOT="$(mktemp -d "$HOME/gdps-g1-stage2-readonly-XXXXXX")"
python3 -m zipfile -e g1-stage2-readonly-实际短SHA.zip "$FIELD_ROOT"
cd "$FIELD_ROOT"
sha256sum -c MANIFEST.sha256
# SDK只读查询/订阅，不更改FSM；确认网卡，当前现场记录为eth0
/usr/bin/python3 scripts/g1/g1_motion_diag_readonly.py status --iface eth0 --out state.json
/usr/bin/python3 scripts/g1/g1_arm_readonly_capture.py --iface eth0 --seconds 10 --hz 20 --out arm-observation.jsonl
/usr/bin/python3 scripts/g1/analyze_teach_trajectory.py arm-observation.jsonl --out arm-analysis.json
# 已有ROS相机/TF/点云 Gate；--live仅表示订阅传感器，绝无运动发布
source /opt/ros/foxy/setup.bash
python3 scripts/g1/check_field_dependencies.py
ros2 topic list -t
# 先核对Topic，唯一相机族可自动发现；缺Depth/Scan分别报告UNKNOWN
python3 scripts/g1/field_gates_centering.py --live --gate all --timeout 10 --max-frames 10 --out-dir camera-evidence
```

录包与提取沿用 `record_field_bag.sh`、`replay_field_extract.py`，详见 phase441-field-capture.md；只选择现场存在的Topic，缺scan不影响原始点云成果。不要启动机器人控制/DDS运动接口来“补齐数据”。

## 下一次测试最短顺序与未解决项

先取只读API7001/SDK版本、MotionSwitcher原始CheckMode、LowState/IMU和17关节JSONL；随后静态RGB/CameraInfo及真实Depth/TF、同一目标ID图像和odom/点云；最后带回原始bag/JSONL/视频、运行离线质量及居中预览。只读阶段不需要人为拖动关节。

尚缺：成功运动时的FSM/模式/逐方向odom日志、跌倒同步遥测、厂家认可的上肢示教与控制权交接、可靠防跌落装置、设备/手型确认、实际URDF/标定/TCP/碰撞/仿真数据。未经这些前置与另行人工审批，不进入任何动态复验。停止编码后等待这些真实G1数据。
