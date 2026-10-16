#!/usr/bin/env bash
# Software stop overlay: publish manual stop if ROS 2 is available.
# This is NOT a hardware e-stop.
set -euo pipefail
echo "Software stop only. Use the hardware e-stop if the robot is unstable."
if ! command -v ros2 >/dev/null; then
  echo "ros2 not on PATH. On the robot run LocoClient StopMove from a verified SDK example, or press hardware e-stop."
  exit 1
fi
ros2 topic pub --once /gdps/manual_stop std_msgs/msg/String "{data: stop}"
echo "published /gdps/manual_stop"
