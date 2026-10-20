#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run map-save
source_overlay
target="${1:?Usage: save_map.sh /absolute/new/map_basename [--pose-graph]}"
test "${target:0:1}" = / || { echo 'Absolute path required'; exit 2; }
test ! -e "$target.yaml" && test ! -e "$target.pgm" && test ! -e "$target.posegraph" || { echo 'Refusing to overwrite map'; exit 2; }
mkdir -p "$(dirname "$target")"
ros2 run nav2_map_server map_saver_cli -f "$target" --ros-args -p use_sim_time:=false -p save_map_timeout:=10000 -p map_subscribe_transient_local:=true
if test "${2:-}" = --pose-graph; then
  # JSON string encoding prevents YAML injection in user paths.
  request="$(python3 -c 'import json,sys; print(json.dumps({"filename":sys.argv[1]}))' "$target")"
  ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph "$request"
  test -s "$target.posegraph" && test -s "$target.data"
fi
test -s "$target.yaml"
