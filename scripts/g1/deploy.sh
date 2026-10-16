#!/usr/bin/env bash
# Copy repo to a NON-SYSTEM directory on the robot. Confirmation required.
set -euo pipefail
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <authorized-user> <verified-robot-ip> <remote-dir>"
  echo "Example remote-dir: /home/<user>/gdps-2026-embodied-ai"
  echo "Will NOT write under /opt, /usr, or overwrite Unitree services."
  exit 1
fi
USER_NAME="$1"
HOST="$2"
REMOTE_DIR="$3"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$REMOTE_DIR" in
  /opt/*|/usr/*|/etc/*|/boot/*)
    echo "refusing system path $REMOTE_DIR"
    exit 2
    ;;
esac
echo "rsync $ROOT -> ${USER_NAME}@${HOST}:$REMOTE_DIR"
echo "excludes: .git .research logs __pycache__"
echo "will NOT restart robot services"
read -r -p "Type DEPLOY to continue: " ans
if [[ "$ans" != "DEPLOY" ]]; then
  echo "aborted"
  exit 1
fi
rsync -av --delete --exclude '.git' --exclude '.research' --exclude 'logs' \
  --exclude '__pycache__' --exclude 'build' --exclude 'install' --exclude 'log' \
  "$ROOT/" "${USER_NAME}@${HOST}:${REMOTE_DIR}/"
echo "deployed. Next: SSH and run read-only checks. Do not start live motion."
