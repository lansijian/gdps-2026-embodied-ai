#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# No interface or domain is guessed; preserve the site's audited CycloneDDS URI.
log_run() { exec > >(tee -a "$ROOT/logs/$1-$(date -u +%Y%m%dT%H%M%SZ)-$$.log") 2>&1; }
source_ros() {
  test -f /opt/ros/foxy/setup.bash || { echo 'ROS 2 Foxy missing'; exit 2; }
  set +u; source /opt/ros/foxy/setup.bash; set -u
  test "${ROS_DISTRO:-}" = foxy || { echo 'Only Foxy supported'; exit 2; }
}
source_overlay() {
  source_ros
  test -f "$ROOT/install/setup.bash" || { echo 'Build the workspace first'; exit 2; }
  set +u; source "$ROOT/install/setup.bash"; set -u
}
