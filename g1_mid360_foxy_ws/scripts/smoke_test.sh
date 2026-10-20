#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run smoke
source_overlay
ros2 run g1_nav_perception smoke --ros-args -p duration_s:=30.0 -p timeout_s:=60.0
timeout 10 ros2 run tf2_ros tf2_echo odom robot_center > "$ROOT/logs/tf-odom.txt" 2>&1 &
pid=$!
wait "$pid" || test "$?" = 124
grep -q 'Translation' "$ROOT/logs/tf-odom.txt"
timeout 10 ros2 run tf2_ros tf2_echo robot_center livox_frame > "$ROOT/logs/tf-livox.txt" 2>&1 &
pid=$!
wait "$pid" || test "$?" = 124
grep -q 'Translation' "$ROOT/logs/tf-livox.txt"
echo 'Sensor gate complete; this does not assert map, planning, localization, motion or hardware acceptance.'
