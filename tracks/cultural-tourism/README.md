# Track: cultural-tourism

复用 `shared/navigation`，本赛道只提供展品目标、识别与讲解触发。

## 摄像头展品识别与语音导览（已实现）

给定一帧摄像头画面，输出展品 ID + 置信度 + 中文名 + 单应性四边形，稳定命中后触发讲解词/语音播报。

```text
tracks/cultural-tourism/
├── README.md
├── requirements-linux.txt          # Ubuntu 20.04 / G1 依赖（Python 3.8）
├── configs/
│   ├── matcher.example.json        # 阈值：内点/比率/置信度/margin/粗筛
│   └── matcher.example.yaml        # 同内容 YAML
└── gdps_tourism/
    ├── camera/                     # V4L2 / AVFoundation / DirectShow / RealSense / 视频 / 图片
    ├── matching/                   # 模板库、ORB 粗筛、SIFT/ORB 精确匹配、展品组、滑窗投票
    └── cli/                        # 实时主循环、HUD 渲染、单图模式
```

入口：`scripts/tourism/match_webcam.py`；基准与验证：`scripts/tourism/bench_camera.py`、`tests/cultural_tourism/`。

## 模板目录（不入库）

模板图片与 `knowledge_base.json` 不打进仓库，用参数或环境变量指定：

```bash
export GDPS_TOURISM_TEMPLATES=/path/to/exhibit_templates   # 001.jpg..028.jpg、25.jpg、025.jpg + knowledge_base.json
```

- 文件名（不含扩展名）即展品 ID；`knowledge_base.json` 的 `exhibits[].associated_images` 用来做展品分组与中文名映射。
- 同一展品的多张模板（如 007/019、013/001、25/025）共享 `exhibit_id`：组内不互相竞争 margin，内容完全相同的模板自动去重。

## 运行

```bash
# Ubuntu 20.04 / 宇树 G1（无显示器自动 headless）
./scripts/tourism/run_linux_camera.sh

# macOS / 有显示器的 Ubuntu：直接调入口，带预览窗口
python3 scripts/tourism/match_webcam.py --templates "$GDPS_TOURISM_TEMPLATES" --camera 0 --method orb --prefilter orb

# 单图测试（不需要摄像头）
python3 scripts/tourism/match_webcam.py --templates "$GDPS_TOURISM_TEMPLATES" --image 001.jpg
```

三档性能策略（详见 `docs/deployment/2026-10-20-tourism-camera-ubuntu-g1.md`）：

| 档位 | 命令 | 单帧耗时（M1 基准） |
| --- | --- | --- |
| A 全量精确匹配（对照） | `--prefilter off` | SIFT ~380ms / ORB ~125ms |
| B 粗筛 + 短名单精匹配（默认） | `--prefilter orb` | SIFT ~105ms / ORB ~47ms |
| C 跳帧降频（叠加在 B 上） | `--match-every 2` | 预览不降频，匹配 15 次/秒上限 |

粗筛不确定时会先用短名单的精确结果判断，只有不够决定性才补扫全量，保证低纹理展品（25/025 银饼拓本）不漏检。

## 配置

```bash
python3 scripts/tourism/match_webcam.py --templates "$GDPS_TOURISM_TEMPLATES" \
  --config tracks/cultural-tourism/configs/matcher.example.yaml
```

关键阈值：`min_inliers=20`、`min_inlier_ratio=0.40`、`min_confidence=0.50`、`min_margin=0.15`（按展品组计算）。
时间投票按 `fps / match_every` 换算成结果次数，改跳帧不改变平滑时长。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests/cultural_tourism -v
.venv/bin/python scripts/tourism/bench_camera.py --templates "$GDPS_TOURISM_TEMPLATES" --method orb
```

## 现状与边界

- 已在 macOS（AVFoundation）与无显示器 Linux 路径上用合成场景/录像回放验证；真实 G1 摄像头与真实 Python 3.8 运行时尚未实机验证。
- 模板为固定视角照片，现场光照/反光/大角度需要按采集样本再调阈值。
