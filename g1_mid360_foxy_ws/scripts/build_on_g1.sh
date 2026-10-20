#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run build
source_ros
test "$(uname -m)" = aarch64 || { echo 'G1 build requires ARM64'; exit 2; }
grep -q 'VERSION_ID="20.04"' /etc/os-release || { echo 'Ubuntu 20.04 required'; exit 2; }
command -v colcon
cd "$ROOT"
colcon list --base-paths src
colcon build --base-paths src --executor sequential --event-handlers console_direct+
source_overlay
for pkg in g1_nav_bringup g1_nav_perception g1_nav_tf g1_nav_tf_authority g1_nav_bridge g1_nav_config g1_ros2_bridge; do
  ros2 pkg prefix "$pkg"
done
ros2 launch g1_nav_bringup g1_nav_bringup.launch.py --show-args
