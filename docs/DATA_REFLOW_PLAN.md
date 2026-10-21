# GDPS 2026 S22 文旅导览 · 数据回流实施规划

> 版本 **v1.6** · 编制 2026-10-21 17:20（Asia/Shanghai）
> 变更：v1.1 实测任务包；v1.2 写接口语义；v1.3 采集+上报；v1.4 P2 问答与合并；v1.5 ASR 适配器 + Runbook；v1.6 **双赛道支持**（新增 S05 质检检测：spec、评分结构、通用事件模式）
> 适用：本仓库（`gdps-2026-embodied-ai` / `feat/tourism-exhibit-camera-matching`）的展品识别导览系统
> 目标：10/22 前完成回流联调；10/23—25 每场导览的 6 个检查点都能完整、如实、可核对地回流
> 依据：平台 OpenAPI、参赛团队操作手册、以及 **2026-10-21 16:25 用 API Key 实测的任务包**（快照见 `logs/spec/`）

---

## 0. 一页速览（决策摘要）

| 项 | 结论 |
| --- | --- |
| 赛道（本队两个） | **S22 文旅导览**：`scene_code=CULTURAL_TOURISM_EDUCATION`、`task_code=task-42c172c6ac7c-1`、`profile=S22-v1`；**S05 质检检测**：`scene_code=INSPECTION_ANALYSIS`、`task_code=task-8ae947c07912-1`、`profile=S05-v1`（见 §1.7） |
| 任务包 | `benchmark_task_id=df983fd4-85b5-4ae3-a99b-a3477427d72e`，**6 个检查点**：P1 定点讲解、P2 问答、P3 多语言、P4 跟随避让、P5 途中互动、P6 销售推荐 |
| 分数结构 | S22：任务执行 65 + 具身 5 + 自主 20 + 创新 10 → **自动 25 / 人工 75**；S05：任务执行 55 + 具身 10 + 自主 30 + 创新 5 → **自动 85 / 人工 15** |
| 主通道 | 在线回流 API；任务与检查点走 `/reflow/tasks/report`，具身时序走 `/reflow/embodied/batch`，轨迹走 `/reflow/trajectories/batch` |
| 强制约束 | 一评测任务一会话；每请求带 `X-API-Key`；建会话带 `Idempotency-Key`(8–128)；单批 1–200 条；`report_id`/`record_id` 幂等；**检查点终态不可覆盖** |
| 建会话实测 | 201 返回 `session_id` + `reporting_profile_version` + `upload_window`（实测**创建即开启、7 天后关闭**）；同键同体重放返回首次回执；同键异体 409；换键重复绑定 409 |
| ⚠️ 赛道自检 | 用 S05 测试评测实测：建会话返回 `S05-v1`——**返回 profile 是“赛道是否选对”的唯一硬信号**；不是 `S22-v1` 就立刻停手，不要上报数据 |
| 通道要求（实测） | `tasks.required=true`；`trajectories/embodied/files` 均为 `required=false`（但具身自动分 5 分，实际必须传） |
| 本项目最大风险 | 本目录只覆盖 P1 定点讲解与部分 P2 问答；**P3 多语言、P4 跟随避让、P5 途中互动、P6 销售推荐 在仓库里没有对应能力**——回流规划必须先把“6 个检查点如实上报”打通，不能等能力补齐才做 |
| 自动分三件事 | ① 不漏 `end_at`（完成时间 5）② 轨迹/具身/影像持续回流（具身 5）③ P4 观测记录 + 轨迹 + 录像（动线避障 15） |
| 时间压力 | 今天 10/21；10/22 是联调与训练数据/模型登记硬截止；10/23—25 正式赛 |
| 交付物 | 本规划 + [现场一页纸 Runbook](RUNBOOK_S22.md) + [事件契约](GUIDE_EVENTS_v1.md) + `tools/reflow_bootstrap.py` + `reflow/agent.py` + `reflow/asr_qa.py` + `reflow/checkpoint_map.yaml` + `reflow/s22_spec.json` + `logs/spec/` 快照 |

> **一句话结论**：回流的技术路径已经打通并可离线自检；真正的风险在“6 个检查点对应的能力”和“现场执行纪律”，不在接口。

---

## 1. 平台事实基线

### 1.1 平台与赛道（已实测）

- 平台：**具身智能评测管理平台**（https://platform.ieic.gdps.org.cn），首页概述“标准化测评五步法”。
- 目录查询实测（`GET /api/v1/reflow/tasks`）：
  - 用 `scene_code=cultural_services` + `task_code=cultural_tour` 查 → **0 条**；
  - 用 `scene_code=CULTURAL_TOURISM_EDUCATION` 或 `q=文旅` 查 → 命中 **S22 文旅导览**（另有 S23 科教培训）。
  - S22 返回：`benchmark_task_id=df983fd4-85b5-4ae3-a99b-a3477427d72e`、`reporting_profile_version=S22-v1`、`benchmark_version=1`。
- 任务包实测（`GET /reflow/tasks/{id}/task-package?morphology=humanoid`）：`is_preview=true`、6 检查点、评分 100 分、`frames=[]`、`robot_profile=null`、`channels.opens_at/closes_at=null`。
- 机器形态：`morphology` 只影响 `scoring.morphology` 字段，**检查点/状态/指标不随形态变化**；本队用 **humanoid**（宇树 G1）。
- 官方在线文档：Swagger `https://platform.ieic.gdps.org.cn/api/v1/reflow/docs`；OpenAPI `.../api/v1/reflow/openapi.json`。
- 操作手册（V1.0，2026-10-19）：`https://platform.ieic.gdps.org.cn/introduction/具身智能评测管理平台参赛团队操作手册.docx`（可直接下载）。
- 教程视频：`/introduction/tutorials/0{1..4}-*.mp4`（在线回流 API / 评测数据集上传 / 模型与评测 / 专家评分）。

### 1.2 赛程与硬节点（手册）

| 环节 | 时间 | 要求 |
| --- | --- | --- |
| 训练数据上传 | 10/22 前 | 上传并核对 |
| 模型登记 | 10/22 前 | 未登记模型**无法提交评测任务** |
| 回流 API 联调 | 10/22 前 | 接入 + 测试评测 + 回流验证 |
| 正式评测提交 | 10/23—25 开赛前 | 获取正式 `evaluation_id` |
| 评测数据文件上传 | 每场结束后及时 | 与评测 ID 关联，确认成功 |
| 评分与榜单 | 成绩发布后 | 评测中心 + 首页 GDPS 赛事榜单 |

### 1.3 八个接口（全部需 `X-API-Key`）

| # | 方法 | 路径 | 用途 | 备注 |
| --- | --- | --- | --- | --- |
| 1 | GET | `/reflow/tasks` | 任务目录 | `page/page_size/q/scene_code/task_code` |
| 2 | GET | `/reflow/tasks/{benchmark_task_id}/task-package` | 预览任务包 | `morphology`；`is_preview=true` |
| 3 | POST | `/reflow/sessions` | 绑定评测任务建会话 | `{evaluation_id, morphology}` + `Idempotency-Key`；201 |
| 4 | GET | `/reflow/sessions/{session_id}/task-package` | 会话冻结任务包 | **每场以它为准** |
| 5 | POST | `/reflow/tasks/report` | 进度/检查点/控制模式 | 终态决定评分完整性 |
| 6 | POST | `/reflow/trajectories/batch` | 轨迹 | 1–200 点/批 |
| 7 | POST | `/reflow/embodied/batch` | 关节/电量/模式/传感器 | 1–200 采样/批 |
| 8 | GET | `/reflow/sessions/{session_id}/status` | 接收量/缺失/缺口/评分/评审 | 收尾核对 |

### 1.4 请求/响应与错误（实测 + 文档）

- 成功 `{"data":{...},"request_id":"..."}`；失败 `{"error":{"code","message","details","field_errors":[]},"request_id":"..."}`。
- 时间 ISO 8601 带时区；请求体不接受未定义字段（`details`/`sensors`/证据引用为开放对象）；`schema_version` 固定 `"1.0"` 也必须传。
- 实测（2026-10-21）：
  - 缺 `X-API-Key` → **422** `VALIDATION_ERROR`，`field_errors[0].field="header.X-API-Key"`；
  - 无效 Key → **401** `INVALID_API_KEY`（“API Key 无效或已撤销”）；
  - 有效 Key → 目录/任务包 200，`request_id` 可用于追踪；
  - 用不存在的 `evaluation_id` 建会话 → **404** `请先在评测中心创建评测任务`（说明会话接口链路、请求头与幂等键均已打通，只差真实评测 ID）。
- 会话幂等实测（2026-10-21 16:29，S05 测试评测）：
  - 同 `Idempotency-Key` + 同请求体重放 → **201**，返回**首次** `session_id`（不新建）；
  - 同键 + 不同请求体 → **409** `同一 Idempotency-Key 不能用于不同请求`；
  - 换新键再次绑定同一评测 → **409** `该评测任务已绑定回流会话，请使用已有会话`；
  - `upload_window`：创建时刻开启，**+7 天**关闭（例：10-21 16:29 → 10-28 16:29 +08:00）。
- 错误码：401/403/404/409/410/422/500/503（含义见 §12.B）。

### 1.5 任务包实测结果（关键事实，务必以本表为工作基线）

检查点（`record_kinds` 决定你能上报哪类记录）：

| 检查点 | 名称 | 允许 record_kind | 允许状态（checkpoint_result） | 对应评分项（人工） |
| --- | --- | --- | --- | --- |
| S22-P1 | 定点讲解 | attempt / observation / checkpoint_result | completed / partial / failed / skipped / unknown | P1 游客日常问答服务 10 分 |
| S22-P2 | 问答 | observation / checkpoint_result | 同上 | P2 导航引导讲解服务 15 分 |
| S22-P3 | 多语言 | attempt / observation / checkpoint_result | 同上 | P3 沿途讲解服务 5 分 |
| S22-P4 | 跟随避让 | observation / checkpoint_result | 同上 | P4 动态路径规划及避障 5 分 |
| S22-P5 | 途中互动 | observation / checkpoint_result | 同上 | P5 周边景点与消费推荐 10 分 |
| S22-P6 | 销售推荐 | observation / checkpoint_result | 同上 | P6 服务交互自然度 15 分 |

各检查点的过程状态（attempt/observation）按场景不同：

| 检查点 | attempt 允许状态 | observation 允许状态 |
| --- | --- | --- |
| P1 定点讲解 | speech_started / speech_finished / speech_failed / failed / unknown / aborted | speech_started / speech_finished / speech_failed / failed / unknown |
| P2 问答 | — | answered / unanswered / failed / unknown |
| P3 多语言 | language_switched / switch_failed / failed / unknown / aborted | language_switched / switch_failed / failed / unknown |
| P4 跟随避让 | — | tracking_started / tracking_lost / tracking_recovered / tracking_finished / collision / failed / unknown |
| P5 途中互动 | — | interaction_started / interaction_finished / no_response / failed / unknown |
| P6 销售推荐 | — | recommendation_provided / no_recommendation / failed / unknown |

评分结构（`scoring.modules`，`rule_version=competition-rules-v2.0-20261009-r3`）：

| 模块 | 权重 | 评分项（分值/自动?/策略） |
| --- | --- | --- |
| 任务执行 | 65 | 完成时间 5/**自动**/time；P1 10/人工；P2 15/人工；P3 5/人工；P4 5/人工；P5 10/人工；P6 15/人工 |
| 具身数据采集与回流 | 5 | 移动轨迹、运行状态、影像等采集回流 5/**自动**/embodied_data |
| 自主智能 | 20 | 理解场景指令 5/人工/semantic；动线避障与通行安全 15/**自动**/avoidance |
| 创新能力 | 10 | 自选创新动作 10/人工 |

其他事实：

- `channels`：`tasks.required=true`（≤200 记录/次，≤1 MiB）；`trajectories`、`embodied`、`files` 均 `required=false`（各自上限 200 / 1 MiB；窗口 preview 为 null）。
- `frames=[]`、`robot_profile=null`：预览不绑定坐标系与机器人配置，**建会话后必须重新拉冻结包**。
- ⚠️ 评分项名称与检查点名称编号**语义不一致**（如评分项“P1 游客日常问答服务”挂 `checkpoint_id=S22-P1` 定点讲解）。以 `checkpoint_id` 为准，但要书面向赛事方确认（见 §11）。
- `details_schema` 是通用开放对象（22 个指标：quality_passed、recognition_correct、collision_count、obstacle_handled、max_stop_seconds、entered_restricted_area、critical_takeover、safety_redline、start_delay_seconds、autonomous_start、failure_count、misclassified_count、adjustment_count、retry_count、force_limit_exceeded、drop_count、normal_removed_count、removal_failure_count、task_interrupted、valid_inspection_order、route_reasonable、critical_task_failed），`additionalProperties=true`，**不要求每个检查点填满**；填不出的留空（≠false、≠0）。

**冻结包 vs 预览（实测对比）**——每场必须以冻结包为准：

| 字段 | 预览（无会话） | 冻结包（有会话） |
| --- | --- | --- |
| `is_preview` | `true` | 无该字段 / `null` |
| `session_id` | 无 | 有 |
| `robot_profile` | `null` | 有（`model_name`、`model_profile_id`）——具身 `robot_profile_version` 的真实来源 |
| `frames` | `[]` | `[]`（本任务同样为空；轨迹 `frame_id` 按实际自定） |
| `channels.opens_at/closes_at` | `null` | 真实窗口（创建即开、+7 天关） |
| `scoring.morphology` | 随查询参数 | 随会话绑定形态 |

**status 字段位置（实测）**：缺失与缺口在 `data.intake` 下——`intake.missing_checkpoint_ids`、`intake.sequence_gaps`、`intake.completeness_status`、`intake.channels.*.accepted_count/duplicate_count`；`automatic_scoring` 未完成上传时为 `visible=false`、`visibility_reason=WAITING_FOR_COMPLETE_UPLOAD`、`status=waiting_upload`、`pending_item_count` 为全部评分项数；`review.status` 初始 `pending`。

### 1.6 实测回执与幂等/冲突语义（2026-10-21 S22 测试评测，会话 `bd8ac362…`）

用真实 S22 测试评测把四类写接口全部打通，回执与冲突语义如下（**可直接作为联调断言**）：

| 操作 | 结果 |
| --- | --- |
| `POST /reflow/tasks/report`（running） | 200：`accepted_count=1`、`scoring_status=waiting_upload`、`reason=任务尚未上报终态` |
| `POST /reflow/embodied/batch`（2 采样） | 200：`accepted_count=2`、`seq_range=[0,1]`、`duplicate_count=0` |
| `POST /reflow/trajectories/batch`（2 点） | 200：`accepted_count=2`、`seq_range=[0,1]` |
| `POST /reflow/tasks/report`（终态 + 6 个 `checkpoint_result`） | 200：`accepted_count=6`、`duplicate_count=1`、`scoring_status=draft_ready`、`pending_item_count=11`、`total_score=0.00` |
| 原样重放同一终态报告 | 200：`accepted_count=6`、`duplicate_count=1`（**不重复计数**），`score_sheet_version` 递增 |
| 已提交终态检查点换新 `record_id` 再报 | **409** `记录 … 与已有事实冲突（尝试编号或终态重复）` |
| 同 `report_id` 改内容 | **409** `相同 report_id 不允许不同内容` |
| 检查点状态与 `record_kind` 不匹配（绕过本地校验） | **422** `INVALID_STATUS`：`检查点 S22-P1 在 checkpoint_result 下不允许状态 answered`（`field_errors` 为空） |
| 收尾 `GET status` | `completeness=complete`、`missing_checkpoint_ids=[]`、`sequence_gaps=[]`、`review.status=draft` |

两条重要解读：

1. `accepted_count` 统计**记录数**（任务通道：6 个检查点记录 = 6；再加 1 条 start 报告共 7），`duplicate_count` 单独统计被去重的 record（重放的控制记录算 1 条）。
2. **上传成功 ≠ 自动分出分**：终态后 `automatic_scoring` 虽变为 `visible=true/draft_ready`，但 `scored_item_count=0`、`pending_item_count=11`（全部评分项待定），说明自动分在评审/发布阶段才结算；**不要把 `draft_ready` 当成“已得 25 分”**。

### 1.7 S05 质检检测任务包（实测，2026-10-21 17:16）

> 来源：`GET /reflow/tasks/7d7ea4d7-702e-4c3c-ab84-62da90e75a29/task-package`；快照 `logs/spec/2026-10-21_S05_*.json`，规范化 `reflow/s05_spec.json`。

| 检查点 | 名称 | 允许 record_kind | 允许状态（checkpoint_result） | 必填评分项 |
| --- | --- | --- | --- | --- |
| S05-P1 | 样品接收与取样 | attempt / observation / checkpoint_result | completed / partial / failed / skipped / unknown | P1 5 分（自动） |
| S05-P2 | 样品前处理（奶片称量 + 试管封管） | 同上 | 同上 | P2 5 分（自动） |
| S05-P3 | 试管排序与离心机装载 | 同上 | 同上 | P3 5 分（自动） |
| S05-P4 | 离心后样品取出与归位 | 同上 | 同上 | P4 5 分（自动） |
| S05-P5 | 样品状态检查 | observation / checkpoint_result | 同上 | P5 5 分（自动） |
| S05-P6 | 判定分拣与报告上传 | attempt / observation / checkpoint_result | 同上 | P6 5 分（自动） |

过程状态（摘要）：P1 `sample_received/sample_placed/sample_missing`；P2 `step_completed/step_failed/spill/broken`；P3 `tube_loaded/device_started/load_failed`；P4 `returned/not_returned/broken/spill`；P5 `normal/leaking/broken`；P6 `sorted/sort_failed/report_submitted`。

评分结构（13 项，满分 100）：

| 模块 | 权重 | 评分项（自动性/策略） |
| --- | --- | --- |
| 任务执行 | 55 | 完成时间 10（auto/time）、任务结果 15（auto/task_result）、P1–P6 各 5（auto/checkpoint） |
| 具身数据采集与回流 | 10 | 采集回流 10（auto/embodied_data） |
| 自主智能 | 30 | 理解指令 10（manual/semantic）、全程自主规划与执行 10（auto/autonomy）、动线避障 10（auto/avoidance） |
| 创新能力 | 5 | 自选创新动作 5（manual） |

**与 S22 的关键差异**：S05 **85 分自动**，且 6 个检查点全部 `required_for_scoring`（`details` 与状态直接决定得分）；S22 只有 25 分自动、75 分靠专家看录像。因此 S05 更依赖“上报事实完整 + `details` 指标准确”，而不是讲解表现。

S05 会话现状（本次实测）：`evaluation_id=6a9e25a6-c29c-4122-8a44-b6b137a147fa` 已绑定会话 `session_id=3aa4136c-ca49-4316-971d-105d67bebc46`（robot_profile=测试模型），窗口至 **10/28 16:29**；目前 `missing=S05-P1..P6`、`completeness=in_progress`（未上传任何数据）。

S05 专用事件契约（通用模式）：事件显式携带

```json
{"type":"checkpoint_record","checkpoint_id":"S05-P1","record_kind":"checkpoint_result",
 "status":"completed","details":{"quality_passed":true,"recognition_correct":true}}
```

用 `agent.py --track s05 --mode generic` 聚合；未被 `checkpoint_result` 覆盖的检查点会自动补 `skipped`（如实上报未执行）。

---

## 2. 数据回流总体模型

```
 平台网页（人工）                          机器人端（自动）
 工作后台 → API Key                 guide 进程 ──事件──► reflow-agent
 数据中心 → 训练数据                                  │
 模型中心 → 模型登记                                  ├─① POST /reflow/sessions (Idempotency-Key)
 评测中心 → 发起评测 → evaluation_id ────────────────►├─② GET  /reflow/sessions/{sid}/task-package（冻结规范）
         → 赛后上传评测数据文件                      ├─③ POST /reflow/tasks/report (running + control_records)
                                                     ├─④ POST /reflow/trajectories/batch（有位姿才传）
                                                     ├─⑤ POST /reflow/embodied/batch（具身自动分，务必传）
                                                     ├─⑥ POST /reflow/tasks/report (终态 + 全量 checkpoint_result)
                                                     └─⑦ GET  /reflow/sessions/{sid}/status → 补传/等评审
```

三条通道：在线回流 API（任务/检查点/轨迹/具身，**必接**）、训练数据（数据中心，按模型）、评测数据文件（评测中心，按任务，赛后上传）。

---

## 3. 现状盘点与本项目数据源

### 3.1 已有能力

- 感知链：摄像头/视频/RealSense → ORB 粗筛 → SIFT/ORB 精匹配 + RANSAC → `TemporalVoteFilter` 多帧投票稳定 → HUD → 讲解播报（TTS 可选）。
- 知识资产：29 张模板 → **22 个展品组**（18 展品 + 4 复合展板），`knowledge_base.json` 有中文名、触发词、讲解词、分组。
- 日志：`--log-jsonl` 逐帧 `{frame_id, match_ms, stable_id, stable_name, stable_confidence, raw}`；稳定切换打印 `[MATCH]` 并触发讲解。
- 本目录另有 `guide_cli.py` + `similarity_matcher.py`（讲解词/问答检索原型），可支撑 P2。

### 3.2 缺口（按 P0/P1）

| 优先级 | 缺口 | 影响 | 最小改法 |
| --- | --- | --- | --- |
| P0 ✅ | 日志无墙钟时间 | 所有时间字段不可用 | **已实现**：`--log-jsonl` 每帧带 `ts`（+08:00 毫秒） |
| P0 ✅ | 无结构化导览事件 | 6 个检查点无数据源 | **已实现**：`--events-jsonl` 输出 `run_start/exhibit_stable/narration_*/run_end` 等，契约见 [GUIDE_EVENTS_v1](GUIDE_EVENTS_v1.md) |
| P0 ✅ | 无回流客户端 | 无法建会话/上报 | **已实现**：`reflow/agent.py`（事件→三类上报，dry-run 校验 + `--send`），单测 5 项通过 |
| P1 | 无位姿/SLAM | 轨迹通道空 | 有定位再传；无位姿不传轨迹（`required=false`），但 P4/避障自动分要靠观测+录像 |
| P1 | 无关节/电量 | 具身自动分 5 分丢 | G1 SDK 采关节/电量；至少 `mode`+`battery_pct` |
| P1 | 录像与事件未对齐 | 人工 75 分靠证据 | 开录记 `t0`，事件与视频同源时钟；按 `evaluation_id` 命名 |
| P2 | 无断网缓冲 | 网络抖动丢数据 | SQLite spool + 幂等 ID |

### 3.3 按检查点看能力覆盖（决定 10/22 的补课优先级）

| 检查点 | 比赛要的能力 | 本目录现状 | 结论/最省做法 |
| --- | --- | --- | --- |
| P1 定点讲解 | 稳定识别展品 + 讲解 | **已具备**（识别+知识库+TTS） | 只需加时间戳/事件/上报 |
| P2 问答 | 听懂问题并回答 | **已接入**：`guide_cli.py` 检索 + 事件；`asr_qa.py` 语音→转写→回答（引擎可插拔） | 现场可键入/预置清单/语音三条入口，均写同一 `qa_answered` 事件 |
| P3 多语言 | 切换语种讲解 | **无** | 准备英/日版讲解稿 + 切换动作；先保证“能切换、能播报、有记录” |
| P4 跟随避让 | 跟随游客 + 避障 | **无**（本目录无底盘/导航） | 若底盘模块在其它仓库，接入其状态；否则如实 `skipped/failed`，不伪造 |
| P5 途中互动 | 主动互动 | **无** | 话术脚本 + 招手/驻足识别（可选）；有动作就记录观测 |
| P6 销售推荐 | 周边景点/消费推荐 | **无** | 准备推荐清单与讲解词，语音播报后按 `recommendation_provided` 记录 |

> 提示：P1—P6 的 6 个检查点是**评分锚点**，不是“必须全部完美”。做不了的按 `skipped/failed/unknown` 如实上报，专家仍可依据录像与现场表现评分；但**不要漏报**，漏报会直接触发缺失检查点门槛。

---

## 4. 数据映射设计（本地 → 平台）

### 4.1 映射策略：检查点 = 服务环节，不是展品

首版的“一展品一检查点”假设已被实测推翻：S22 的 6 个检查点是**服务能力环节**。因此：

1. `checkpoint_id` 固定为 `S22-P1…S22-P6`，语义见 §1.5；
2. 每个检查点可有多条 `attempt/observation`（过程）和**一条** `checkpoint_result`（终态，不可覆盖）；
3. 展品识别结果作为 P1 的 `details`（如 `recognition_correct`、`misclassified_count`）与 P2 的检索依据，不再作为检查点本身；
4. 每场建会话后拉冻结包再核对一遍（`checkpoint_map.yaml` 已按预览版写好，冻结版若变要同步改）。

### 4.2 字段级映射（按检查点）

| 检查点 | 本地事件源 | 上报记录 | 关键字段 |
| --- | --- | --- | --- |
| P1 定点讲解 | 稳定识别、TTS 开始/结束、离开点位 | attempt：`speech_started/finished/failed`；终态 `checkpoint_result` | `reported_at`、`details.recognition_correct/misclassified_count/failure_count/start_delay_seconds/autonomous_start` |
| P2 问答 | 游客提问、检索命中、回答结束/超时 | observation：`answered/unanswered/failed`；终态 | `details.question/answer_source/hit_score/response_latency_s`（自定义字段允许） |
| P3 多语言 | 语种切换请求/完成/失败 | attempt：`language_switched/switch_failed`；终态 | `details.language/switch_latency_s/narration_language_correct` |
| P4 跟随避让 | 跟随开始、丢失、恢复、结束、碰撞 | observation：`tracking_*`/`collision`；终态 | `details.collision_count/obstacle_handled/max_stop_seconds/entered_restricted_area/safety_redline/critical_takeover/route_reasonable` |
| P5 途中互动 | 互动开始/结束/无响应 | observation：`interaction_*`/`no_response`；终态 | `details.interaction_type/interaction_count/no_response_count`（自定义） |
| P6 销售推荐 | 推荐播报/未推荐 | observation：`recommendation_provided/no_recommendation`；终态 | `details.recommended_items/accepted_by_visitor/recommendation_basis`（自定义） |

报告级字段：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `start_at / end_at` | 开跑/结束墙钟 | 完成时间 5 分自动项依赖 `end_at`，终态报告必须填 |
| `control_records` | 接管/急停事件 | mode 仅 autonomous/teleoperation/assisted；“理解指令/自主执行”评分依据 |
| `avg_speed_mps` | 底盘里程/时间 | 有则填真实值，无则省略 |
| `completion_note` | 人工 | 缺失/降级/异常如实说明，别掩盖 |

### 4.3 自动分 25 分怎么拿（最容易丢的分）

| 自动项 | 分值 | 拿分要点 | 常见丢分 |
| --- | --- | --- | --- |
| 完成时间 | 5 | `start_at/end_at` 真实且在规则范围内 | 只报 running、终态漏 `end_at` |
| 具身数据采集与回流 | 5 | 具身批次持续到终态（mode+battery 至少，关节更好）；有影像走 files 通道 | 只报任务不报具身；`robot_profile_version` 抄了会话里的 null |
| 动线避障与通行安全 | 15 | P4 观测 + 轨迹质量 + 录像证据；`collision_count=0` 等必须真实 | 无 P4 观测、无轨迹、无录像；或填假 0 |

> 注意：实测终态后 `automatic_scoring` 仍 `pending_item_count=11`（全部待定）。自动分在评审/发布阶段结算，**联调时不要用“有没有出分”判断是否成功**，只看 `accepted_count`、`duplicate_count`、`missing_checkpoint_ids`、`sequence_gaps`、`completeness_status`。

### 4.4 通道判定

| 通道 | 判定 | 依据 |
| --- | --- | --- |
| tasks/report | **必传** | `channels.tasks.required=true`；终态+检查点完整性是评分门槛 |
| embodied | **视为必传** | 自动分 5 分；文档 `required=false` 只是“接口不强制” |
| trajectories | 按能力 | `required=false`；有可靠位姿就传（P4 自动分受益），无则不造 |
| files（评测数据文件） | **必须赛后上传** | 人工 75 分的证据来源；手册要求每场结束及时上传 |
| 训练数据 | 10/22 前 | 模型登记关联 |

---

## 5. 机器人端系统设计（reflow-agent）

目标：导览主循环不因回流卡顿；断网续传；每条数据可追溯。

```
gdps_tourism_camera（现有）
  cli/match_live.py ──► logs/match_<date>.jsonl（逐帧 + ts_iso）
                    └─► logs/guide_events_<evaluation_id>.jsonl（结构化事件）

reflow-agent（已实现：reflow/agent.py）
  collector  读事件文件（tail）/队列
  mapper     checkpoint_map.yaml + 冻结任务包 → 6 检查点的 report 记录
  spool      SQLite（pending/sent/acked；主键 report_id/record_id/stream+seq）
  client     urllib/httpx：超时、指数退避、幂等键复用、request_id 落盘
  reporter   ①建会话 ②running ③周期批量 ④终态 ⑤status 补传
```

设计要点：

1. **ID**：`run_id=<team>-<evaluation_id前8>-<yyyymmddHHMM>`；`report_id/record_id` 见上；重试复用原 ID 原内容。
2. **幂等**：`Idempotency-Key=run_id-session-create`；会话已绑定就用已有 `session_id`。
3. **序列号**：轨迹/具身 `seq` 跨批连续；`stream_id` 的实体/坐标系/来源/关节顺序不可变。
4. **批量**：≤200/批，5–10s 或 100 条触发；`max_request_bytes=1MiB`，超了拆批。
5. **时钟**：`timedatectl`/chrony 校时；时间带 `+08:00`；视频 `t0` 同源。
6. **审计**：`logs/reflow/` 存请求+响应+`request_id`（bootstrap 已默认如此）。
7. **失败**：4xx 不重试（409 同键、410 等窗口除外），5xx/超时 1→2→4→8→30s 退避 6 次，再转人工。
8. **不阻塞**：独立线程；队列满只丢非检查点采样并记 `dropped_seq`。
9. **终态唯一**：`checkpoint_result` 不可覆盖（换 ID 也不行）；只在真实终态提交。
10. **一个 report_id 一份内容**：改内容必须新 ID，否则 409。
11. **已落地**：`match_live.py`（`ts`/`--events-jsonl`/`--control-mode`）+ `reflow/agent.py`（确定性 `run_id` 保证重跑安全），单测 `reflow/tests` 5 项、感知测试 7 项均通过。

---

## 6. 分阶段实施计划（10/21 → 10/25）

### 6.1 今晚 10/21（16:25 已拿到任务包，剩余）

| 时间 | 任务 | 产出/验收 |
| --- | --- | --- |
| ✅ 16:25 | 用 Key 拉目录 + 任务包预览 | `logs/spec/2026-10-21_S22_task-package-preview_*.json`、`reflow/s22_spec.json` |
| 16:35–17:30 | 冻结映射：按 §1.5 确认 6 检查点语义，评审 `reflow/checkpoint_map.yaml` | 映射 v2（已写入，需队内过一遍） |
| 17:30–19:00 | 训练数据上传核对 + 模型登记 | 数据中心/模型中心状态截图 |
| 19:00–21:00 | 改造排期：`ts_iso`、`guide_events`、具身采样 | 契约 `docs/REFLOW_CONTRACT_v1.md` + 分工 |
| 21:00–23:00 | reflow-agent 骨架 + 用 `validate` 过一遍样例报告 | 0 问题（spec 感知校验已可用） |
| 23:00–24:00 | 录像/事件时间对齐方案定稿 | `t0` 记录脚本 + 命名规范 |

### 6.2 明天 10/22（联调日 + 能力补课）

| 时间 | 任务 | 验收 |
| --- | --- | --- |
| 09:00–11:00 | 最小闭环：测试评测 → evaluation_id → 建会话 → 冻结包 → P1 单检查点 → 终态 | 测试评测页出现接收量 |
| 11:00–12:00 | 补 P2/P3 事件（问答、语言切换）并上报 | observation 状态合法、无 422 |
| 13:00–15:00 | 全量 6 检查点跑一遍（能做真做，不能做如实 skipped/failed） | `missing_checkpoint_ids=[]`、`sequence_gaps=[]` |
| 15:00–16:00 | 具身通道联调（mode+battery 起，逐步加关节） | 具身接收量 >0，`robot_profile_version` 真实 |
| 16:00–17:00 | 异常演练：断网/重启/重复上传/错 Key/漏 end_at | 自愈或明确报错 |
| 17:00–18:30 | 版本冻结：代码打包、config、映射、Key 备份、SOP | `backup/reflow-v1-<日期>.tar.gz` |
| 18:30–21:00 | 进馆预演（若可）：真实光照/网络/2 遍计时 | 单场 ≤45 min；录像可回放；时间对齐 |

### 6.3 正式赛 10/23—10/25

每场按 §7 Runbook；赛后 15 分钟内 status 核对 + 评测数据文件上传。

### 6.4 赛后

确认 `review.status=published` → 查自动/专家评分与榜单 → 归档请求日志、status、录像、映射版本。

---

## 7. 每场执行 Runbook（现场 60 分钟）

### 7.0 工具速查

```bash
cd /Users/tostar/Downloads/导览图
export GDPS_API_KEY="$(cat ~/.gdps/api_key)"     # 600 权限；不入库
PY=.venv/bin/python                               # 有 certifi；系统 python 缺证书时用它

$PY tools/reflow_bootstrap.py tasks --scene-code CULTURAL_TOURISM_EDUCATION --task-code ''
$PY tools/reflow_bootstrap.py preview --benchmark-task-id df983fd4-85b5-4ae3-a99b-a3477427d72e --morphology humanoid
$PY tools/reflow_bootstrap.py session --evaluation-id <UUID> --morphology humanoid --expect-profile S22-v1
$PY tools/reflow_bootstrap.py package --session-id <SID>      # 冻结包，必须核对
$PY tools/reflow_bootstrap.py status  --session-id <SID>
$PY tools/reflow_bootstrap.py validate --kind report --file report-final.json   # spec 感知，离线
```

**T-60 场地检查**：网络/电源/摄像头识别/`timedatectl`/磁盘 ≥20GB/Key 有效。

**T-45 发起正式评测**：评测中心 → 选赛道 S22、模型、机器人构型 → 正式评测 → 复制 `evaluation_id`。

**T-40 建会话**：

```bash
BASE_URL='https://platform.ieic.gdps.org.cn/api/v1'
API_KEY="$(cat ~/.gdps/api_key)"
EVALUATION_ID='<正式评测ID>'
RUN_ID="$(date +%Y%m%d%H%M)-$(printf %s "$EVALUATION_ID" | cut -c1-8)"
jq -n --arg e "$EVALUATION_ID" '{evaluation_id:$e, morphology:"humanoid"}' > session-create.json
curl --fail-with-body -sS -X POST "$BASE_URL/reflow/sessions" \
  -H "X-API-Key: $API_KEY" -H "Idempotency-Key: $RUN_ID-session-create" \
  -H 'Content-Type: application/json' --data-binary @session-create.json -o session.json
SESSION_ID=$(jq -er .data.session_id session.json)
jq '.data | {session_id, reporting_profile_version, upload_window}' session.json | tee session-window.json
```

**T-35 核对 profile（硬闸门）**：建会话返回的 `reporting_profile_version` **必须等于 `S22-v1`**。不是 → 立刻停手：该 `evaluation_id` 赛道选错，不要上报任何数据，回评测中心重新发起（已绑定会话无法解绑）。

**T-35 核对冻结包**：6 个 `checkpoint_id`、`record_kinds`、`status_values`、`channels` 与预览 diff；不一致以冻结版改映射；同时确认 `robot_profile.model_name/model_profile_id` 与实机一致。

**T-30 开录 + running**：录像（记 `t0`）→ 上报 `task_status=running`、`start_at`、初始 `control_records`。

**T-0 执行导览（6 环节）**：
P1 定点讲解（识别+播报）→ P2 问答 → P3 多语言 → P4 跟随避让 → P5 途中互动 → P6 销售推荐；每环节先报 attempt/observation，结束时补终态。

**T+0 终态报告**：`end_at` + `task_status`（completed/partial/failed/aborted）+ **全部 6 个** `checkpoint_result`；做不了的写 `skipped/failed` 并在 `completion_note` 说明。

**T+10 收尾核对**：

```bash
curl --fail-with-body -sS "$BASE_URL/reflow/sessions/$SESSION_ID/status" \
  -H "X-API-Key: $API_KEY" -o status.json
jq '.data | {session_status, task_status, intake, missing_checkpoint_ids,
  sequence_gaps, completeness_status, automatic_scoring, review}' status.json
```

- `missing_checkpoint_ids` 非空 → 新报告 + 新 `record_id` 补传；
- `sequence_gaps` 非空 → 原流补序号；
- `duplicate_count` 增长 → 确认是否预期重传；
- ⚠️ 终态不可覆盖（换 ID 也不行），更正找赛事方；
- 评分 `waiting_upload` → 看 `automatic_scoring.reason`。

**T+15 上传评测数据文件**：多视角录像、重点点位影像、空间修正数据 → 核对状态与评测 ID。

**T+30 归档**：日志/响应/status 打包；任务卡备注 `session_id`、`request_id`、录像文件名。

---

## 8. 验收清单

| # | 检查 | 通过标准 |
| --- | --- | --- |
| 1 | Key 认证 | `tasks` 返回 `data.items`；S22 命中 |
| 2 | 赛道自检 | 建会话返回 `reporting_profile_version=S22-v1`（不是则说明评测任务选错赛道） |
| 2b | 任务包基线 | 6 检查点、状态字典、评分项与预览一致（冻结包 diff 无变化）；`robot_profile` 与实机一致 |
| 3 | 映射齐全 | `checkpoint_map.yaml` 覆盖 P1–P6，且与 `s22_spec.json` 一致 |
| 4 | 离线校验 | `validate --kind report|trajectory|embodied` 对真实体 0 问题（含未定义字段/检查点 ID/record_kind/状态校验） |
| 5 | 会话唯一 | 一个 `evaluation_id` 一个 `session_id` |
| 6 | 时间 | 全部带 `+08:00`，与录像 `t0` 误差 <1s |
| 7 | 幂等 | 同 `report_id` 重传不重复；改内容 409 |
| 8 | 检查点 | P1–P6 都有终态；状态均为任务包允许值；缺失项有 `completion_note` |
| 9 | 自动分 | `end_at` 非空；具身接收量 >0；P4 观测存在 |
| 10 | 断网续传 | 拔网 5 分钟恢复后无丢失/无重复 |
| 11 | 收尾 | `completeness_status=complete`、`missing_checkpoint_ids=[]`、`sequence_gaps=[]` |
| 12 | 文件通道 | 评测数据文件上传成功且与评测 ID 关联 |
| 13 | 评分可读 | `automatic_scoring` 的 scored/pending 合理，pending 有解释 |
| 14 | 证据包 | `logs/reflow/` + status + 录像 + 映射版本可追溯 |
| 15 | 写通道冒烟 | running/终态/具身/轨迹四类请求均 200 且 `accepted_count` 符合预期；原样重放不重复计数 |

---

## 9. 风险与预案

| # | 风险 | 触发信号 | 处置 |
| --- | --- | --- | --- |
| 1 | 目录查不到 S22 | `items=[]` | 用 `scene_code=CULTURAL_TOURISM_EDUCATION` 或 `q=文旅`（实测有效） |
| 2 | 评测任务选错赛道 | 建会话返回 profile ≠ S22-v1（如 S05-v1） | 停手不上报；回评测中心按 S22 重新发起；已绑定会话不可解绑 |
| 2b | 评分项与检查点名称不一致 | 人工评分对不上环节 | 以 `checkpoint_id` 为准，书面向赛事方确认 |
| 3 | 状态值不合法 | 422 `field_errors` 指向 status | 按 §1.5 表填；`validate` 可离线拦住 |
| 4 | 检查点类型错配 | 422/P2 报 attempt | P2/P4/P5/P6 只允许 observation+checkpoint_result |
| 5 | 会话已绑定 | 409 | 用已有 `session_id`，不重建 |
| 6 | 窗口关闭 | 410 | 核对 `upload_window`；联系赛事方；本地留证 |
| 7 | 网络抖动 | 超时/503 | spool + 退避；6 次失败转人工 |
| 8 | 时钟漂移 | 事件与录像错位 | 校时；漂移 >1s 停跑校准 |
| 9 | 具身缺失 | 无关节/电量 | 至少 mode+battery；如实说明，不造假 |
| 10 | 无位姿 | 无 SLAM/定位 | 不传轨迹（`required=false`），P4 靠观测+录像 |
| 11 | 能力缺口（P3–P6） | 无法完成环节 | 如实 `skipped/failed/unknown` + 录像；别漏报 |
| 12 | 漏 `end_at` | 完成时间 5 分拿不到 | 终态报告强制校验（validate 已提示） |
| 13 | 模型未登记 | 发起评测失败 | 10/22 前完成 |
| 14 | 误以为已发布 | `review.status=draft/pending` | 以 `published` 为准 |

---

## 10. 合规红线

1. 只上报本次真实执行数据；不重放历史、不伪造坐标/传感器/时间/状态。
2. 做不了的环节如实填 `skipped/failed/unknown`，不刷 `completed`。
3. 一评测任务一会话；不复用回流数据。
4. API Key 不入库、不群发、不写镜像；泄露立即撤回重建（本次 Key 已在会话中出现，赛后建议轮换）。
5. 不用他人模板/影像；录像只含本队执行过程。
6. 保留请求日志与 `request_id` 以备申诉。

---

## 11. 待赛事方确认（今晚发出）

1. 评分项名称与检查点编号语义不一致（评分项“P1 游客日常问答服务”挂 S22-P1 定点讲解），以哪个为准？
2. `details_schema` 的 22 个通用指标中，P1–P6 各自**哪些指标参与自动/人工评分**？（目前自动策略只有 time/embodied_data/avoidance）
3. 动线避障 15 分（avoidance）具体如何计算？是否需要轨迹通道数据？无位姿是否直接判 0？
4. 具身 5 分（embodied_data）的最低要求：频率、字段（关节/电量/影像）、轨迹是否计入？
5. `files` 通道（评测数据文件）规格：机位数量/分辨率/时长上限/命名规范；上传后能否获得 `asset_id` 用于 `evidence_refs`？
6. 能力缺失（如无多语言、无跟随）按 `skipped/failed` 上报后，人工评分如何处理？是否扣“任务执行”分？
7. `upload_window` 真实时长；窗口关闭后补传流程。
8. 测试评测是否计入评分/占用次数。

---

## 12. 附录

### A. 官方入口

| 内容 | 地址 |
| --- | --- |
| 平台首页 | https://platform.ieic.gdps.org.cn |
| 在线回流 Swagger | https://platform.ieic.gdps.org.cn/api/v1/reflow/docs |
| OpenAPI JSON | https://platform.ieic.gdps.org.cn/api/v1/reflow/openapi.json |
| 操作手册（docx） | https://platform.ieic.gdps.org.cn/introduction/具身智能评测管理平台参赛团队操作手册.docx |

### B. 枚举与字段字典（实测补齐）

| 字段 | 取值 |
| --- | --- |
| `task_status` | running / completed / partial / failed / aborted |
| `session_status` | scheduled / active / closed / cancelled |
| `record_kind` | attempt / observation / checkpoint_result |
| `control_records.mode` | autonomous / teleoperation / assisted |
| `embodied.samples.mode` | autonomous / teleoperation / assisted / unknown |
| `entity_type` | robot_base / tool |
| `pose_source` | robot / slam / localization / external |
| 检查点终态 | completed / partial / failed / skipped / unknown（P1–P6 相同） |
| P1/P3 attempt | speech_* / language_* 等（见 §1.5） |
| 数组上限 | checkpoints ≤200；control_records ≤200；points 1–200；samples 1–200；report_asset_ids ≤200 |
| 请求体上限 | 1 MiB/次（任务与具身通道） |

### C. 评分结构（实测，rule_version=competition-rules-v2.0-20261009-r3）

| 模块 | 权重 | 自动项 | 人工项 |
| --- | --- | --- | --- |
| 任务执行 | 65 | 完成时间 5（time） | P1 10 / P2 15 / P3 5 / P4 5 / P5 10 / P6 15 |
| 具身数据采集与回流 | 5 | 采集与回流 5（embodied_data） | — |
| 自主智能 | 20 | 动线避障与通行安全 15（avoidance） | 理解场景指令 5（semantic） |
| 创新能力 | 10 | — | 自选创新动作 10 |
| 合计 | 100 | **25** | **75** |

### D. 相关仓库文件

| 文件 | 作用 |
| --- | --- |
| `docs/DATA_REFLOW_PLAN.md` | 本文档 |
| `tools/reflow_bootstrap.py` | 目录/预览/会话/冻结包/状态/上线发送（`send`）+ spec 感知离线校验 |
| `reflow/checkpoint_map.yaml` | 6 检查点事件→记录映射（已按实测任务包写好） |
| `reflow/s22_spec.json` | 任务包规范化快照（校验用；不含密钥） |
| `reflow/examples/` | 三类上报的可直接校验示例（report/trajectory/embodied，占位值需替换） |
| `reflow/agent.py` | 事件→上报：6 检查点聚合、dry-run 校验、`--send` 发送 + status 核对 |
| `reflow/tests/test_agent.py` | agent 单测（全流程/仅有 P1/中断/无事件/批次 共 5 项） |
| `docs/GUIDE_EVENTS_v1.md` | 导览事件契约（字段/类型/检查点判定/用法，含 P2 问答源与多来源合并） |
| `guide_cli.py` | P2 问答：`--ask`/`--questions` + `--events-jsonl` 写 `qa_answered/qa_unanswered` |
| `run_mac_camera.py` | 启动脚本透传 `--log-jsonl`/`--events-jsonl`/`--control-mode`（Linux 脚本本就透传） |
| `reflow/asr_qa.py` | 语音提问：可插拔 ASR 命令 → 检索回答 → `asr_transcript`/`qa_*` 事件 |
| `docs/RUNBOOK_S22.md` | S22 现场一页纸（时间轴/命令卡/故障分支/分工，可打印） |
| `reflow/s05_spec.json` | S05 质检任务包规范化快照（校验/映射用） |
| `logs/spec/2026-10-21_S22_task-package-preview_{humanoid,wheeled}.json` | 原始响应快照 |
| `logs/reflow/` | 每次请求/响应/`request_id` 审计 |
| `gdps_tourism_camera/.../cli/match_live.py` | 主循环（需加 `ts_iso` 与事件输出） |
| `knowledge_base.json` | 展品组/讲解词（P1/P2 依据） |

### E. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-10-21 16:10 | 首版：平台事实、映射设计、分阶段计划、Runbook |
| v1.1 | 2026-10-21 16:35 | 用 API Key 实测任务包：6 检查点、100 分结构、25 自动/75 人工、通道要求；纠正赛道代码；重写映射与计划；新增 spec 快照与 spec 感知校验 |
| v1.2 | 2026-10-21 16:40 | S22 测试评测全链路实测：四类写接口回执、幂等/409/422 语义、`accepted_count` 统计口径、`draft_ready≠出分`；新增 `send` 命令与赛道 profile 闸门；补冻结包对比 |
| v1.3 | 2026-10-21 16:45 | 落地采集与上报：`match_live.py` 加 `ts`/`--events-jsonl`/`--control-mode`；新增 `reflow/agent.py` 与单测；新增事件契约文档；README 同步 |
| v1.4 | 2026-10-21 16:55 | P2 问答接入：`guide_cli.py` 输出 `qa_answered/unanswered`；agent 支持多事件文件按 ts 合并 + 晚于 run_end 告警；启动脚本透传事件参数；单测 7 项 |
| v1.5 | 2026-10-21 17:05 | 语音 ASR 适配器 `reflow/asr_qa.py`（可插拔引擎，含录音与假引擎测试，4 项单测）；现场一页纸 Runbook；单测合计 11 项 |
| v1.6 | 2026-10-21 17:20 | 双赛道：实测并固化 S05 质检任务包（6 检查点/85 分自动）；bootstrap 增 `--track`；agent 增 `--mode generic`（显式 checkpoint_record）+ S05 单测；单测 13 项 |
