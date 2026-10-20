#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run preflight
source_ros
python3 "$ROOT/scripts/ros_environment.py" --phase rmw --output "$ROOT/logs/preflight-rmw-$$.json"
failed=0
uname -a
cat /etc/os-release
test "$(dpkg --print-architecture)" = arm64 || { echo 'TARGET_ARCH_MISMATCH: ARM64 required on G1'; failed=1; }
grep -q 'VERSION_ID="20.04"' /etc/os-release || { echo 'Ubuntu 20.04 required'; failed=1; }
python3 --version
ip -brief address
printf 'RMW=%s ROS_DOMAIN_ID=%s CYCLONEDDS_URI=%s\n' "$RMW_IMPLEMENTATION" "${ROS_DOMAIN_ID:-UNSET}" "${CYCLONEDDS_URI:-UNSET}"
for pkg in nav2_bringup slam_toolbox pointcloud_to_laserscan rmw_cyclonedds_cpp; do
  ros2 pkg prefix "$pkg" || failed=1
done
apt-cache policy ros-foxy-nav2-bringup ros-foxy-slam-toolbox ros-foxy-pointcloud-to-laserscan
grep -RhE '^[[:space:]]*deb .*ros' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null || true
command -v rosdep || true
ros2 topic list -t
for topic in /utlidar/cloud_livox_mid360 /utlidar/imu_livox_mid360 /dog_odom /tf /tf_static /scan; do
  ros2 topic info "$topic" --verbose || true
done
if test -f "$ROOT/install/setup.bash"; then
  source_overlay
  ros2 run g1_nav_perception clock_preflight --duration 30 --output "$ROOT/logs/clock-preflight.json" || failed=1
else
  echo 'Clock subscription audit pending overlay build'; failed=1
fi
python3 "$ROOT/scripts/sdk_audit.py" --output "$ROOT/logs/sdk-audit.json" || failed=1
exit "$failed"
