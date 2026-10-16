#!/usr/bin/env bash
# Copy repo to a NON-SYSTEM directory on the robot. Confirmation required.
# Default: rsync WITHOUT --delete (will not remove extra remote files).
# --delete is opt-in and requires a remote sentinel file.
set -euo pipefail

usage() {
  echo "Usage: $0 <authorized-user> <verified-robot-ip> <remote-dir> [--delete]"
  echo "Example remote-dir: /home/<user>/gdps-2026-embodied-ai"
  echo "Will NOT write under /opt, /usr, /etc, /boot, or home roots."
  echo "rsync --delete is OFF unless you pass --delete AND the remote sentinel exists."
}

if [[ $# -lt 3 ]]; then
  usage
  exit 1
fi

USER_NAME="$1"
HOST="$2"
REMOTE_DIR="$3"
ALLOW_DELETE=0
if [[ $# -ge 4 ]]; then
  if [[ "$4" == "--delete" ]]; then
    ALLOW_DELETE=1
  else
    echo "unknown extra argument: $4"
    usage
    exit 1
  fi
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SENTINEL=".gdps-g1-deploy-root"
ALLOWED_BASENAMES="gdps-2026-embodied-ai|gdps-ws|gdps_g1_ws"

if [[ -z "$REMOTE_DIR" || "$REMOTE_DIR" == "/" ]]; then
  echo "refusing empty or root path"
  exit 2
fi
if [[ "$REMOTE_DIR" != /* ]]; then
  echo "refusing relative path $REMOTE_DIR (must be absolute on the robot)"
  exit 2
fi

case "$REMOTE_DIR" in
  /|/home|/home/|/root|/root/|/tmp|/tmp/|/var|/var/*|/opt|/opt/*|/usr|/usr/*|/etc|/etc/*|/boot|/boot/*|/mnt|/mnt/*|/media|/media/*|/dev|/dev/*|/proc|/proc/*|/sys|/sys/*)
    echo "refusing system or too-broad path $REMOTE_DIR"
    exit 2
    ;;
esac

depth="$(awk -F/ '{print NF-1}' <<<"${REMOTE_DIR%/}")"
if [[ "$depth" -lt 3 ]]; then
  echo "refusing shallow path $REMOTE_DIR (need at least /home/<user>/<project>)"
  exit 2
fi

base="$(basename "$REMOTE_DIR")"
if [[ ! "$base" =~ ^($ALLOWED_BASENAMES)$ ]]; then
  echo "refusing basename '$base'."
  echo "allowed: gdps-2026-embodied-ai, gdps-ws, gdps_g1_ws"
  echo "this avoids rsync into an unrelated existing folder."
  exit 2
fi

RSYNC_FLAGS=(-av --exclude '.git' --exclude '.research' --exclude 'logs'
  --exclude '__pycache__' --exclude 'build' --exclude 'install' --exclude 'log'
  --exclude "$SENTINEL")
if [[ "$ALLOW_DELETE" -eq 1 ]]; then
  DELETE_NOTE="--delete requested (blocked unless remote $SENTINEL exists)"
else
  DELETE_NOTE="--delete OFF (remote extras kept)"
fi

echo "plan:"
echo "  src:  $ROOT/"
echo "  dest: ${USER_NAME}@${HOST}:$REMOTE_DIR/"
echo "  $DELETE_NOTE"
echo "  will NOT restart robot services, change IP, or send motion"
echo "  excluded: .git .research logs __pycache__ build install log"

read -r -p "Type DEPLOY to continue: " ans
if [[ "$ans" != "DEPLOY" ]]; then
  echo "aborted"
  exit 1
fi

qdir="$(printf '%q' "$REMOTE_DIR")"
qsent="$(printf '%q' "$SENTINEL")"
remote_state="$(ssh -o BatchMode=yes "${USER_NAME}@${HOST}" \
  "d=$qdir; s=$qsent; if [ ! -e \"\$d\" ]; then echo MISSING; elif [ ! -d \"\$d\" ]; then echo NOTDIR; elif [ -f \"\$d/\$s\" ]; then echo SENTINEL; else n=\$(find \"\$d\" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' '); echo EXISTS:\$n; fi")" || {
  echo "SSH probe failed. Fix SSH first; not deploying."
  exit 3
}

echo "remote_state=$remote_state"
if [[ "$remote_state" == "NOTDIR" ]]; then
  echo "remote path exists but is not a directory; abort"
  exit 4
fi

if [[ "$ALLOW_DELETE" -eq 1 ]]; then
  if [[ "$remote_state" != "SENTINEL" ]]; then
    echo "refusing --delete: remote lacks $SENTINEL"
    echo "first deploy WITHOUT --delete so the sentinel can be created."
    exit 5
  fi
  RSYNC_FLAGS+=(--delete)
  echo "remote sentinel found; using rsync --delete"
else
  echo "rsync without --delete"
fi

if [[ "$remote_state" == "MISSING" ]]; then
  ssh -o BatchMode=yes "${USER_NAME}@${HOST}" "mkdir -p $qdir"
fi

rsync "${RSYNC_FLAGS[@]}" "$ROOT/" "${USER_NAME}@${HOST}:${REMOTE_DIR}/"
ssh -o BatchMode=yes "${USER_NAME}@${HOST}" \
  "d=$qdir; s=$qsent; printf 'gdps-2026-embodied-ai deploy target\n' > \"\$d/\$s\""
echo "deployed. Sentinel $SENTINEL written on the robot."
echo "Next: SSH read-only checks. Do not start live motion."
echo "To later sync deletions, re-run with --delete only against this same path."
