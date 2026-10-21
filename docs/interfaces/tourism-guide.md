# 文旅导览 ↔ 导航 / 豆包 接口契约

状态：草稿 v0.1（2026-10-21）。代码：`tracks/cultural-tourism/gdps_tourism/guide/`，dry-run 已验证。

## 1. 角色与数据流

```text
迎宾/主控 --START--> [tourism guide 进程] --/navigate_to_pose(Nav2 Action)--> g1_nav2_ws 导航栈
                         |  <- 到达/失败（Action result）
                         |  -> 相机识别（tracks/cultural-tourism/gdps_tourism/matching）
                         |  -> 豆包实时语音（session.update + 预置讲解词 + Function Calling）
                         |  -> 游客意图（FC: request_next_station / stop_narration / request_recommendation）
                         +--/tourism/guide_event(String JSON)--> 导航组/主控（END 信号）
```

- guide 只发高层导航目标，**不碰** `cmd_vel`、`LocoClient`、SDK、TF。
- 到点 = Nav2 `NavigateToPose` action result `SUCCEEDED`（失败/取消按 ERROR 处理）。

## 2. 事件契约（ROS 2 topic `/tourism/guide_event`, std_msgs/String, JSON）

| type | 触发 | 关键字段 | 消费方动作 |
| --- | --- | --- | --- |
| `END_NARRATION` | 游客说去下一个点/点名目标/要求停止讲话 | `station_id`, `next_station_id`(可为 null), `reason`, `ts` | 结束本轮讲解；`next_station_id` 非空时准备下一站 |
| `NAV_REQUEST` | guide 已下发导航目标 | `station_id`, `frame_id`, `x`, `y`, `yaw`, `eta_s` | 仅观察/记录（导航动作本身由 guide 调 Action） |
| `READY` | guide 启动完成 | `stations`, `mode` | 主控可发 START |
| `ERROR` | 导航失败/豆包异常/相机异常 | `stage`, `message`, `recoverable` | 主控降级或人工接管 |
| `FINISHED` | 全部站点讲完 | `reason` | 主控收尾 |

`reason` 取值：`visitor_next_request` / `narration_stopped` / `listen_timeout` / `tour_complete` / `operator_stop`。

## 3. START 信号（待迎宾组确认）

guide 目前支持三种启动方式，任选其一：
1. ROS topic `/tourism/start`（std_msgs/String，JSON：`{"mode":"tour","greeting":false}`）；
2. 命令行参数 `--autostart`（现场调试）；
3. 由主控直接 import 调用 `TourFlow.start()`（同进程集成，不推荐，多进程更安全）。

## 4. 站点配置 `tracks/cultural-tourism/configs/stations.example.yaml`

- `pose: {x, y, yaw}` 为 `map` 坐标，**现场 SLAM 建图 + RViz 标点后填写**；
- `tour_order` 为环线顺序；`kind=exhibit` 到点后触发相机识别，`landmark/shop` 直接讲；
- `route_brief` 是 P3 沿途一句话简讲；`target_aliases` 供 P2 无坐标指令匹配；
- `eta_s` 用于 P2 回答“能不能到、大概多久”。

## 5. 豆包实时语音用法（模型 1.2.6.1）

| 能力 | 事件 | 用途 |
| --- | --- | --- |
| 初始人设/场景 | `session.create` (instructions, tools, dialog_context, hotwords) | 开场/第一站 |
| 换站换场景 | `session.update` (instructions) | 到点后更新场景与知识 |
| 精确播报预置讲解词 | `speech_text_buffer.commit` / `speech_text_buffer.replacement.append+commit` | 防幻觉，按馆方稿件朗读 |
| 立即停止长讲解 | `response.cancel` + 本地 `PlayStop` | END 信号的第一步 |
| 游客意图 | `response.function_call_arguments.done` + `conversation.item.create(role=tool)` | 结构化结束/换站/推荐 |
| 静音保活 | `input_audio_mute.commit` / `input_audio_unmute.commit` | 讲解期间防回声 |
| ASR 热词 | `session.context.hotwords` | 展品名/地名识别（汇丰铜狮、仰山堂…） |

Function Calling 定义（3 个）：`request_next_station`、`stop_narration`、`request_recommendation`，见 `guide/scene.py`。

## 6. P1/P2/P3/P5 映射

- **P1 四类问答**：`configs/knowledge_dialogue.example.json` 的 `venue_facts`（馆情/建筑/庭院服务/参观建议）+ 拒答话术；
- **P2 无坐标指令**：FC `request_next_station.target_name` → `StationBook.resolve_target()` → 可达性/ETA 回答 + 导航；
- **P3 沿途讲解**：行进中低频识别地标（`kind=landmark`），`TourFlow.on_landmark()` 保证每次经过只讲一句、且与上一句间隔 ≥ `brief_gap_s`；
- **P5 周边推荐**：`knowledge_dialogue.recommendations` + FC `request_recommendation`。

## 7. Dry-run（不需要 ROS / 摄像头 / 云）

```bash
python3 scripts/tourism/guide_dryrun.py \
  --stations tracks/cultural-tourism/configs/stations.example.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.example.json \
  --out /tmp/guide_dryrun.json
```

输出完整时间线：每站导航→到达→识别→讲解→游客意图→END 信号，最后 `final_state=finished`。

## 8. 对导航组的请求

1. 订阅 `/tourism/guide_event`（std_msgs/String JSON），按上表处理 `END_NARRATION`；
2. 确认 guide 可以直接用 `nav2_msgs/NavigateToPose` action（`/navigate_to_pose`），不需要走 RViz；
3. 现场建图后提供 `maps/site.yaml` + 标点结果（或允许我们自己用 `/goal_pose` 记录）；
4. 相机：导航栈不使用相机；若遥操作/图传占用 RealSense，请告知可用图像话题；
5. `dry_run:=true` 时 guide 也走同一 Action（Nav2 正常返回 SUCCEEDED，只是速度桥不真动），便于联调。

## 9. 待补（不阻塞联调）

- 站点真实坐标与环线顺序（现场建图后）；
- P1 权威资料（开放时间/票务/设施）、文创馆内容、周边 POI 清单（现有占位数据已在文件里标注 verified=false）；
- 豆包 API Key 与现场网络；
- 讲解词长/短两版审核（长讲解取 `knowledge_base.json` 的 `narration`，沿途一句话取 `stations.route_brief`）。
## 10. 节点运行方式（占位版已可跑 dry-run）

```bash
# 无 ROS / 无摄像头 / 无云端：跑完整时间线
python3 scripts/tourism/guide_node.py --dry-run \
  --stations tracks/cultural-tourism/configs/stations.example.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.example.json

# G1 上（ROS 2 Foxy + 导航栈已启动 + DOUBAO_API_KEY 已设置）
export GDPS_TOURISM_TEMPLATES=$HOME/exhibit_templates
export DOUBAO_API_KEY=...
python3 scripts/tourism/guide_node.py \
  --stations tracks/cultural-tourism/configs/stations.g1.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.json \
  --camera 0 --method orb --prefilter orb --greeting --log-dir logs/tourism

# 现场调试：不等 /tourism/start，直接开跑
python3 scripts/tourism/guide_node.py ... --autostart
```

节点内部：rclpy 在后台线程 spin，asyncio 主线程跑「豆包会话 + 导览状态机 + 相机识别」；
导航用 NavigateToPose Action result 判定到点；P3 每 `--scan-interval` 秒扫一次地标，
命中 `route_match_exhibit_ids` 的展品则播一句 `route_brief`（同一地标只讲一次，间隔 ≥ brief_gap_s）。
