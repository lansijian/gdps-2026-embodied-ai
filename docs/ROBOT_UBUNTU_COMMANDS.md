# G1 · Ubuntu 采集与上传指令

任意 Linux 通用（DDS/eth0 仅 G1 相关）。`python3` 3.8+，不需要 venv / ROS2。

## 1. 克隆仓库

```bash
git clone -b feat/reflow-s22-s05 https://github.com/lansijian/gdps-2026-embodied-ai.git ~/gdps-embodied-ai
cd ~/gdps-embodied-ai && git log --oneline -1
```

模板图片与知识库不在仓库里，单独放一个目录：

```bash
export TEMPLATES="$HOME/templates"    # 001.jpg..028.jpg、25.jpg、knowledge_base.json
ls "$TEMPLATES/001.jpg" "$TEMPLATES/knowledge_base.json"
```

P2 文本问答的事件源（`guide_cli.py`、`similarity_matcher.py`）也不在仓库；从交付包拷到仓库根目录，不需要 P2 就跳过。

## 2. API Key

```bash
mkdir -p ~/.gdps && chmod 700 ~/.gdps
vi ~/.gdps/api_key        # 粘贴队伍 API Key
chmod 600 ~/.gdps/api_key
```

## 3. 采集

```bash
cd ~/gdps-embodied-ai
mkdir -p logs

# 相机 + 讲解（生成 logs/run_HHMM.events.jsonl）
python3 scripts/tourism/match_webcam.py --templates "$TEMPLATES" --camera 0 \
  --backend v4l2 --headless --control-mode autonomous \
  --log-jsonl logs/run_$(date +%H%M).jsonl

# 单图验收
python3 scripts/tourism/match_webcam.py --templates "$TEMPLATES" --image "$TEMPLATES/001.jpg"

# 问答（需 guide_cli.py）
python3 guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl

# 语音问答（可选；需 guide_cli + whisper.cpp）
export GDPS_ASR_CMD="whisper-cli -m $HOME/whisper.cpp/models/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
python3 reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl

# 具身（只读，不发控制指令）
python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl
```

RealSense 用 `--backend realsense`。

## 4. 上传

```bash
EVAL='<evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"

python3 tools/reflow_bootstrap.py --track s22 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"

SESSION_ID='<返回的 session_id>'
python3 tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"

# dry-run：只生成并校验
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

S05 把 `--track s22` 换成 `--track s05 --mode generic`，事件写 `checkpoint_record`。

## 5. 后台跑

```bash
tmux new -d -s bridge 'cd ~/gdps-embodied-ai && python3 reflow/sdk_bridge.py --duration 0 --mode autonomous --out logs/robot.events.jsonl'
tmux new -d -s camera 'cd ~/gdps-embodied-ai && python3 scripts/tourism/match_webcam.py --templates "$TEMPLATES" --camera 0 --backend v4l2 --headless --control-mode autonomous --log-jsonl logs/run_$(date +%H%M).jsonl'
```

## 6. 卡住先看

| 现象 | 处理 |
| --- | --- |
| 收不到 lowstate | `--interface eth0`；`ip -brief addr` |
| 没有 /dev/video | `lsusb`；RealSense 换 `--backend realsense` |
| 中文显示方块 | `sudo apt install fonts-noto-cjk` |
| 401/422/409/410 | 看回执 `error.code` / `field_errors` |
| 克隆失败 | 换镜像/内网源；模板与 key 可离线拷贝 |

检查点终态不可覆盖；上传窗口 7 天；key `chmod 600`。
