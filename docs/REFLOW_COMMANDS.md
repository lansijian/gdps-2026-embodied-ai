# Mac 本机指令（联调/远控）

机器人内执行看 [ROBOT_UBUNTU_COMMANDS.md](ROBOT_UBUNTU_COMMANDS.md)。本机用 `~/Downloads/导览图` + `.venv/bin/python`。

## 采集

```bash
cd ~/Downloads/导览图
PY=.venv/bin/python

# 单图验收（不产生事件）
$PY gdps_tourism_camera/scripts/tourism/match_webcam.py --templates . --image 001.jpg

# 录像回放，生成事件
$PY gdps_tourism_camera/scripts/tourism/match_webcam.py --templates . --video demo.mp4 \
  --headless --control-mode autonomous --log-jsonl logs/run_demo.jsonl
```

## 上传

```bash
export GDPS_API_KEY_FILE="$HOME/.gdps/api_key"
EVAL='<evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"
$PY tools/reflow_bootstrap.py --track s22 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"

SESSION_ID='<返回的 session_id>'
$PY tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"
$PY reflow/agent.py --track s22 --events logs/run_demo.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID"      # dry-run
$PY reflow/agent.py --track s22 --events logs/run_demo.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send
$PY tools/reflow_bootstrap.py --track s22 status --session-id "$SESSION_ID"
```

## 拉机器人日志

```bash
rsync -av unitree@192.168.123.164:~/gdps-embodied-ai/logs/ ~/backup/场次/
```
