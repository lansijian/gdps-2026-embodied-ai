#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run stack
source_overlay
mode="${1:-sensor_check}"
case "$mode" in --check-only) shift; mode=sensor_check; extra=(check_only:=true);; --nav2-only) shift; mode=dry_run; extra=(nav2_only:=true);; sensor_check|mapping|localization|dry_run|navigation) shift || true; extra=();; *) echo 'Usage: start_stack.sh MODE [site.yaml] [map.yaml] [name:=value ...]'; exit 2;; esac
args=(mode:="$mode" rmw:="$RMW_IMPLEMENTATION" "${extra[@]}")
site_path="${G1_NAV_SITE:-$ROOT/config/site.g1_default.yaml}"
if [[ -n "${1:-}" && "$1" != *:=* ]]; then site_path="$(realpath "$1")"; shift; fi
args+=(site:="$site_path")
if [[ -n "${1:-}" && "$1" != *:=* ]]; then args+=(map:="$(realpath "$1")"); shift; fi
echo 'Stage3: legacy cleanup -> offset calibration -> direct projected odom TF -> scan -> SLAM/Nav2. LIVE default OFF.'
exec ros2 launch g1_nav_bringup g1_nav_bringup.launch.py "${args[@]}" "$@"
