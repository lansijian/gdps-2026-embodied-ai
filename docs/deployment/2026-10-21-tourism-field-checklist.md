# 文旅导览 · G1 真机联调清单（逐步执行）

日期：2026-10-21。对象：`feat/tourism-guide-workflow`（导览进程）+ 导航组 `g1_nav2_ws`（导航栈）。
原则：**guide 只发标准 Nav2 `NavigateToPose`，不碰速度/SDK；每一步先 dry-run 再 live。**

## 0. 前置

- [ ] 机器人 `uname -m`（aarch64/x86_64）、`python3 -V`（3.8.x）、`echo $DISPLAY`（SSH 应为空）；
- [ ] `GDPS_TOURISM_TEMPLATES` 指向模板目录（29 张 jpg + knowledge_base.json）；
- [ ] `DOUBAO_API_KEY` 已设置（能联网）；
- [ ] 仓库同步到 `feat/tourism-guide-workflow`，依赖已装（opencv/numpy/Pillow/PyYAML/websockets）。

## 1. 相机

```bash
# 只读状态（不修改任何东西）
bash scripts/tourism/g1_camera_fix.sh status

# 修复 USB 自动挂起/掉线（需要 sudo 密码）
bash scripts/tourism/g1_camera_fix.sh            # 临时生效
bash scripts/tourism/g1_camera_fix.sh persist    # 永久生效（推荐）

# 只读自检 + 抓一帧 + 可选识别（彩色节点 /dev/video4，头部倒装用 --flip 180）
python3 scripts/tourism/check_camera.py --camera 4 --flip 180 \
  --match-templates ~/tourism_guide/templates
```

预期：`[camera] captured ... shape=(480, 640, 3)`，识别结果 `accepted` 或 `unknown_reason` 合理。
若内核日志是 `error -71 / device not responding`：拔插 Type-C 后重跑修复脚本。

**2026-10-21 实测**：RealSense 在 SuperSpeed 下反复报 `device not accepting address / error -71 / Disable of U1/U2 failed`，
表现为 `/dev/video*` 每隔一两分钟消失重连。处理顺序：
1) 重新插紧/更换机器人内部 Type-C 线（优先）；2) `bash scripts/tourism/g1_camera_fix.sh persist` 后重启；
3) 仍不稳定时用 USB2 转接（640×480 彩色流 YUYV 约 18MB/s，USB2 可承受），避免 SuperSpeed 信号问题。
彩色节点通常是 `/dev/video4`（YUYV），红外/深度是 `/dev/video0-3`（Z16/GREY）；头部安装方向由 `--flip` 校正，
站定后 `check_camera.py --camera 4` 抓一帧确认画面方向（当前抓到的红外帧是天花板、彩色帧是地面，需现场确认相机朝向）。

```bash
# A. ROS 图像话题（等队友给话题名后替换）
ros2 topic list | grep -i image
ros2 topic hz /camera/color/image_raw
ros2 topic echo /camera/color/image_raw --once | head -5
# B. UVC 直连
ls -l /dev/video*; v4l2-ctl --list-devices
```

- [ ] 单图验收（不接摄像头，验证模板/知识库/匹配）：
  `python3 scripts/tourism/match_webcam.py --templates "$GDPS_TOURISM_TEMPLATES" --image "$GDPS_TOURISM_TEMPLATES/001.jpg"`
- [ ] 实拍验收：把相机对着展品图片，`--camera 0 --no-tts` 单帧确认 accepted。

## 2. 导航（导航组负责，guide 只消费）

```bash
cd ~/g1_nav2_ws && source .deps/environment.bash && source install/setup.bash
bash src/g1_nav_bringup/scripts/check_stack.sh        # 正墙测试：angle 0 ≈ 1m
ros2 launch g1_nav_bringup mapping.launch.py          # 建图
bash src/g1_nav_bringup/scripts/save_map.sh           # 存图
ros2 launch g1_nav_bringup nav_bringup.launch.py slam:=false map:=$HOME/g1_nav2_ws/maps/site.yaml dry_run:=true
```

- [ ] RViz 2D Pose Estimate → 2D Nav Goal 单点 dry-run 能规划、返回成功；
- [ ] `ros2 action list | grep navigate_to_pose` 存在（guide 用这个名字，必要时 `--action-name`）；
- [ ] 到点后用 RViz/日志记录至少 4 个站点坐标，填入 `stations.g1.yaml`。

## 3. 配置自检（填完站点后必跑）

```bash
python3 scripts/tourism/check_tourism_config.py \
  --stations tracks/cultural-tourism/configs/stations.g1.yaml \
  --knowledge "$GDPS_TOURISM_TEMPLATES/knowledge_base.json" \
  --dialogue tracks/cultural-tourism/configs/knowledge_dialogue.json \
  --templates "$GDPS_TOURISM_TEMPLATES" \
  --manifest assets/narration/manifest.json
```

- [ ] `errors=0`；警告逐项确认（占位坐标、P1 资料未核实、简讲过长）。

## 3.5 P1 资料现场核对（10 分钟）

打开 `tracks/cultural-tourism/configs/knowledge_dialogue.json`，逐项核对 `meta.pending_verification`：

- [ ] 文创商店/咖啡厅当前是否营业、位置；
- [ ] 母婴室、各楼层洗手间位置；
- [ ] 免费定时讲解当日场次；
- [ ] VR 眼镜/讲解器租赁价格与押金；
- [ ] 庭院是否开放、有无围挡；
- [ ] 预约政策是否仍为公众号实名预约。

核对完把 `meta.verified` 改为 `true`，并跑一次配置自检（`check_tourism_config.py`）确认 P1 不再提示 partial。

## 4. guide dry-run（不发任何运动）

```bash
python3 scripts/tourism/guide_node.py --dry-run \
  --stations tracks/cultural-tourism/configs/stations.g1.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.json
```

- [ ] 8 站环线跑完，END 信号数 = 站数 + 1（停止讲解测试），`final_state=finished`。

## 5. 联调：导航 dry_run + guide 真跑（推荐第一轮）

终端1（导航组）：`dry_run:=true` 的 Nav2（会返回 SUCCEEDED，但不真动）。
终端2：

```bash
export GDPS_TOURISM_TEMPLATES=...; export DOUBAO_API_KEY=...
python3 scripts/tourism/guide_node.py \
  --stations tracks/cultural-tourism/configs/stations.g1.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.json \
  --camera 4 --flip 180 \
  --greeting --autostart --log-dir logs/tourism
```

- [ ] 收到 START 后发第一个目标；到点（Nav2 SUCCEEDED）→ 相机识别 → 豆包开口讲解；
- [ ] 说"好的，感谢，请前往下一个目标点"→ 立刻停播 + `/tourism/guide_event` 出现 `END_NARRATION`；
- [ ] 说"带我去看汇丰铜狮"→ 导航到对应站点并讲解；
- [ ] 视觉触发：`ros2 topic pub /tourism/visual_target std_msgs/String "{data: '{\"exhibit_id\":\"EXH_001\",\"confidence\":0.9}'}" --once` → 导航改道；
- [ ] `logs/tourism/guide_*.jsonl` 完整（END/NAV/ASR/budget 都有）。

## 6. 真机 live（安全前提全部满足才做）

- [ ] 现场人员到位、急停可用、场地清空、导航组允许 `allow_live`；
- [ ] 先单站短距离：`--no-auto-advance`，人工确认到点后结束；
- [ ] 再跑 2-3 站环线；最后完整 8 站；
- [ ] 全程有人盯，异常立即急停（软件停车不等于急停）。

## 7. 断网/豆包故障降级

```bash
# 预生成音频（开发机）→ 同步到机器人
python3 scripts/tourism/prepare_fallback_audio.py --knowledge ... --stations ... --out-dir assets/narration
python3 scripts/tourism/guide_node.py ... --offline-audio-dir assets/narration
# 或彻底离线
python3 scripts/tourism/guide_node.py ... --offline --offline-audio-dir assets/narration
```

- [ ] 运行中拔网/停 key：日志出现 `doubao_unavailable_offline_fallback`，讲解改本地 wav，导航/END 不断。

## 8. 30 分钟预算演练

```bash
python3 scripts/tourism/guide_rehearsal.py --knowledge "$GDPS_TOURISM_TEMPLATES/knowledge_base.json" \
  --manifest assets/narration/manifest.json --budget-s 1800 --reserve-s 180 --listen-s 8
```

- [ ] `status=OK`；实跑时对照 `[budget]` 日志，超时自动推进是否生效。

## 9. 验收勾选（比赛前）

- [ ] P1：四类问答各问 3 条 + 1 条超范围（应拒答）；
- [ ] P2：3 个无坐标指令（馆内/馆外/不可达）行为正确；
- [ ] P3：途经点位各触发一次简讲、无重复、不打断长讲解；
- [ ] P5：推荐清单内容与馆方口径一致；
- [ ] P6：人称/礼貌/结束语自然；
- [ ] 数据采集：语音、对话文本、识别帧、运动轨迹、导航日志齐全；
- [ ] 全程无人工干预（除安全确认）。

## 10. 常见故障

| 现象 | 排查 |
| --- | --- |
| `import rclpy` 失败 | 先 `source /opt/ros/foxy/setup.bash` 再跑；或 `--no-ros --dry-run` 先验逻辑 |
| action server 不在 | `ros2 action list \| grep navigate`；检查导航栈是否起来；`--action-name` 对齐 |
| 图像话题没数据 | `ros2 topic hz`；相机被 videohub/遥操作占用时用 `scripts/tourism/g1_camera_fix.sh` |
| 豆包无响应 | 检查 key/网络；日志 `doubao:` 错误；先 `--offline` 跑通再恢复在线 |
| 到点不停/不停发目标 | 检查 Nav2 result；guide 日志 `navigation_failed`；检查 map/AMCL 初始位姿 |
| END 信号没人收 | 确认导航/主控订阅 `/tourism/guide_event`（话题名可 `--visual-target-topic` 同理配置） |