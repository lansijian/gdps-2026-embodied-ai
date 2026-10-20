#!/usr/bin/env bash
# =============================================================================
# 文旅赛道 · 展品摄像头识别导览 · Ubuntu 20.04 / 宇树 G1 启动脚本
#
# 仓库布局：
#   <repo>/scripts/tourism/run_linux_camera.sh      <- 本脚本
#   <repo>/scripts/tourism/match_webcam.py          <- 入口
#   <repo>/tracks/cultural-tourism/gdps_tourism/    <- 匹配包
#
# 模板图片（001.jpg..028.jpg、25.jpg、025.jpg + knowledge_base.json）不入库，
# 必须用 --templates 或环境变量 GDPS_TOURISM_TEMPLATES 指定目录。
#
# 用法：
#   export GDPS_TOURISM_TEMPLATES=$HOME/exhibit_templates
#   ./scripts/tourism/run_linux_camera.sh                    # 实时快速档
#   CAMERA=1 ./scripts/tourism/run_linux_camera.sh           # 第二台摄像头
#   ./scripts/tourism/run_linux_camera.sh --accurate         # sift + 粗筛
#   ./scripts/tourism/run_linux_camera.sh --no-prefilter     # 关闭粗筛基线
#   ./scripts/tourism/run_linux_camera.sh --image 001.jpg
#   ./scripts/tourism/run_linux_camera.sh --video clip.mp4 --headless
#   ./scripts/tourism/run_linux_camera.sh --list-cameras
# 其余参数原样透传给 match_webcam.py。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd )"
ENTRY="$SCRIPT_DIR/match_webcam.py"

if [ ! -f "$ENTRY" ]; then
    echo "[tourism] 找不到入口: $ENTRY" >&2
    exit 2
fi

# 解释器优先级：PYTHON > 仓库 .venv > 系统 python3
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "[tourism] 找不到 python3，请先安装 Python 3.8+（见 docs/deployment/2026-10-20-tourism-camera-ubuntu-g1.md）" >&2
    exit 2
fi

has_arg() {
    local name="$1"; shift
    local arg
    for arg in "$@"; do
        if [ "$arg" = "$name" ]; then return 0; fi
        case "$arg" in "$name"=*) return 0 ;; esac
    done
    return 1
}

forward=()
want_accurate=0
want_no_prefilter=0
for arg in "$@"; do
    case "$arg" in
        --accurate) want_accurate=1 ;;
        --no-prefilter) want_no_prefilter=1 ;;
        *) forward+=("$arg") ;;
    esac
done

extra=()

if [ "$want_accurate" -eq 1 ] && ! has_arg --method ${forward[@]+"${forward[@]}"}; then
    extra+=(--method sift)
fi
if [ "$want_no_prefilter" -eq 1 ] && ! has_arg --prefilter ${forward[@]+"${forward[@]}"}; then
    extra+=(--prefilter off)
fi

# 实时相机快速档默认值；单图 / 视频 / 枚举模式沿用 CLI 默认
if ! has_arg --image ${forward[@]+"${forward[@]}"} && ! has_arg --video ${forward[@]+"${forward[@]}"} && ! has_arg --list-cameras ${forward[@]+"${forward[@]}"}; then
    if ! has_arg --camera ${forward[@]+"${forward[@]}"}; then
        extra+=(--camera "${CAMERA:-0}")
    fi
    if ! has_arg --method ${forward[@]+"${forward[@]}"} && ! has_arg --method ${extra[@]+"${extra[@]}"}; then
        extra+=(--method orb)
    fi
    if ! has_arg --prefilter ${forward[@]+"${forward[@]}"} && ! has_arg --prefilter ${extra[@]+"${extra[@]}"}; then
        extra+=(--prefilter orb)
    fi
    if ! has_arg --match-every ${forward[@]+"${forward[@]}"}; then
        extra+=(--match-every 2)
    fi
fi

# 模板目录：命令行 > GDPS_TOURISM_TEMPLATES（实时/单图/视频模式都适用）
if ! has_arg --templates ${forward[@]+"${forward[@]}"} && [ -n "${GDPS_TOURISM_TEMPLATES:-}" ]; then
    extra+=(--templates "$GDPS_TOURISM_TEMPLATES")
fi

# 无显示环境自动 headless
if [ "$(uname -s)" = "Linux" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] \
    && ! has_arg --headless ${forward[@]+"${forward[@]}"} \
    && ! has_arg --help ${forward[@]+"${forward[@]}"} && ! has_arg -h ${forward[@]+"${forward[@]}"}; then
    extra+=(--headless)
fi

# 模板目录必须可用（仓库不存模板图）
if ! has_arg --templates ${extra[@]+"${extra[@]}"} && ! has_arg --templates ${forward[@]+"${forward[@]}"} \
    && ! has_arg --list-cameras ${forward[@]+"${forward[@]}"} \
    && ! has_arg --help ${forward[@]+"${forward[@]}"} && ! has_arg -h ${forward[@]+"${forward[@]}"}; then
    echo "[tourism] 缺少模板目录：请设置 GDPS_TOURISM_TEMPLATES 或传 --templates <目录>" >&2
    echo "[tourism] 目录内需含 001.jpg..028.jpg、25.jpg、025.jpg 与 knowledge_base.json" >&2
    exit 2
fi

echo "[tourism] python=$PY repo=$REPO_ROOT" >&2
exec "$PY" "$ENTRY" ${extra[@]+"${extra[@]}"} ${forward[@]+"${forward[@]}"}
