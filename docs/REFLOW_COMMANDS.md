# 数据采集与上传指令手册（GDPS 2026 · S22 文旅导览 / S05 质检检测）

> 版本 v1.0 · 2026-10-22
> 配套：`reflow/README.md`、`docs/GUIDE_EVENTS_v1.md`、`docs/DATA_REFLOW_PLAN.md`
> 适用：Mac 本机 + 宇树 G1 实机（`unitree@192.168.123.164`，DDS 网口 `eth0`）

---

## 0. 前置

```bash
# 工作目录（仓库布局）
cd ~/gdps-2026-embodied-ai

# 或交付包布局（gdps_tourism_camera/ 下）
# cd ~/Downloads/导览图

export GDPS_BASE_URL="https://platform.ieic.gdps.org.cn/api/v1"
export GDPS_API_KEY_FILE="$HOME/.gdps/api_key"     # chmod 600，不要入库
PY=.venv/bin/python                                  # 本机；机器人用 python3
```

平台入口：https://platform.ieic.gdps.org.cn
目录/预览/建会话/上传均需要队伍 API Key（工作后台 → 在线回流 API Key）。

两个赛道的固定参数（预览会随发布更新，以会话冻结包为准）：

| 赛道 | scene_code | task_code | profile | benchmark_task_id |
| --- | --- | --- | --- | --- |
| S22 文旅导览 | `CULTURAL_TOURISM_EDUCATION` | `task-42c172c6ac7c-1` | `S22-v1` | `df983fd4-85b5-4ae3-a99b-a3477427d72e` |
| S05 质检检测 | `INSPECTION_ANALYSIS` | `task-8ae947c07912-1` | `S05-v1` | `7d7ea4d7-702e-4c3c-ab84-62da90e75a29` |

---

## 1. 数据采集

采集统一输出 **JSONL 事件文件**（每行一个事件，字段含 `schema_version/seq/ts/type`），由第 2 步的 agent 聚合上报。

### 1.1 相机 + 讲解（S22 P1 定点讲解）

```bash
# 直接调入口（推荐，参数完整）
$PY scripts/tourism/match_webcam.py \
  --templates . --camera 0 \
  --method orb --prefilter orb --match-every 2 \
  --control-mode autonomous \                # 只有真实以该模式运行才写
  --log-jsonl logs/run_$(date +%H%M).jsonl    # 自动生成同名 .events.jsonl
```

```bash
# 单图验收（不产生事件）
$PY scripts/tourism/match_webcam.py --templates . --image 001.jpg

# 录像回放（彩排/离线验证）
$PY scripts/tourism/match_webcam.py --templates . --video demo.mp4 --headless
```

Mac 启动脚本同样支持透传：`./run_mac_camera.sh --events-jsonl logs/run.events.jsonl --control-mode autonomous`
（Linux/G1：`./run_linux_camera.sh ...` 原样透传。）

产出事件：`run_start`、`exhibit_stable`、`narration_start/end`、`exhibit_left`、`exhibit_unknown`、`control_mode_changed`、`run_end`。

### 1.2 文本问答（S22 P2 问答）

```bash
# 单问
$PY guide_cli.py --ask "徐光启是谁" --events-jsonl logs/qa.events.jsonl

# 多问 / 预置清单（每行一个，# 注释）
$PY guide_cli.py --ask "豫园仰山堂宴会图讲的是什么" --ask "今天天气怎么样" \
  --events-jsonl logs/qa.events.jsonl
$PY guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl

# 交互模式（逐条写事件）
$PY guide_cli.py --interactive --events-jsonl logs/qa.events.jsonl
```

产出事件：`qa_answered`（details 含 question/exhibit_id/hit_score/response_latency_s/top_candidates）、`qa_unanswered`。

### 1.3 语音问答（S22 P2，可选）

需自备 ASR 引擎（whisper.cpp / faster-whisper / vosk / 云端 CLI 均可），占位符 `{audio}` `{lang}` `{out}`：

```bash
export GDPS_ASR_CMD="whisper-cli -m /path/ggml-base.bin -f {audio} -l {lang} -otxt -of {out}"

# 已有音频
$PY reflow/asr_qa.py --audio logs/q.wav --events-jsonl logs/qa.events.jsonl

# 现场录音（需 ffmpeg/arecord/sox 之一）
$PY reflow/asr_qa.py --record 5 --events-jsonl logs/qa.events.jsonl

# 无引擎时验证链路
$PY reflow/asr_qa.py --audio logs/q.wav --asr-cmd "echo 徐光启是谁" --events-jsonl /tmp/qa.jsonl
```

产出：`asr_transcript`（诊断）+ `qa_answered/qa_unanswered`（带 `asr` 元信息）。

### 1.4 实机具身数据（G1，机器人上运行）

只读订阅，**不发任何控制指令**，不会让机器人运动：

```bash
# 机器人上（需要 unitree_sdk2py；DDS 网口默认 eth0）
ssh unitree@192.168.123.164
cd ~/gdps_reflow
python3 reflow/sdk_bridge.py \
  --duration 900 \                # 0 = 跑到 Ctrl+C
  --embodied-hz 5 \
  --mode autonomous \              # autonomous | teleoperation | assisted | unknown
  --out logs/robot.events.jsonl
```

订阅：`rt/lowstate`（35 电机 q/dq/tau + IMU）、`rt/lf/bmsstate`（电量 soc）。
产出事件：`embodied_sample`（joint_positions/velocities/efforts、battery_pct、sensors{imu_rpy,imu_gyro,imu_acc,motor_temp_max_c,motor_vol_min_v}）。
自带统计：`[done] samples=... rate=...Hz lowstate=... bms=...`。

### 1.5 轨迹（暂未接）

`/dog_odom` 的 ROS2 订阅在本机 G1 环境会报 `bad_alloc`（foxy + cyclonedds 组合问题），轨迹通道先不传（平台 `required=false`）。需要时用 SDK `rt/odommodestate`/导航里程计另行适配。

### 1.6 事件文件清单

| 文件 | 来源 | 内容 |
| --- | --- | --- |
| `logs/run_<HHMM>.events.jsonl` | 相机进程 | P1 讲解相关 |
| `logs/qa.events.jsonl` | guide_cli / asr_qa（追加写） | P2 问答 |
| `logs/robot.events.jsonl` | sdk_bridge | 具身时序 |
| `logs/reflow/` | bootstrap / agent（自动） | 请求/响应/request_id 审计 |

---

## 2. 上传数据（在线回流 API）

### 2.1 查目录 / 预览任务包

```bash
# 目录（默认 S22；--track s05 查质检）
$PY tools/reflow_bootstrap.py --track s22 tasks
$PY tools/reflow_bootstrap.py --track s05 tasks

# 预览任务包（morphology：humanoid/quadruped/wheeled/other）
$PY tools/reflow_bootstrap.py --track s22 preview \
  --benchmark-task-id df983fd4-85b5-4ae3-a99b-a3477427d72e --morphology humanoid
```

### 2.2 建会话（每场一次；一个评测任务只能绑一个会话）

```bash
EVAL='<评测中心拿到的 evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"

$PY tools/reflow_bootstrap.py --track s22 session \
  --evaluation-id "$EVAL" --morphology humanoid --idempotency-key "$IDEM"
```

必须核对返回：`reporting_profile_version` **等于 S22-v1**（S05 则为 S05-v1）；`upload_window` 记录到当班记录。
不一致 → **停手**，说明评测任务选错赛道，回评测中心重新发起。

### 2.3 拉冻结任务包（每场以它为准）

```bash
$PY tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"
```

核对 6 个检查点、状态字典、通道窗口；与预览快照 diff 不一致时以冻结包改映射。

### 2.4 生成并校验上报（dry-run，不联网）

```bash
$PY reflow/agent.py --track s22 \
  --events logs/run_$(date +%H%M).events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" \
  --out-dir logs/reflow_agent --note "10/23 第N场"
```

看到 `[OK] payload 校验通过`、检查点统计、`dry-run：未联网` 后再发送。
产物：`report-start.json`、`report-final.json`、`embodied-*.json`、`trajectory-*.json`。

### 2.5 发送

```bash
$PY reflow/agent.py --track s22 \
  --events logs/run_$(date +%H%M).events.jsonl logs/qa.events.jsonl logs/robot.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" \
  --send --api-key-file ~/.gdps/api_key
```

- 顺序：running 报告 → 具身批次 → 终态报告（含全部 `checkpoint_result`）→ 自动查 status；
- 已发过 running 想补发终态：加 `--skip-start`；
- `report_id`/`record_id` 确定性生成，**同一条命令重跑安全**（服务端幂等）。

### 2.6 收尾核对

```bash
$PY tools/reflow_bootstrap.py --track s22 status --session-id "$SESSION_ID"
```

| 字段 | 通过标准 |
| --- | --- |
| `intake.completeness_status` | `complete` |
| `intake.missing_checkpoint_ids` | `[]` |
| `intake.sequence_gaps` | `[]` |
| `review.status` | `draft/pending` 属正常；最终以 `published` 为准 |

缺项：新报告 + 新 `record_id` 补传；**不要改已提交终态**（会 409）。

### 2.7 网页通道（非 API，人工操作）

| 通道 | 入口 | 内容 |
| --- | --- | --- |
| 训练数据 | 数据中心 → 上传训练数据 | 数据集名称/构型/格式/场景/任务 |
| 模型登记 | 模型中心 → 登记模型 | 未登记无法发起评测 |
| 评测数据文件 | 评测中心 → 对应评测任务 → 上传评测数据文件 | 多视角录像、重点点位影像、空间修正数据（赛后 15 分钟内） |

---

## 3. 完整示例

### 3.1 S22 一场（比赛当天）

```bash
# ① 评测中心发起正式评测 → 复制 evaluation_id
EVAL='<evaluation_id>'

# ② 建会话（只建一次）
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"
$PY tools/reflow_bootstrap.py --track s22 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"
SESSION_ID='<返回的 session_id>'
$PY tools/reflow_bootstrap.py --track s22 package --session-id "$SESSION_ID"

# ③ 开录 + 采集（并行）
$PY scripts/tourism/match_webcam.py --templates . --camera 0 \
  --control-mode autonomous --log-jsonl logs/run_$(date +%H%M).jsonl &
# 机器人上：python3 reflow/sdk_bridge.py --duration 900 --mode autonomous --out logs/robot.events.jsonl

# ④ 问答（按现场情况）
$PY guide_cli.py --questions questions.txt --events-jsonl logs/qa.events.jsonl

# ⑤ 结束：生成 → 发送 → 核对
$PY reflow/agent.py --track s22 --events logs/run_*.events.jsonl logs/qa.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --out-dir logs/reflow_agent
$PY reflow/agent.py --track s22 --events logs/run_*.events.jsonl logs/qa.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send --api-key-file ~/.gdps/api_key
$PY tools/reflow_bootstrap.py --track s22 status --session-id "$SESSION_ID"
```

### 3.2 S05 一场（通用模式）

S05 由质检流程模块写事件（每条 = 一个检查点记录）：

```bash
# logs/s05.events.jsonl 每行示例：
# {"schema_version":"1.0","seq":3,"ts":"2026-10-23T10:00:20.000+08:00",
#  "type":"checkpoint_record","checkpoint_id":"S05-P1",
#  "record_kind":"checkpoint_result","status":"completed",
#  "details":{"quality_passed":true,"recognition_correct":true}}

EVAL='<S05 evaluation_id>'
IDEM="s05-$(printf %s "$EVAL" | cut -c1-8)-session-create"
$PY tools/reflow_bootstrap.py --track s05 session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"
SESSION_ID='<返回的 session_id>'

$PY reflow/agent.py --track s05 --mode generic \
  --events logs/s05.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --out-dir logs/reflow_agent
$PY reflow/agent.py --track s05 --mode generic \
  --events logs/s05.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send --api-key-file ~/.gdps/api_key
$PY tools/reflow_bootstrap.py --track s05 status --session-id "$SESSION_ID"
```

未被 `checkpoint_result` 覆盖的检查点会被自动补 `skipped`（如实上报未执行）。

---

## 4. 常见错误与处置

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 401 `INVALID_API_KEY` | Key 缺失/无效/已撤回 | 检查 `~/.gdps/api_key`（600） |
| 422 且 `field_errors` 指向 header | 没带 `X-API-Key` | 同上 |
| 422 `INVALID_STATUS` | 检查点状态/类型不匹配任务包 | 按 `reflow/s22_spec.json` / `s05_spec.json` 填；先本地 `validate` |
| 409 已绑定会话 | 重复建会话 | 用已有 `session_id`，不要换幂等键 |
| 409 相同 report_id 不允许不同内容 | 重试时改了内容 | 原内容重试；新事实用新 report_id/record_id |
| 409 记录与已有事实冲突 | 重复提交检查点终态 | 终态不可改；更正联系赛事方 |
| 410 | 窗口未开/已关 | 核对 `upload_window`（实测 7 天） |
| TLS 证书错误（本机 python） | 系统 python 无 CA | 用 `.venv/bin/python`（含 certifi）或临时 `--insecure`（仅联调） |

字段硬规则：`joint_names` 必须在批次级（样本内出现会 422）；单批 ≤200 条、≤1 MiB；`details` 是开放对象，`sensors` 同理。

---

## 5. 安全与命名

- Key 只放 `~/.gdps/api_key`（`chmod 600`），不入库、不发群；赛后轮换；
- 录像命名 `<evaluation_id>_cam<机位>_<YYYYmmdd-HHMM>.mp4`；
- 每场归档：事件 JSONL + `logs/reflow/` + status.json + 录像 + 映射版本；
- 测试评测可以写测试数据，但**正式评测只上报真实执行数据**；做不了的检查点如实 `skipped/failed`。

---

## 附录 A：S22 / S05 检查点速查

S22（自动 25 / 人工 75）：P1 定点讲解、P2 问答、P3 多语言、P4 跟随避让、P5 途中互动、P6 销售推荐。
S05（自动 85 / 人工 15）：P1 样品接收与取样、P2 前处理、P3 试管排序/离心机装载、P4 取出归位、P5 样品状态、P6 判定分拣与报告。

状态字典、details 指标以每场**冻结任务包**为准（`reflow/s22_spec.json`、`reflow/s05_spec.json` 为快照）。
