#!/usr/bin/env bash
# SSH read-only diagnostics. Fill user/IP yourself. Never pass a password on the CLI.
# Does not change network, apt, systemd, or send motion.
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
echo "Connecting to ${USER_NAME}@${HOST} (read-only remote commands; no motion)"
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${USER_NAME}@${HOST}" 'bash -s' <<'REMOTE' | tee "$LOG"
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
echo "=== /opt/ros (do not assume Humble) ==="
ls /opt/ros 2>/dev/null || echo "no /opt/ros"
echo "=== df ==="
df -h
echo "=== env RMW / DDS / ROS_DOMAIN (names only) ==="
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION-unset}"
echo "CYCLONEDDS_URI=${CYCLONEDDS_URI-unset}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID-unset}"
echo "=== which ros2 ==="
command -v ros2 || echo "ros2 not on PATH yet"

source_ros() {
  if command -v ros2 >/dev/null; then
    return 0
  fi
  if [[ ! -d /opt/ros ]]; then
    echo "no /opt/ros; cannot source"
    return 1
  fi
  local d
  for d in /opt/ros/*; do
    if [[ -f "$d/setup.bash" ]]; then
      echo "sourcing $d/setup.bash (distro from directory name, not assumed)"
      # shellcheck disable=SC1090
      source "$d/setup.bash"
      return 0
    fi
  done
  return 1
}

if source_ros && command -v ros2 >/dev/null; then
  echo "=== ros2 doctor --report ==="
  ros2 doctor --report || true
  echo "=== ros2 topic list -t ==="
  ros2 topic list -t || true
  echo "=== ros2 node list ==="
  ros2 node list || true
  echo "=== topic name hints (presence only) ==="
  ros2 topic list 2>/dev/null | grep -Ei 'livox|mid360|points|cloud|scan|odom|tf|imu|sport|cmd_vel|unitree' || echo "(no matching topic names)"
  echo "=== try tf once (may be empty) ==="
  timeout 3 ros2 topic echo /tf --once 2>/dev/null || echo "no /tf echo (missing topic, timeout, or no timeout(1))"
else
  echo "ROS 2 CLI still unavailable after source attempt — not concluding the image has no ROS"
fi

echo "=== python unitree_sdk2py (import only) ==="
python3 - <<'PY'
try:
    import unitree_sdk2py
    print("unitree_sdk2py=", getattr(unitree_sdk2py, "__file__", "imported"))
    try:
        from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        print("LocoClient=import_ok")
    except Exception as exc:
        print("LocoClient=import_fail", type(exc).__name__, exc)
except Exception as exc:
    print("unitree_sdk2py=missing", type(exc).__name__, exc)
PY

echo "=== DDS / cyclonedds files if present (paths only) ==="
ls /etc/cyclonedds.xml /home/*/.cyclonedds.xml 2>/dev/null || echo "no obvious cyclonedds.xml"
echo "=== DONE read-only ==="
REMOTE
echo "saved $LOG (host/network names only; do not add passwords or keys)"
echo "Do not start navigation or live motion from this step."
