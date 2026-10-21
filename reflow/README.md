# reflow —— 平台在线回流工具链（S22 文旅导览 / S05 质检检测）

把机器人运行数据转成「具身智能评测管理平台」要求的在线回流上报。

## 文件

| 文件 | 作用 |
| --- | --- |
| `agent.py` | 事件 JSONL → 三类上报（report / embodied / trajectory）。默认 dry-run，`--send` 才联网；spec 感知校验 |
| `sdk_bridge.py` | G1 实机具身桥（unitree_sdk2py 只读订阅 `rt/lowstate` + `rt/lf/bmsstate`），5Hz 写 `embodied_sample` |
| `asr_qa.py` | 语音问答适配器（可插拔 ASR 命令 → 检索回答 → `qa_*` 事件）；依赖交付包内的 `guide_cli.py` |
| `s22_spec.json` / `s05_spec.json` | 两个赛道的任务包规范化快照（检查点/状态/评分），用于离线校验 |
| `checkpoint_map.yaml` | S22 检查点 ↔ 本地事件映射（语义参考） |
| `examples/` | report / trajectory / embodied 可校验样例（占位值需替换） |
| `tests/` | 离线单测（`python -m unittest discover -s reflow/tests`） |

## 两条赛道

| 赛道 | profile | 事件模式 | 说明 |
| --- | --- | --- | --- |
| S22 文旅导览 | `S22-v1` | `--mode auto`（默认） | 相机/问答事件聚合为 P1 定点讲解、P2 问答… |
| S05 质检检测 | `S05-v1` | `--mode generic` | 事件显式携带 `checkpoint_record`（checkpoint_id/record_kind/status） |

## 用法

```bash
# 1) 采集事件（相机进程已支持 --events-jsonl；S05 由对应流程模块写 checkpoint_record）
python3 .../match_webcam.py --templates <模板目录> --camera 0 --log-jsonl logs/run.jsonl

# 2) 实机具身（只读，不控制机器人）
python3 reflow/sdk_bridge.py --duration 900 --mode autonomous --out logs/robot.events.jsonl

# 3) 生成并校验（不联网）
python3 reflow/agent.py --track s22 --events logs/run.events.jsonl logs/robot.events.jsonl \
  --evaluation-id <评测ID> --session-id <会话ID> --out-dir logs/reflow_agent

# 4) 发送（确定性 ID，重跑安全）
python3 reflow/agent.py ... --send --api-key-file ~/.gdps/api_key

# 5) 收尾核对
python3 tools/reflow_bootstrap.py status --session-id <会话ID>
```

S05 示例：

```bash
python3 reflow/agent.py --track s05 --mode generic \
  --events logs/s05.events.jsonl \
  --evaluation-id <S05评测ID> --session-id <S05会话ID>
```

## 关键约束（来自平台实测）

- 每请求带 `X-API-Key`；建会话带 `Idempotency-Key`（8–128 字符）；一个评测任务只绑一个会话；
- 单批 ≤200 条、请求 ≤1 MiB；`report_id`/`record_id` 幂等；检查点终态**不可覆盖**；
- `joint_names` 必须在批次级，样本内不允许（否则 422）；
- `upload_window` 实测约 7 天（创建即开）。

## 文档

- `docs/DATA_REFLOW_PLAN.md`：实施规划（双赛道、实测回执语义、风险与 Runbook）
- `docs/GUIDE_EVENTS_v1.md`：事件契约（字段/类型/检查点判定/通用模式）
- `docs/RUNBOOK_S22.md`：S22 现场一页纸
