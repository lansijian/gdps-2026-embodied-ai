#!/usr/bin/env bash
# Build the ROS 2 package. Prints the plan and waits for confirmation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WS="$ROOT/shared/navigation/ros2_ws"
echo "About to:"
echo "  1. source ROS 2 (you must already have Humble or compatible sourced)"
echo "  2. colcon build in $WS"
echo "  3. NOT install packages on the robot"
echo "  4. NOT start motion"
read -r -p "Type BUILD to continue: " ans
if [[ "$ans" != "BUILD" ]]; then
  echo "aborted"
  exit 1
fi
if ! command -v colcon >/dev/null; then
  echo "colcon not found. Source ROS 2 and install colcon, or build on the robot later."
  exit 2
fi
cd "$WS"
colcon build --symlink-install --packages-select gdps_g1_navigation
echo "source $WS/install/setup.bash"
