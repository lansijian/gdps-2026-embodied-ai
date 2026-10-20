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
