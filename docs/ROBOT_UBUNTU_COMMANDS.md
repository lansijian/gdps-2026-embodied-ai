# G1 · Ubuntu 20.04 采集与上传指令

`python3` 直跑，不需要 venv / ROS2。工作目录 `~/gdps-embodied-ai`。

## 部署（Mac 执行一次）

```bash
rsync -av --exclude '.venv' --exclude '__pycache__' --exclude 'logs' \
  ~/Downloads/导览图/ unitree@192.168.123.164:~/gdps-embodied-ai/
scp ~/.gdps/api_key unitree@192.168.123.164:~/.gdps/api_key
ssh unitree@192.168.123.164 'mkdir -p ~/gdps-embodied-ai/logs && chmod 600 ~/.gdps/api_key'
```

依赖机器人已具备（cv2 / numpy / PIL / yaml / unitree_sdk2py）。缺了就：

```bash
sudo apt install -y python3-opencv python3-numpy python3-yaml python3-pil fonts-noto-cjk espeak-ng
```

## 采集

相机 + 讲解：

```bash
cd ~/gdps-embodied-ai
python3 gdps_tourism_camera/scripts/tourism/match_webcam.py \
  --templates . --camera 0 --backend v4l2 --headless \
  --control-mode autonomous --log-jsonl logs/run_$(date +%H%M).jsonl
```

生成 `logs/run_HHMM.events.jsonl`。RealSense 用 `--backend realsense`；单图验收 `--image 001.jpg`。

问答：

```bash
python3 guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl
# 或 --ask "问题"；交互模式 --interactive
```

语音问答（可选）：

```bash
export GDPS_ASR_CMD="whisper-cli -m $HOME/whisper.cpp/models/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
python3 reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl
```

二进制路径按实际 whisper.cpp 安装改；没有引擎就用上面的文本问答。

具身（只读，不发控制指令）：

```bash
python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl
```

## 上传

```bash
EVAL='<evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"
python3 tools/reflow_bootstrap.py --track s22 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"

SESSION_ID='<返回的 session_id>'
python3 tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"

# dry-run：生成并校验，不联网
python3 reflow/agent.py --track s22 \
  --events logs/run_*.events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID"

# 发送
python3 reflow/agent.py --track s22 \
  --events logs/run_*.events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send --api-key-file ~/.gdps/api_key

# 核对
python3 tools/reflow_bootstrap.py --track s22 status --session-id "$SESSION_ID"
```

S05：把 `--track s22` 换成 `--track s05 --mode generic`，事件写 `checkpoint_record`。

## 后台跑

```bash
tmux new -d -s bridge 'cd ~/gdps-embodied-ai && python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl'
tmux new -d -s camera 'cd ~/gdps-embodied-ai && python3 gdps_tourism_camera/scripts/tourism/match_webcam.py --templates . --camera 0 --backend v4l2 --headless --control-mode autonomous --log-jsonl logs/run_$(date +%H%M).jsonl'
```

## 卡住先看

| 现象 | 处理 |
| --- | --- |
| 收不到 lowstate | `--interface eth0`；`ip -brief addr` 看网口 |
| 没有 /dev/video | `lsusb`；RealSense 换 `--backend realsense` |
| 中文显示方块 | `sudo apt install fonts-noto-cjk` |
| 401/422/409/410 | 看回执 `error.code` / `field_errors`；422 多为状态或字段不符 |
| GitHub 连不上 | 不影响；平台域名单独判断（`curl platform`） |

注意：检查点终态不可覆盖；上传窗口 7 天；key `chmod 600`。
