# 导览事件契约 v1.2（GUIDE_EVENTS_v1）

> 适用：相机/讲解进程、问答 CLI、语音 ASR、底盘/交互模块 → `reflow/agent.py` → 平台回流 API
> 状态：v1 相机事件；v1.1 增加 **P2 问答事件源**与多来源合并；v1.2 增加 **语音 ASR 适配器**（`reflow/asr_qa.py`）。
> 逐帧日志 `--log-jsonl` 用于性能分析；结构化事件 `--events-jsonl` 用于回流上报与赛后复盘。

## 1. 事件源

| 来源 | 命令 | 产出事件 |
| --- | --- | --- |
| 相机 + 讲解 | `match_webcam.py --log-jsonl run.jsonl`（自动生成 `run.events.jsonl`） | `run_start`、`control_mode_changed`、`exhibit_stable`、`narration_*`、`exhibit_left`、`exhibit_unknown`、`run_end` |
| 问答（P2） | `guide_cli.py --ask "问题" --events-jsonl qa.events.jsonl` | `qa_answered`、`qa_unanswered` |
| 语音提问（P2） | `asr_qa.py --audio q.wav --asr-cmd "引擎命令 {audio}"` | `asr_transcript` + `qa_answered/unanswered`（details 带 asr 元信息） |
| 底盘/跟随/互动/推荐（P3–P6） | 各模块按本契约追加 | `tracking_*`、`interaction_*`、`language_*`、`recommendation_*`、`embodied_sample`、`trajectory_point` |

多个文件由 agent 按 `ts` 合并：`--events run.events.jsonl qa.events.jsonl`。
各源进程各自维护自己的 `seq`（文件内单调），合并后以 `ts` 为准。

## 2. 通用字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 固定 `"1.0"` |
| `seq` | int | 文件内单调递增；仅排错用 |
| `ts` | string | ISO 8601 + `+08:00`，毫秒精度；**唯一时间基准** |
| `type` | string | 事件类型（见 §3） |
| 其余 | object | 各事件自有字段 |

## 3. 事件类型

| type | 产生时机 | 关键字段 | 回流映射 |
| --- | --- | --- | --- |
| `run_start` | 导览启动 | `source`, `match_every`, `template_count`, `match_rate` | 报告 `start_at` |
| `control_mode_changed` | 声明/切换控制模式 | `mode` | `control_records[]` |
| `exhibit_stable` | 多帧投票稳定命中 | `template_id`, `exhibit_id`, `exhibit_name`, `confidence`, `inliers` | P1 识别尝试 |
| `narration_start` | 触发讲解 | `template_id`, `exhibit_id`, `has_summary`, `tts` | P1 attempt（聚合） |
| `narration_end` | 讲解结束/切换 | 同上 + `duration_s`, `reason` | P1 attempt / 终态 |
| `exhibit_left` | 命中结束 | `dwell_s`, `reason` | 诊断 |
| `exhibit_unknown` | 无稳定命中 | `reason`, `frame_id` | 诊断 |
| `run_end` | 循环结束（含 Ctrl+C） | `interrupted`, `frames`, `matches` | `end_at` / `task_status` |
| `qa_answered` | 问答命中 | `details.question/exhibit_id/hit_score/response_latency_s/top_candidates` | P2 observation `answered` |
| `qa_unanswered` | 问答未命中/超时 | `details.question/hit_score/threshold/reason` | P2 observation `unanswered` |
| `asr_transcript` | 语音转写完成（诊断用） | `text`, `audio`, `backend`, `asr_latency_s` | 不直接上报（供复盘/排查） |
| `language_switch_attempt` / `language_switched` / `language_switch_failed` | 多语言 | `details.language` | P3 |
| `tracking_started` / `tracking_lost` / `tracking_recovered` / `tracking_finished` / `collision` | 跟随避让 | `details` | P4 |
| `interaction_started` / `interaction_finished` / `interaction_no_response` | 途中互动 | `details` | P5 |
| `recommendation_provided` / `recommendation_absent` | 销售推荐 | `details.items` | P6 |
| `embodied_sample` | 关节/电量采样 | `sample_seq`, `timestamp`, `mode`, `joint_positions`, `battery_pct`, `sensors` | `/reflow/embodied/batch` |
| `trajectory_point` | 位姿点 | `point_seq`, `timestamp`, `x_m`, `y_m`, `z_m`, `yaw_rad` | `/reflow/trajectories/batch` |

## 4. 检查点判定（`reflow/agent.py`）

| 检查点 | 判定 |
| --- | --- |
| P1 定点讲解 | 有 `narration_end` → completed；开始但未结束 → partial；有识别无讲解 → failed；无识别 → skipped |
| P2 问答 | 有 `qa_answered` → completed；只有 unanswered → partial；无事件 → skipped |
| P3 多语言 | `language_switched`（attempt/observation）→ completed；只有失败 → partial；无 → skipped |
| P4 跟随避让 | `tracking_finished` 且无 `collision` → completed；有 collision → partial；无 → skipped |
| P5 途中互动 | `interaction_finished` → completed；无 → skipped |
| P6 销售推荐 | `recommendation_provided` → completed；无 → skipped |

任务总状态：`run_end.interrupted` → aborted；无 completed → failed；6 个全 completed → completed；否则 partial。
可用 `--task-status` 覆盖。事件晚于 `run_end` 时会写入告警（提示时钟或合并顺序有问题）。

## 5. 生成事件

相机 + 讲解：

```bash
.venv/bin/python gdps_tourism_camera/scripts/tourism/match_webcam.py \
  --templates . --camera 0 --control-mode autonomous \
  --log-jsonl logs/run.jsonl          # 自动生成 logs/run.events.jsonl
```

问答（无 ASR 时的 P2 兜底：现场键入问题或预置问题清单）：

```bash
.venv/bin/python guide_cli.py --ask "徐光启是谁" --events-jsonl logs/qa.events.jsonl
.venv/bin/python guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl
```

语音提问（需自备 ASR 引擎；adapter 不绑定具体实现）：

```bash
# whisper.cpp 示例（模型自备）
export GDPS_ASR_CMD="whisper-cli -m /path/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"
.venv/bin/python reflow/asr_qa.py --audio logs/q.wav --events-jsonl logs/qa.events.jsonl
# 现场录音（需 ffmpeg / arecord / sox 之一）
.venv/bin/python reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl
# 无引擎时先用假命令验证链路
.venv/bin/python reflow/asr_qa.py --audio logs/q.wav --asr-cmd "echo 徐光启是谁" --events-jsonl /tmp/qa.jsonl
```

## 6. 转成上报

```bash
# dry-run（默认）：生成 payload + spec 感知校验，不联网
.venv/bin/python reflow/agent.py \
  --events logs/run.events.jsonl logs/qa.events.jsonl \
  --evaluation-id <评测ID> --session-id <回流会话ID> \
  --out-dir logs/reflow_agent --note "10/23 第一场"

# 真正发送：running → 批次 → 终态 → 自动查 status
.venv/bin/python reflow/agent.py ... --send --api-key-file ~/.gdps/api_key
```

产物：`report-start.json`、`report-final.json`、`embodied-*.json`、`trajectory-*.json`、`requests/`（含 `request_id`）。

幂等：`report_id`/`record_id` 由 `run_id` 确定性生成，**重跑安全**；同 `run_id` 改内容会 409，需换 `--run-id`。

## 7. 校验与测试

```bash
.venv/bin/python -m unittest discover -s reflow/tests                     # 13 项（agent/通用模式 9 + asr_qa 4）
.venv/bin/python -m unittest discover -s gdps_tourism_camera/tests        # 7 项
```

## 8. 多赛道：通用事件模式（S05 质检检测等）

S22 的事件是“展品/问答/跟随”这类能力事件，由 agent 的 auto 模式聚合。**其他赛道（如 S05 质检检测）**通常有不同流程，用通用模式：事件显式携带检查点记录。

```json
{"schema_version":"1.0","seq":3,"ts":"2026-10-23T10:00:20.000+08:00",
 "type":"checkpoint_record","checkpoint_id":"S05-P1",
 "record_kind":"checkpoint_result","status":"completed",
 "details":{"quality_passed":true,"recognition_correct":true}}
```

规则：

- `checkpoint_id` / `record_kind` / `status` 必须是该赛道任务包允许的值（本地 `validate --track s05` 会拦）；
- 没有被任何 `checkpoint_result` 覆盖的检查点 → agent 自动补 `skipped`（如实上报未执行）；
- 控制模式仍用 `control_mode_changed`；具身/轨迹事件同 S22。

```bash
# S05（用 S05 的 spec 与 profile）
.venv/bin/python reflow/agent.py --track s05 --mode generic \
  --events logs/s05.events.jsonl \
  --evaluation-id <S05评测ID> --session-id <S05会话ID>

# 或显式指定
.venv/bin/python reflow/agent.py --mode generic --profile S05-v1 \
  --spec reflow/s05_spec.json ...
```

赛道预设：`--track s22|s05`；对应的 bootstrap 命令也支持 `--track s05`（任务目录过滤 `INSPECTION_ANALYSIS`、默认校验 `s05_spec.json`）。

## 9. 验证记录（2026-10-21）

- 001/007 合成录像 → `match_webcam.py --events-jsonl`：11 条事件（run_start → exhibit_unknown → exhibit_stable ×2 → narration ×2 → run_end）；
- `guide_cli.py --ask`：命中写 `qa_answered`（含 exhibit_id/hit_score/延迟），未命中写 `qa_unanswered`（below_threshold）；
- 合并相机 + 问答事件跑 `agent.py`：P1 completed、P2 completed、其余 skipped，任务 `partial`，spec 校验 0 问题；
- `agent.py --send` 用本地 mock 服务验证请求序列：POST running → POST 终态 → GET status；
- `asr_qa.py` 用 `--asr-cmd "echo 徐光启是谁"` 验证：`asr_transcript` → `qa_answered`（details.asr 含 backend/latency/audio），未命中走 `qa_unanswered`；无引擎时打印安装指引并非零退出。
