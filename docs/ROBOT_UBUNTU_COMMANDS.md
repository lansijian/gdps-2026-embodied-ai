# 机器人 Ubuntu 现场指令手册（G1 · Ubuntu 20.04 LTS）

> 版本 v1.0 · 2026-10-22
> 适用：**直接在机器人内 Ubuntu 上执行**（不经过 Mac）；S22 文旅导览 / S05 质检检测
> 配套：`docs/REFLOW_COMMANDS.md`（Mac 侧）、`reflow/README.md`、`docs/GUIDE_EVENTS_v1.md`

---

## 0. 环境基线（实测）

| 项 | 值 |
| --- | --- |
| 主机 | `ubuntu`（Jetson aarch64），Ubuntu 20.04.6 LTS，Python 3.8.10 |
| 资源 | 8 核 / 15 GiB，`/` 剩余 1.8 TB |
| 已有依赖 | cv2 4.2、numpy 1.24.4、Pillow、PyYAML、`unitree_sdk2py` |
| DDS 网口 | `eth0`（192.168.123.164） |
| 平台连通 | `curl https://platform.ieic.gdps.org.cn/` → 200（约 0.24s） |
| 时间 | `Asia/Shanghai +08:00`，NTP 已同步 |
| 摄像头 | 需现场确认 `/dev/video*` 或 Intel RealSense |

> 机器人上**不需要** source ROS2 环境即可做回流：采集用 `python3` + `unitree_sdk2py`，上传用纯 HTTP。

---

## 1. 部署（Mac → 机器人，二选一）

### A. 交付版（推荐：相机 + 问答 + 回流 自包含）

```bash
# 在 Mac 上执行
rsync -av --exclude '.venv' --exclude '__pycache__' --exclude 'logs' \
  ~/Downloads/导览图/ unitree@192.168.123.164:~/gdps-embodied-ai/
ssh unitree@192.168.123.164 'mkdir -p ~/gdps-embodied-ai/logs'
```

机器人上的工作目录：`~/gdps-embodied-ai`。

### B. 仓库版（含最新 guide/nav 代码，需另补模板）

```bash
rsync -av --exclude '.git' --exclude '__pycache__' \
  --exclude 'build' --exclude 'install' --exclude 'log' \
  ~/gdps-2026-embodied-ai/ unitree@192.168.123.164:~/gdps-2026-embodied-ai/

# 仓库未跟踪模板与知识库，从交付包补
rsync -av --include '0*.jpg' --include '2*.jpg' --include '25.jpg' \
  --include '*.txt' --include 'knowledge_base.json' --exclude '*' \
  ~/Downloads/导览图/ unitree@192.168.123.164:~/gdps-2026-embodied-ai/
```

> 仓库版没有 `guide_cli.py`/`similarity_matcher.py`（文本问答、ASR 问答依赖它们）；需要时用交付版，或把这两个文件一并拷入。

---

## 2. 机器人上检查依赖

```bash
ssh unitree@192.168.123.164
cd ~/gdps-embodied-ai

python3 -V
python3 - <<'PY'
import importlib.util
for m in ("cv2", "numpy", "PIL", "yaml", "unitree_sdk2py"):
    print(m, bool(importlib.util.find_spec(m)))
PY

command -v espeak-ng || echo "no espeak-ng"
fc-list :lang=zh 2>/dev/null | head -2 || echo "no CJK font"
ls /dev/video* 2>/dev/null || echo "no /dev/video"
lsusb | grep -iE "realsense|camera|uvc" | head -3
timedatectl | head -3
curl -sS -m 8 -o /dev/null -w 'platform=%{http_code}\n' https://platform.ieic.gdps.org.cn/
```

缺什么补什么（一般都已具备）：

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-yaml python3-pil \
  espeak-ng fonts-noto-cjk ca-certificates
# RealSense 用户：sudo apt install -y python3-pyrealsense2（或按官方脚本）
```

---

## 3. API Key

```bash
# Mac 上传 Key（只发生一次）
scp ~/.gdps/api_key unitree@192.168.123.164:~/.gdps/api_key

# 机器人上收紧权限
mkdir -p ~/.gdps && chmod 700 ~/.gdps
chmod 600 ~/.gdps/api_key
```

---

## 4. 数据采集（机器人本地 python3）

所有事件写到 `logs/`，后续由 `reflow/agent.py` 合并上报。

### 4.1 相机 + 讲解（S22 P1）

```bash
cd ~/gdps-embodied-ai
mkdir -p logs

# USB/UVC 相机
python3 gdps_tourism_camera/scripts/tourism/match_webcam.py \
  --templates . --camera 0 --backend v4l2 --headless \
  --method orb --prefilter orb --match-every 2 \
  --control-mode autonomous \
  --log-jsonl logs/run_$(date +%H%M).jsonl
```

- 无显示器自动 headless；退出时打印 `[done]` 统计；
- 自动生成同名事件文件 `logs/run_<HHMM>.events.jsonl`（也可 `--events-jsonl` 显式指定）；
- RealSense：`--backend realsense`；
- 单图验收：`--templates . --image 001.jpg`。

### 4.2 文本问答（S22 P2）

```bash
python3 guide_cli.py --ask "徐光启是谁" --events-jsonl logs/qa.events.jsonl
python3 guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl
python3 guide_cli.py --interactive --events-jsonl logs/qa.events.jsonl
```

### 4.3 语音问答（可选，需 whisper.cpp）

```bash
sudo apt install -y git build-essential cmake ffmpeg
git clone https://github.com/ggerganov/whisper.cpp ~/whisper.cpp
cd ~/whisper.cpp && make -j4
bash ./models/download-ggml-model.sh base       # 需外网；离线可提前拷模型

export GDPS_ASR_CMD="$HOME/whisper.cpp/build/bin/whisper-cli -m $HOME/whisper.cpp/models/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
# 旧版本 whisper.cpp 二进制可能是 build/bin/main，按实际路径改

cd ~/gdps-embodied-ai
python3 reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl
# 或用已录音频：--audio logs/q.wav
```

没有 ASR 引擎时：用 4.2 的预置问题清单，不影响 P2 得分链路。

### 4.4 实机具身数据（G1，只读订阅）

```bash
cd ~/gdps-embodied-ai
python3 reflow/sdk_bridge.py \
  --duration 0 \                 # 0 = 跑到 Ctrl+C
  --embodied-hz 5 \
  --mode autonomous \             # 只有真实以该模式运行才这么填
  --interface eth0 \
  --out logs/robot.events.jsonl
```

- 订阅 `rt/lowstate`（35 电机 q/dq/tau + IMU）与 `rt/lf/bmsstate`（电量）；
- **只创建 Subscriber，不发布任何控制指令**，不会让机器人运动；
- 正常输出：`[done] samples=... rate=5.0Hz lowstate=... bms=...`。

### 4.5 轨迹（暂不上传）

`/dog_odom` 的 ROS2 订阅在本机环境报 `bad_alloc`（foxy + cyclonedds），平台轨迹通道 `required=false`，先不传；需要时再单独适配。

---

## 5. 上传（机器人直连平台）

### 5.1 建会话（每场一次）

```bash
cd ~/gdps-embodied-ai
EVAL='<评测中心拿到的 evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"

python3 tools/reflow_bootstrap.py --track s22 session \
  --evaluation-id "$EVAL" --morphology humanoid --idempotency-key "$IDEM"
# 记录返回的 session_id 与 upload_window；profile 必须是 S22-v1

SESSION_ID='<返回的 session_id>'
python3 tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"
```

### 5.2 生成并校验（dry-run，不联网）

```bash
python3 reflow/agent.py --track s22 \
  --events logs/run_*.events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" \
  --out-dir logs/reflow_agent --note "G1 现场"
```

### 5.3 发送

```bash
python3 reflow/agent.py --track s22 \
  --events logs/run_*.events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" \
  --send --api-key-file ~/.gdps/api_key
```

### 5.4 收尾核对

```bash
python3 tools/reflow_bootstrap.py --track s22 status --session-id "$SESSION_ID"
```

通过标准：`intake.completeness_status=complete`、`missing_checkpoint_ids=[]`、`sequence_gaps=[]`。

### 5.5 S05 质检（通用模式）

```bash
EVAL='<S05 evaluation_id>'
IDEM="s05-$(printf %s "$EVAL" | cut -c1-8)-session-create"
python3 tools/reflow_bootstrap.py --track s05 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"

python3 reflow/agent.py --track s05 --mode generic \
  --events logs/s05.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send --api-key-file ~/.gdps/api_key
```

---

## 6. 长时运行（tmux / systemd）

### 6.1 tmux（推荐：相机交互 + 多进程）

```bash
cd ~/gdps-embodied-ai
tmux new -d -s bridge 'cd ~/gdps-embodied-ai && python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl 2>&1 | tee logs/bridge.log'
tmux new -d -s camera 'cd ~/gdps-embodied-ai && python3 gdps_tourism_camera/scripts/tourism/match_webcam.py --templates . --camera 0 --backend v4l2 --headless --control-mode autonomous --log-jsonl logs/run_$(date +%H%M).jsonl 2>&1 | tee logs/camera.log'

tmux ls
tmux attach -t camera      # 看实时输出；Ctrl+B D 退出
tmux kill-session -t camera
```

### 6.2 systemd（仅具身桥这类无交互进程）

```bash
sudo tee /etc/systemd/system/gdps-bridge.service >/dev/null <<'EOF'
[Unit]
Description=GDPS reflow embodied bridge (read-only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=unitree
WorkingDirectory=/home/unitree/gdps-embodied-ai
ExecStart=/usr/bin/python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now gdps-bridge
journalctl -u gdps-bridge -f
```

相机进程带 HUD/退出键，不要放 systemd，用 tmux。

---

## 7. 每场 Runbook（机器人侧）

| 时刻 | 动作 |
| --- | --- |
| T-30 | `ssh` 进机器人：`timedatectl`、`df -h /`、`curl 平台`、`ls /dev/video*`、Key 可读 |
| T-25 | 建会话 + 拉冻结包（命令见 §5.1），核对 profile 与检查点 |
| T-20 | 起 `bridge` tmux、起 `camera` tmux、开录（机位/手机） |
| T-0 | 开始导览；问答用 `guide_cli`（或 ASR） |
| T+0 | 停 camera / bridge → dry-run → `--send` → `status` 核对 |
| T+10 | Mac 拉回日志归档：`rsync -av unitree@192.168.123.164:~/gdps-embodied-ai/logs/ ~/backup/场次/` |
| T+15 | 网页上传评测数据文件（多视角录像等） |

---

## 8. 排错

| 现象 | 处置 |
| --- | --- |
| ssh 超时 | 是否同一网段（192.168.123.x）；网线/网卡；`ping 192.168.123.164` |
| `5s 内未收到 rt/lowstate` | `ip -brief addr` 确认网口；`--interface eth0`；DDS 服务是否在跑 |
| `/dev/video*` 不存在 | USB/RealSense 未插或占用；`lsusb`；`--backend v4l2/realsense` |
| HUD 中文方块 | `sudo apt install fonts-noto-cjk` |
| 无语音播报 | `command -v espeak-ng`；缺失则 apt 安装；或改用仓库 guide 的扬声器模块 |
| 平台 401/422/409/410 | 见 `docs/REFLOW_COMMANDS.md` §4（Key/状态/幂等/窗口） |
| TLS/证书错误 | `sudo apt install ca-certificates`；不要用 `--insecure` 正式跑 |
| 时间漂移 | `sudo timedatectl set-ntp true`；时间戳必须 +08:00 |
| 磁盘增长 | `du -sh logs/*`；按场次归档后清理 `logs/run_*` |

---

## 9. 目录与命名（机器人上）

```
~/gdps-embodied-ai/
├── gdps_tourism_camera/scripts/tourism/match_webcam.py   # 相机入口
├── guide_cli.py / similarity_matcher.py                  # 文本/ASR 问答
├── reflow/{agent.py,sdk_bridge.py,asr_qa.py,...}         # 回流
├── tools/reflow_bootstrap.py                             # 平台引导
├── logs/
│   ├── run_<HHMM>.events.jsonl                           # P1
│   ├── qa.events.jsonl                                   # P2
│   ├── robot.events.jsonl                                # 具身
│   ├── reflow_agent/                                     # 上报 payload
│   └── reflow/                                           # 请求/响应/request_id 审计
└── docs/
```

命名：录像 `<evaluation_id>_cam<机位>_<YYYYmmdd-HHMM>.mp4`；每场归档事件 + status + 录像。

---

## 10. 安全

- Key 仅 `~/.gdps/api_key`（600），不入库、不进日志、不发群；赛后轮换；
- `sdk_bridge.py` 只读，不创建 Publisher；不要在现场随手跑其它控制脚本；
- 正式评测只上报真实数据；做不了的检查点如实 `skipped/failed`，不刷 `completed`。
