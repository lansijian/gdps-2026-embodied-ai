#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
log_run dependencies
source_ros
case "${1:---plan}" in --plan|--install) ;; *) echo 'Usage: install_dependencies.sh --plan|--install'; exit 2;; esac
python3 "$ROOT/scripts/dependency_plan.py" "$1" "$ROOT/logs/dependencies.json"
