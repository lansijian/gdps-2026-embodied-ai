# S22 文旅导览 · 现场一页纸 Runbook（v1.0 · 2026-10-21）

> 打印建议：A4 单页、双面；每场按顺序打勾。配套：`docs/DATA_REFLOW_PLAN.md`、`docs/GUIDE_EVENTS_v1.md`
> 本文针对 **S22 文旅导览**；**S05 质检检测**（85 分自动）用 `--track s05 --mode generic`，检查点/评分见规划 §1.7。

## 0. 赛前 24h（10/22）必须完成

- [ ] 训练数据已上传并核对（数据中心）
- [ ] 参赛模型已登记（模型中心；未登记无法发起评测）
- [ ] 测试评测跑通：`profile=S22-v1`、`completeness=complete`、`missing=[]`、`gaps=[]`
- [ ] API Key 已备份（`~/.gdps/api_key`，600 权限，不入库）
- [ ] 代码/配置/映射打包 `backup/reflow-v1-<日期>.tar.gz`，校验和记录
- [ ] 现场设备：摄像头识别 OK、磁盘 ≥20GB、`timedatectl` 校时、充电/网络

## 1. 每场时间轴（T = 开跑时刻）

| 时刻 | 动作 | ✅ |
| --- | --- | --- |
| T-60 | 场地检查：`curl -sS -o /dev/null -w '%{http_code}' https://platform.ieic.gdps.org.cn/`；网络/电源/摄像头/时间/磁盘/Key | ☐ |
| T-45 | 评测中心 → 发起**正式评测**（S22、模型、构型 humanoid）→ 复制 `evaluation_id` | ☐ |
| T-40 | 建会话（命令卡 2）→ **核对返回 `reporting_profile_version=S22-v1`**，否则停手上报 | ☐ |
| T-35 | 拉冻结任务包，与 `logs/spec/` 快照 diff（6 检查点/状态/通道）；确认 `robot_profile` 与实机一致 | ☐ |
| T-30 | 开录（记 `t0`）→ 启动相机进程（带 `--events-jsonl`、`--control-mode`）→ 发 running | ☐ |
| T-0 | 开始导览：P1 定点讲解 → P2 问答 → P3 多语言 → P4 跟随避让 → P5 途中互动 → P6 销售推荐 | ☐ |
| T+0 | 停止采集 → 终态报告（6 个 `checkpoint_result`；做不了的 `skipped/failed` 如实填） | ☐ |
| T+10 | `status` 核对：`completeness=complete`、`missing=[]`、`gaps=[]`；缺项用新 `record_id` 补传 | ☐ |
| T+15 | 评测中心上传**评测数据文件**（多视角录像/重点点位影像/空间修正）→ 核对与评测 ID 关联 | ☐ |
| T+30 | 归档 `logs/reflow/`、`status.json`、录像、映射版本；任务卡备注 `session_id`/`request_id` | ☐ |

## 2. 命令卡（复制即可）

```bash
cd /Users/tostar/Downloads/导览图
export GDPS_API_KEY="$(cat ~/.gdps/api_key)"
PY=.venv/bin/python

# 1) 目录（可选，确认赛道在线）
$PY tools/reflow_bootstrap.py tasks

# 2) 建会话（把 EVAL 换成评测 ID；同一评测只用一次该幂等键）
EVAL='<evaluation_id>'
IDEM="s22-$(printf %s "$EVAL" | cut -c1-8)-session-create"
$PY tools/reflow_bootstrap.py session --evaluation-id "$EVAL" \
  --morphology humanoid --idempotency-key "$IDEM"

# 3) 冻结任务包（核对后开跑）
$PY tools/reflow_bootstrap.py package --session-id "$SESSION_ID"

# 4) 生成并校验上报（dry-run；events 可多份）
$PY reflow/agent.py --events logs/run.events.jsonl logs/qa.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --note "10/23 第N场"

# 5) 发送（先 running，后终态；同一条命令重跑安全）
$PY reflow/agent.py --events logs/run.events.jsonl logs/qa.events.jsonl \
  --evaluation-id "$EVAL" --session-id "$SESSION_ID" --send --api-key-file ~/.gdps/api_key

# 6) 收尾核对
$PY tools/reflow_bootstrap.py status --session-id "$SESSION_ID"
```

## 3. 六个检查点：做什么、怎么记

| 检查点 | 现场动作 | 事件来源（自动写） | 判定 |
| --- | --- | --- | --- |
| P1 定点讲解 | 对准展品 → 稳定识别 → 播报讲解 | `exhibit_stable/narration_*` | 有 narration_end=completed |
| P2 问答 | 游客提问 → 键入/ASR → 回答 | `qa_answered/unanswered` | 有 answered=completed |
| P3 多语言 | 切换语种 → 播报 | `language_switched`（需模块） | 有 switched=completed |
| P4 跟随避让 | 跟随游客/绕障 | `tracking_*`（需底盘） | finished 且无 collision=completed |
| P5 途中互动 | 招手/驻足互动 | `interaction_*`（需模块） | finished=completed |
| P6 销售推荐 | 推荐周边景点/消费 | `recommendation_provided`（需模块） | provided=completed |

> 做不了的环节：如实 `skipped/failed` + `completion_note` 说明，**不要漏报**（漏报触发缺失门槛）。

## 4. 故障分支（30 秒决策）

| 现象 | 判定 | 处置 |
| --- | --- | --- |
| 建会话返回 profile ≠ `S22-v1` | 评测任务选错赛道 | **停手**，不上报；回评测中心重新发起（会话不可解绑） |
| `409 已绑定回流会话` | 重复建会话 | 用已有 `session_id`，不要换幂等键 |
| `409 相同 report_id 不允许不同内容` | 重试时改了内容 | 用原内容重试；补新事实换新 `report_id`/`record_id` |
| `409 记录…与已有事实冲突` | 重复提交检查点终态 | 终态不可改；如需更正联系赛事方 |
| `410` | 窗口未开/已关 | 核对 `upload_window`（实测 7 天）；联系赛事方 |
| `422` | 字段/状态不合法 | 看 `error.code/field_errors`；本地先 `validate` 拦住 |
| 网络中断 | 超时/503 | agent 重试；仍失败保留事件文件，恢复后重跑（幂等） |
| 漏检查点 | `missing` 非空 | 新报告 + 新 `record_id` 补传，别改已提交终态 |
| 自动分 pending | `draft_ready` 但未出分 | 正常：自动分在评审/发布阶段结算 |

## 5. 命名与归档

- 录像：`<evaluation_id>_cam<机位>_<YYYYmmdd-HHMM>.mp4`
- 事件：`logs/run_<HHMM>.events.jsonl`、`logs/qa.events.jsonl`
- 审计：`logs/reflow/`（请求/响应/`request_id`）、`logs/reflow_agent/`
- 归档包：`archive/<日期>_<evaluation_id>.tar.gz`（录像 + 事件 + status + 映射版本）

## 6. 分工（现场填写）

| 角色 | 姓名 | 电话 |
| --- | --- | --- |
| 指挥/决策 | | |
| 机器人操作 | | |
| 回流/网络 | | |
| 录像/证据 | | |
| 赛事方联系人 | | |
