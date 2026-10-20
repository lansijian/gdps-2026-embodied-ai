#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
export RMW_IMPLEMENTATION="${G1_NAV_RMW:-${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}}"
case "$RMW_IMPLEMENTATION" in rmw_cyclonedds_cpp|rmw_fastrtps_cpp) ;; *) echo 'Unsupported G1_NAV_RMW'; exit 2;; esac
# No interface or domain is guessed; preserve the site's audited CycloneDDS URI.
log_run() { exec > >(tee -a "$ROOT/logs/$1-$(date -u +%Y%m%dT%H%M%SZ)-$$.log") 2>&1; }
source_ros() {
  python3 "$ROOT/scripts/ros_environment.py" --phase python --output "$ROOT/logs/python-environment-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
  test -f /opt/ros/foxy/setup.bash || { echo 'ROS 2 Foxy missing'; exit 2; }
  set +u; source /opt/ros/foxy/setup.bash; set -u
  if [[ "$RMW_IMPLEMENTATION" = rmw_cyclonedds_cpp && -f "$HOME/cyclonedds_ws/install/setup.bash" ]]; then
    set +u; source "$HOME/cyclonedds_ws/install/setup.bash"; set -u
  fi
  test "${ROS_DISTRO:-}" = foxy || { echo 'Only Foxy supported'; exit 2; }
}
source_overlay() {
  source_ros
  test -f "$ROOT/install/setup.bash" || { echo 'Build the workspace first'; exit 2; }
  set +u; source "$ROOT/install/setup.bash"; set -u
  export G1_NAV_LOG_DIR="$ROOT/logs"
  if [[ "$RMW_IMPLEMENTATION" = rmw_cyclonedds_cpp ]]; then
    export G1_NAV_PREVIOUS_DDS_URI="${CYCLONEDDS_URI:-}"
    export CYCLONEDDS_URI="file://${G1_NAV_DDS_CONFIG:-$ROOT/src/g1_nav_config/config/cyclonedds.xml}"
  fi
  python3 "$ROOT/scripts/ros_environment.py" --phase rmw --output "$ROOT/logs/rmw-environment-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
}
