#!/usr/bin/env bash
# G1 EDU 现场一键部署+编译+诊断脚本（在机器人上运行，只读+构建，不发布运动）
# 用法: bash scripts/g1/field_setup.sh <archive.tar.gz> [target_dir]
#   archive.tar.gz: 通过 scp 上传的 git archive 包
#   target_dir:    默认 /home/unitree/gdps-2026-embodied-ai
set -euo pipefail

ARCHIVE="${1:-}"
TARGET="${2:-/home/unitree/gdps-2026-embodied-ai}"
LOG_DIR="${TARGET}/logs/field-setup"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/$(date +%Y%m%d-%H%M%S).log"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "用法: bash $0 <archive.tar.gz> [target_dir]" >&2
  echo "  archive 必须存在，例如 /tmp/gdps-2026-field.tar.gz" >&2
  exit 1
fi

log "=== G1 EDU 现场部署脚本 ==="
log "archive: $ARCHIVE"
log "target : $TARGET"
log "log    : $LOG"

# ---------- 1. 目标目录安全检查 ----------
log "--- [1/5] 目标目录检查 ---"
if [[ -d "$TARGET" ]]; then
  log "目标目录已存在，内容如下（不会自动删除）："
  ls -la "$TARGET" 2>/dev/null | tee -a "$LOG" || true
  # 检查是否已有厂商程序或他人数据
  if compgen -G "$TARGET/*" > /dev/null 2>&1; then
    log "警告: 目标目录非空，将在其下解压（不删除已有文件）。"
  fi
else
  log "目标目录不存在，创建: $TARGET"
  mkdir -p "$TARGET"
fi

# 禁止覆盖系统路径
case "$TARGET" in
  /|/home|/home/unitree|/opt|/usr|/etc|/root)
    log "错误: 禁止写入系统路径 $TARGET"; exit 1 ;;
esac

# ---------- 2. 解压 ----------
log "--- [2/5] 解压 $ARCHIVE 到 $TARGET ---"
# 解压前先清理我方 build/install/log（不删除用户其他文件）
rm -rf "$TARGET/shared/navigation/ros2_ws/build" \
       "$TARGET/shared/navigation/ros2_ws/install" \
       "$TARGET/shared/navigation/ros2_ws/log" 2>/dev/null || true
tar -xzf "$ARCHIVE" -C "$TARGET"
log "解压完成。"

# ---------- 3. ROS 2 Foxy 环境 ----------
log "--- [3/5] ROS 2 环境 ---"
if [[ -f /opt/ros/foxy/setup.bash ]]; then
  source /opt/ros/foxy/setup.bash
  log "已 source /opt/ros/foxy/setup.bash"
else
  log "错误: 未找到 /opt/ros/foxy/setup.bash，系统不是 Foxy？"; exit 1
fi
log "ROS_DISTRO=$ROS_DISTRO  RMW=$RMW_IMPLEMENTATION  PYTHON=$(python3 --version 2>&1)"

# ---------- 4. 依赖检查 ----------
log "--- [4/5] 构建依赖检查 ---"
MISSING=()
for pkg in sensor_msgs nav_msgs geometry_msgs std_msgs sensor_msgs_py tf2_ros; do
  if ! ros2 pkg list 2>/dev/null | grep -qx "$pkg"; then
    MISSING+=("$pkg")
  fi
done
log "缺失包: ${MISSING[*]:-(none)}"
if [[ ${#MISSING[@]} -gt 0 ]]; then
  log "警告: 缺失 ${#MISSING[@]} 个包，编译可能失败。"
  log "  尝试用: sudo apt install ros-foxy-${MISSING[0]//_/-} ..."
  log "  （需用户授权，本脚本不自动 apt install）"
fi

# ---------- 5. colcon build ----------
log "--- [5/5] colcon build ---"
cd "$TARGET/shared/navigation/ros2_ws"
log "工作目录: $(pwd)"
if command -v colcon >/dev/null 2>&1; then
  log "执行: colcon build --symlink-install --packages-select gdps_g1_navigation"
  colcon build --symlink-install --packages-select gdps_g1_navigation 2>&1 | tee -a "$LOG" || {
    log "colcon build 失败，请查看日志: $LOG"
    log "尝试不带 --packages-select 全量构建以获取更多信息..."
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
log "下一步运行传感器诊断:"
log "  bash $TARGET/scripts/g1/sensor_diag.sh"
log "日志: $LOG"
