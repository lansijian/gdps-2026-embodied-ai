#!/usr/bin/env bash
# G1 EDU 现场一键部署+编译+诊断脚本（在机器人上运行，只读+构建，不发布运动）
# 用法: bash scripts/g1/field_setup.sh <archive.tar.gz> [target_dir]
#   archive.tar.gz: 通过 scp 上传的 git archive 包
#   target_dir:    默认 /home/unitree/gdps-2026-embodied-ai
#
# 安全约束:
#   - 先校验 archive 与目标路径，再创建任何目录或写入文件
#   - 禁止写入系统路径
#   - 不执行 rm -rf，不删除任何已有文件
#   - tar 使用 --keep-old-files，不覆盖已有文件
#   - 不 apt install，不修改厂商系统，不发布运动指令
set -euo pipefail

ARCHIVE="${1:-}"
TARGET="${2:-/home/unitree/gdps-2026-embodied-ai}"

# ---------- 0. 前置校验（在任何写入之前） ----------
# 校验 archive 参数
if [[ -z "$ARCHIVE" ]]; then
  echo "用法: bash $0 <archive.tar.gz> [target_dir]" >&2
  echo "  archive 必须存在，例如 /tmp/gdps-2026-field.tar.gz" >&2
  exit 1
fi

# 解析 archive 绝对路径，校验不是符号链接且是普通文件
ARCHIVE_ABS="$(cd "$(dirname "$ARCHIVE")" 2>/dev/null && pwd)/$(basename "$ARCHIVE")"
if [[ ! -f "$ARCHIVE_ABS" || -L "$ARCHIVE_ABS" ]]; then
  echo "错误: archive 不存在、是符号链接或非普通文件: $ARCHIVE" >&2
  exit 1
fi

# 校验目标路径不是系统路径
case "$TARGET" in
  /|/home|/home/unitree|/opt|/usr|/etc|/root|/tmp)
    echo "错误: 禁止写入系统路径 $TARGET" >&2; exit 1 ;;
esac

# 校验目标路径不是符号链接
if [[ -L "$TARGET" ]]; then
  echo "错误: 目标路径是符号链接，拒绝写入: $TARGET" >&2
  exit 1
fi

# 校验目标路径的父目录存在且不是符号链接
PARENT="$(dirname "$TARGET")"
if [[ ! -d "$PARENT" || -L "$PARENT" ]]; then
  echo "错误: 目标父目录不存在或是符号链接: $PARENT" >&2
  exit 1
fi

# 校验目标路径不以 / 结尾（避免路径拼接问题）
TARGET="${TARGET%/}"

# 校验通过后才创建日志目录
LOG_DIR="${TARGET}/logs/field-setup"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/$(date +%Y%m%d-%H%M%S).log"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "=== G1 EDU 现场部署脚本 ==="
log "archive: $ARCHIVE_ABS"
log "target : $TARGET"
log "log    : $LOG"

# ---------- 1. 目标目录内容检查 ----------
log "--- [1/6] 目标目录检查 ---"
if [[ -d "$TARGET" ]]; then
  log "目标目录已存在，内容如下（不会自动删除任何文件）："
  ls -la "$TARGET" 2>/dev/null | tee -a "$LOG" || true
  if [[ -f "$TARGET/README.md" ]]; then
    log "检测到我方 README.md，判定为我方历史部署。"
  else
    log "警告: 目标目录无我方 README.md，可能含他人数据。"
    log "  将使用 --keep-old-files，不覆盖任何已有文件。"
  fi
else
  log "目标目录不存在，创建: $TARGET"
  mkdir -p "$TARGET"
fi

# ---------- 2. 解压（不覆盖已有文件，不删除任何文件） ----------
log "--- [2/6] 解压 $ARCHIVE_ABS 到 $TARGET ---"
log "使用 --keep-old-files，已存在的文件将被保留不覆盖。"
tar -xzf "$ARCHIVE_ABS" -C "$TARGET" --keep-old-files 2>&1 | tee -a "$LOG" || \
  log "警告: tar 部分文件因已存在而跳过（符合预期）。"
log "解压完成。"

# ---------- 3. ROS 2 Foxy 环境 ----------
log "--- [3/6] ROS 2 环境 ---"
if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
  log "已 source /opt/ros/foxy/setup.bash"
else
  log "错误: 未找到 /opt/ros/foxy/setup.bash，系统不是 Foxy？"; exit 1
fi
log "ROS_DISTRO=${ROS_DISTRO:-}  RMW=${RMW_IMPLEMENTATION:-}  PYTHON=$(python3 --version 2>&1)"

# ---------- 4. 依赖检查 ----------
log "--- [4/6] 构建依赖检查 ---"
MISSING=()
for pkg in sensor_msgs nav_msgs geometry_msgs std_msgs sensor_msgs_py tf2_ros; do
  if ! ros2 pkg list 2>/dev/null | grep -qx "$pkg"; then
    MISSING+=("$pkg")
  fi
done
log "缺失包: ${MISSING[*]:-(none)}"
if [[ ${#MISSING[@]} -gt 0 ]]; then
  log "警告: 缺失 ${#MISSING[@]} 个包，编译可能失败。"
  log "  如需安装: sudo apt install ros-foxy-${MISSING[0]//_/-} ..."
  log "  （需用户授权，本脚本不自动 apt install）"
fi

# ---------- 5. colcon build ----------
log "--- [5/6] colcon build ---"
cd "$TARGET/shared/navigation/ros2_ws"
log "工作目录: $(pwd)"
if command -v colcon >/dev/null 2>&1; then
  log "执行: colcon build --symlink-install --packages-select gdps_g1_navigation"
  colcon build --symlink-install --packages-select gdps_g1_navigation 2>&1 | tee -a "$LOG" || {
    log "colcon build 失败，详细错误见上方输出或日志: $LOG"
    exit 1
  }
  log "colcon build 成功。"
else
  log "错误: colcon 未安装"; exit 1
fi

# 验证包可被找到
log "验证包可见性:"
source install/setup.bash
ros2 pkg list 2>/dev/null | grep -i gdps || log "警告: 未在包列表中找到 gdps 包"
ros2 pkg executables gdps_g1_navigation 2>/dev/null || log "警告: 无法列出 gdps_g1_navigation 可执行文件"

log ""
log "=== 部署+编译完成 ==="

# ---------- 6. 传感器只读诊断 ----------
log ""
log "--- [6/6] 传感器只读诊断（sensor_diag.sh） ---"
DIAG_SCRIPT="$TARGET/scripts/g1/sensor_diag.sh"
if [[ -f "$DIAG_SCRIPT" ]]; then
  log "运行: bash $DIAG_SCRIPT"
  log "（只读：订阅/echo/info/hz，不发布、不移动机器人）"
  bash "$DIAG_SCRIPT" 2>&1 | tee -a "$LOG" || log "sensor_diag.sh 退出码非零，见日志"
else
  log "警告: 未找到 $DIAG_SCRIPT"
fi

log ""
log "=== 全部完成 ==="
log "完整日志: $LOG"
log "请把本脚本的全部输出（或上述日志文件内容）发给开发端分析。"
