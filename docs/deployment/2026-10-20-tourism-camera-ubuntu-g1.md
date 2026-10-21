# 文旅赛道：摄像头展品识别导览 · Ubuntu 20.04 / 宇树 G1 部署

日期：2026-10-20。范围：把 `tracks/cultural-tourism/` 的展品识别导览跑到 Ubuntu 20.04（含宇树 G1 的 aarch64 JetPack 5）。
本轮只做迁移适配与离线/回放验证，未在真实 G1 硬件与真实摄像头下实测。

## 0. 布局与前提

```text
$REPO/gdps-2026-embodied-ai/
├── scripts/tourism/match_webcam.py          # 入口
├── scripts/tourism/run_linux_camera.sh      # Ubuntu/G1 启动脚本
├── scripts/tourism/bench_camera.py          # 性能基准
├── tests/cultural_tourism/                  # 无摄像头单测
└── tracks/cultural-tourism/
    ├── gdps_tourism/                        # 匹配包（camera / matching / cli）
    ├── configs/matcher.example.{json,yaml}
    └── requirements-linux.txt
```

模板图片与 `knowledge_base.json` **不入库**，单独放一个目录（下称 `$TEMPLATES`）：`001.jpg..028.jpg`、`25.jpg`、`025.jpg` + `knowledge_base.json`。

```bash
export REPO=$HOME/gdps-2026-embodied-ai
export TEMPLATES=$HOME/exhibit_templates
cd "$REPO"
```

## 1. 安装依赖

先探测机器：

```bash
uname -m                                  # aarch64 = Jetson/G1；x86_64 = 普通 PC
python3 -V                                # Ubuntu 20.04 为 3.8.10
echo "DISPLAY=[${DISPLAY:-}]"             # SSH 为空 -> 自动 headless
ls -l /dev/video* 2>/dev/null || echo "未发现摄像头节点"
```

### 1.1 aarch64 / JetPack 5（G1，推荐 apt）

JetPack 5 的 L4T 源自带 OpenCV 4.5.4（含 SIFT），无需 pip 编译：

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-yaml python3-pil \
  espeak-ng fonts-noto-cjk v4l-utils
python3 -c "import cv2; print(cv2.__version__, hasattr(cv2, 'SIFT_create'))"   # 期望 4.5.4 True
```

### 1.2 x86_64（venv + pip）

普通 x86 Ubuntu 20.04 的 apt OpenCV 是 4.2（无 SIFT），改用 venv：

```bash
sudo apt install -y python3-venv libgl1 libglib2.0-0 espeak-ng fonts-noto-cjk v4l-utils
python3 -m venv .venv
.venv/bin/pip install -r tracks/cultural-tourism/requirements-linux.txt
.venv/bin/python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'SIFT_create'))"
```

无显示器机器可把 `requirements-linux.txt` 里的 `opencv-python` 换成 `opencv-python-headless`（不依赖 libGL，但没有 `imshow`）。

## 2. 摄像头权限

```bash
sudo usermod -aG video $USER && newgrp video    # 重新登录后生效
v4l2-ctl --list-devices                          # 需要 v4l-utils
./scripts/tourism/run_linux_camera.sh --list-cameras
```

USB/UVC 摄像头一般是 `/dev/video0`；外接第二台用 `CAMERA=1` 或 `CAMERA=/dev/video2`。
Intel RealSense（D435i 等）需要 `pip install pyrealsense2`（aarch64 用 Intel apt 源），然后用 `--backend realsense`。

## 3. 运行

```bash
cd "$REPO"
export GDPS_TOURISM_TEMPLATES="$TEMPLATES"

# 实时快速档：orb + 粗筛 + 每 2 帧匹配；无 DISPLAY 自动 headless
./scripts/tourism/run_linux_camera.sh --log-jsonl logs/live.jsonl

# 精度档 / 关闭粗筛对照 / 外接摄像头 / RealSense
./scripts/tourism/run_linux_camera.sh --accurate
./scripts/tourism/run_linux_camera.sh --no-prefilter
CAMERA=1 ./scripts/tourism/run_linux_camera.sh
./scripts/tourism/run_linux_camera.sh --backend realsense

# 不接摄像头也能验收：单图 / 录像回放
./scripts/tourism/run_linux_camera.sh --image 001.jpg
./scripts/tourism/run_linux_camera.sh --video demo.mp4 --headless
```

接显示器时去掉 headless 即可看到置顶预览窗口（`q`/`Esc` 退出，`s` 存快照，需 `--snapshot-dir`）。
退出（含 Ctrl+C）会打印汇总：

```text
[done] frames=... matches=... display=..fps match=..fps mean_match=..ms mean_prefilter=..ms prefilter_fallback=..%
```

`match` 应接近 `display / match_every`；`prefilter_fallback` 是实际补扫全量的比例（低纹理展品会触发，属安全行为）。

## 4. 验证

```bash
.venv/bin/python -m unittest discover -s tests/cultural_tourism -v      # 7 个单测
.venv/bin/python scripts/tourism/bench_camera.py --templates "$TEMPLATES" --method orb
.venv/bin/python scripts/tourism/match_webcam.py --templates "$TEMPLATES" --image 025.jpg --method orb
```

预期：单测全过；`bench_camera` 输出 `exhibit_top1_accuracy=1.000`、`false_accepts=0`；`025.jpg` 触发 `low_score` 回退全量但仍正确接受。

## 5. 性能与调优

| 档位 | 单帧耗时（M1 基准，单进程） | G1 预估 |
| --- | --- | --- |
| ORB + 粗筛（默认） | ~47ms | 70–150ms |
| SIFT + 粗筛（`--accurate`） | ~105ms | 150–300ms |
| 全量扫描（`--no-prefilter`） | SIFT ~380ms / ORB ~125ms | 0.5–1.5s |

G1 上若偏慢，按顺序调：`--match-every 3` -> `--prefilter-top-k 2` -> 配置里 `max_side: 960` -> 采集分辨率降到 960x540。

## 6. 排障

| 现象 | 处理 |
| --- | --- |
| `ImportError: libGL.so.1` | 无显示器改用 `opencv-python-headless`，或 `apt install libgl1` |
| 无窗口 / `imshow` 报错 | 加 `--headless`（脚本在 Linux 无 DISPLAY 时会自动加） |
| `SIFT_create` 不存在 | 装 OpenCV 4.4+；否则自动回退 ORB（精度略降，可指定 `--method orb`） |
| 找不到 `/dev/video*` | 检查 USB 连接、`usermod -aG video`、`v4l2-ctl --list-devices` |
| 摄像头被占用 | `fuser -v /dev/video0`，关掉其它进程 |
| 帧率低 | 先看 `[done]` 的 `match` 与 `mean_match`，再按第 5 节调优 |
| 中文名不显示 | `apt install fonts-noto-cjk`（HUD 通过 Pillow 渲染） |
| 语音不播报 | 加 `--tts`，并确认 `espeak-ng` 已安装 |

## 7. 已知边界

- 未在真实 G1 / 真实展馆光照下验证；模板为固定视角照片，现场需按样本复核阈值。
- 开机自启可用 systemd user service 包一层上面的启动命令（`loginctl enable-linger $USER`）。
- 若使用 G1 机身自带相机（走 Unitree SDK 而非 V4L2/RealSense），需要在 `camera/` 下新增取帧适配器。
## 8. G1 实机探测记录（2026-10-21，只读）

环境：Jetson Orin 类 aarch64 / 8 核 / 15G 内存，Ubuntu 20.04.6，Python 3.8.10。

| 项 | 实测 |
| --- | --- |
| OpenCV | 4.2.0（apt），**无 SIFT** → 现场固定 `--method orb`（代码会自动回退并告警） |
| 其它依赖 | numpy 1.24.4、websockets 13.1、Pillow 7.0（无 getbbox，HUD 预览需升级）、unitree_sdk2py 1.0.1 |
| ROS | Foxy + CycloneDDS，环境脚本 `~/g1_nav2_ws/.deps/environment.bash`；`/dog_odom` 1034Hz |
| 地图 | `~/g1_nav2_ws/maps/site.pgm` 777×732 @0.05m，origin (-20.1,-19.6)；AMCL 初始位姿已保存 |
| 相机 | RealSense D435i UVC：彩色 `/dev/video4`（YUYV）、灰度 `/dev/video2`；**头部倒装，需 `--flip 180`** |
| 相机稳定性 | USB 自动挂起会导致 `error -71 / device not responding` 掉线；先跑 `bash scripts/tourism/g1_camera_fix.sh`（临时）或 `persist`（永久，需 sudo） |
| 音频 | 麦克风组播 239.168.123.161:5555 有数据（5120B/包，约 6.3 包/秒）；`AudioClient` 可导入 |
| 网络 | 可访问 `openspeech.bytedance.com`（TLS 正常） |

**实测性能（真实 29 张模板，G1 CPU，bench_camera 合成场景）**：

| 模式 | 结果 |
| --- | --- |
| 模板库构建 | 5.3s（启动一次性） |
| ORB + 粗筛（默认） | mean 93.2ms / median 80.2ms / p95 214ms |
| ORB 全量（对照） | 约 248ms |
| 准确率 | exhibit_top1=1.000、topk=1.000、accept_rate=1.000、false_accepts=0 |

结论：30fps 相机 + `match_every 2` 会超过 CPU 能力（约 10 次/秒上限），建议现场 `--match-every 3`；
或把采集分辨率降到 960×540 / 640×480。

**机器人上部署（已验证）**：

```bash
# 开发机（仓库根目录）
rsync -az --exclude .git --exclude __pycache__ ./ unitree@192.168.123.164:~/tourism_guide/
rsync -az /path/to/templates/*.jpg /path/to/templates/knowledge_base.json \
  unitree@192.168.123.164:~/tourism_guide/templates/
# 机器人上
cd ~/tourism_guide
python3 -m unittest discover -s tests/cultural_tourism      # 56 项通过
python3 scripts/tourism/guide_node.py --dry-run \
  --stations tracks/cultural-tourism/configs/stations.example.yaml \
  --knowledge tracks/cultural-tourism/configs/knowledge_dialogue.json
python3 scripts/tourism/check_camera.py --camera 4 --flip 180 \
  --match-templates templates
```

注意：厂商 `videohub` 二进制当前是 `.bak`（被禁用，可能是导航组为让出相机）；如需官方图传，需与导航组确认后再恢复。
### 8.1 2026-10-21 第二轮实测（换 USB 口后）

- 相机换口后稳定：USB 路径 `2-2.2`，6 个接口全部绑定 `uvcvideo`，`/dev/video0-5`；
- 彩色节点 `/dev/video4`（YUYV），OpenCV 打开为 **1280×720 @ 30fps**；
- 实时主循环实测（headless，90 帧，`--match-every 2`）：`display≈25.3fps`，`match≈4.8fps`，`mean_match≈170ms`；
  当前镜头对着地面（低纹理），**所有帧都走全量回退**（`prefilter_fallback=100%`，query_features≈900，good_matches≈4）；
- 对着展品时粗筛应命中短名单，预计回到 ~90-100ms/帧（bench 实测 93.2ms）；
- `power/control=on` 但 `autosuspend=2`、`usbfs_memory_mb=16`，仍建议跑一次 `bash scripts/tourism/g1_camera_fix.sh persist`（sudo）彻底稳定；
- 当前画面朝下/朝地面：需机器人站立并面向展品后再验证识别；`--flip` 方向参数待现场确认。

**低特征快速拒识**：已实现 `fast_reject_features`（默认关闭）。实测地面帧仍有 ~900 个 ORB 特征，
按特征数阈值无法和展品区分，故暂不启用；空白/墙面帧的全量回退成本可接受（约 170ms，且只发生在没看到展品时）。
### 8.2 真机全链路自检（2026-10-21，未动机器人）

```bash
export DOUBAO_API_KEY="$(cat ~/.doubao_key)"
cd ~/tourism_guide
python3 scripts/tourism/guide_selftest.py --stations 2 --truncate 100 \
  --camera 4 --flip 180 --play --volume 60
```

实测结果：豆包会话 1.5s；S01 音频 485KB、S02 音频 1.74MB（均经 G1 喇叭播放）；
2 个 END_NARRATION、3 次导航请求、2 次 audio.done，状态机按预期推进。
该自检用 MockNavigator 跳过真实导航，只验证「相机→匹配→场景→豆包→意图→END」链路。
