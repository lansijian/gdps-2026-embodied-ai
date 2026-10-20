#!/usr/bin/env bash
# Reference: nav2_map_server map_saver_cli; slam_toolbox SerializePoseGraph service (Foxy).
# Run while the mapping launch is still up, after a closed loop looks clean in RViz.
set -euo pipefail
MAP_DIR="$HOME/g1_nav2_ws/maps"
POSEGRAPH_DIR="/home/unitree/maps"
mkdir -p "$MAP_DIR" "$POSEGRAPH_DIR"
ros2 run nav2_map_server map_saver_cli -f "$MAP_DIR/site"
ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \
  "{filename: '$POSEGRAPH_DIR/site_posegraph'}"
echo "saved: $MAP_DIR/site.pgm + $MAP_DIR/site.yaml ; $POSEGRAPH_DIR/site_posegraph.posegraph"
