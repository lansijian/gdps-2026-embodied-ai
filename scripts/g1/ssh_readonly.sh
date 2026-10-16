#!/usr/bin/env bash
# SSH read-only diagnostics. Fill user/IP yourself. Never pass a password on the CLI.
set -euo pipefail
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <authorized-user> <verified-robot-ip>"
  echo "Does not guess credentials. Run only after those values are confirmed."
  exit 1
fi
USER_NAME="$1"
HOST="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOGDIR="$ROOT/logs/g1-ssh"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/ssh-$HOST-$(date +%Y%m%d-%H%M%S).txt"
echo "Connecting to ${USER_NAME}@${HOST} (read-only remote commands)"
ssh -o StrictHostKeyChecking=accept-new "${USER_NAME}@${HOST}" 'bash -s' <<'REMOTE' | tee "$LOG"
set +e
echo "=== hostname ==="
hostname
echo "=== uname ==="
uname -a
echo "=== os-release ==="
cat /etc/os-release
echo "=== ip ==="
ip -br addr
echo "=== python ==="
python3 --version
echo "=== /opt/ros ==="
ls /opt/ros
echo "=== df ==="
df -h
echo "=== which ros2 ==="
command -v ros2
echo "If ros2 is missing, try: source /opt/ros/humble/setup.bash  (distro UNVERIFIED)"
if command -v ros2 >/dev/null; then
  ros2 doctor --report || true
  ros2 topic list -t || true
  ros2 node list || true
else
  for d in /opt/ros/*; do
    if [[ -f "$d/setup.bash" ]]; then
      echo "sourcing $d/setup.bash"
      # shellcheck disable=SC1090
      source "$d/setup.bash"
      command -v ros2 && ros2 doctor --report
      command -v ros2 && ros2 topic list -t
      command -v ros2 && ros2 node list
      break
    fi
  done
fi
REMOTE
echo "saved $LOG (contains host/network names; do not add passwords or keys)"
