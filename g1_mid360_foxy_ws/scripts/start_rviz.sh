#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
source_overlay
case "${1:-navigation}" in
  audit) config="$ROOT/src/g1_nav_config/rviz/sensor_audit.rviz" ;;
  calibration) config="$ROOT/src/g1_nav_config/rviz/calibration.rviz" ;;
  navigation) config="$ROOT/src/g1_nav_config/rviz/g1_nav.rviz" ;;
  *) echo 'Usage: bash scripts/start_rviz.sh audit|calibration|navigation'; exit 2 ;;
esac
exec rviz2 -d "$config"
