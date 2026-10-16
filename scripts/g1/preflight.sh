#!/usr/bin/env bash
# Read-only preflight on Ubuntu / WSL. Does not change network config.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOGDIR="${1:-$ROOT/logs/g1-preflight}"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/preflight-$(date +%Y%m%d-%H%M%S).txt"
exec > >(tee -a "$LOG") 2>&1
echo "GDPS G1 preflight (bash, read-only)"
echo "repo=$ROOT"
uname -a
cat /etc/os-release || true
hostname
python3 "$ROOT/scripts/g1/detect_host.py" || python "$ROOT/scripts/g1/detect_host.py"
echo "--- ip ---"
ip -br addr || true
command -v nmcli >/dev/null && nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev || true
echo "--- ros ---"
ls /opt/ros 2>/dev/null || echo "no /opt/ros"
if command -v ros2 >/dev/null; then
  echo "ros2 found on PATH"
else
  echo "ros2 not on PATH; source /opt/ros/<distro>/setup.bash before judging ROS missing"
fi
echo "Candidate robot IP 192.168.123.164 is UNVERIFIED."
echo "SSH after you confirm user/IP: ssh <authorized-user>@<verified-robot-ip>"
echo "log=$LOG"
