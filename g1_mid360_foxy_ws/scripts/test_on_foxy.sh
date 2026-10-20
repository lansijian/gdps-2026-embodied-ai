#!/usr/bin/env bash
set -euo pipefail
[[ "${G1_NAV_TEST_ONLY:-}" = 1 && "${ROS_DOMAIN_ID:-}" = 87 ]] || { echo 'Run only in isolated SYNTHETIC_TEST domain 87; NEVER on a connected robot domain'; exit 2; }
source "$(dirname "$0")/common.sh"
source_overlay
cd "$ROOT"
log_run test-foxy
python3 -m pytest tests/test_contracts.py tests/test_scripts.py tests/test_field_fixes.py tests/test_stage3.py -q --junitxml=logs/field-fix-r2-pytest.xml
python3 tests/ros_negative_launch.py
python3 tests/ros_field_regression.py
python3 tests/ros_integration.py
