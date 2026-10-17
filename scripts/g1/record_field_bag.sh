#!/usr/bin/env bash
# Read-only rosbag2 recording, preview is the default. No services or motion SDK.
set -euo pipefail
source /opt/ros/foxy/setup.bash
DURATION="${DURATION:-20}"
OUT="${OUT:-$HOME/gdps_bags/field_$(date +%Y%m%d_%H%M%S)}"
if [[ ! "$DURATION" =~ ^[0-9]+$ ]] || (( DURATION < 1 || DURATION > 60 )); then
  echo 'DURATION must be 1..60 seconds' >&2; exit 2
fi
[[ ! -e "$OUT" ]] || { echo 'Output exists; refusing overwrite' >&2; exit 2; }
mkdir -p "$(dirname "$OUT")"
AVAILABLE="$(ros2 topic list)"
TOPICS=()
for topic in "${RGB_TOPIC:-}" "${DEPTH_TOPIC:-}" "${CAMERA_INFO_TOPIC:-}" \
  "${PC_TOPIC:-/utlidar/cloud_livox_mid360}" "${SCAN_TOPIC:-/scan}" \
  "${ODOM_TOPIC:-/dog_odom}" /tf /tf_static "${JOINT_TOPIC:-/joint_states}"; do
  [[ -z "$topic" ]] && continue
  # Allow only expected read-only sensor types, even if an environment variable is wrong.
  if ! grep -Fxq "$topic" <<< "$AVAILABLE"; then echo "Missing (not selected): $topic"; continue; fi
  TYPE="$(ros2 topic type "$topic")"
  case "$TYPE" in
    sensor_msgs/msg/Image|sensor_msgs/msg/CameraInfo|sensor_msgs/msg/PointCloud2|sensor_msgs/msg/LaserScan|sensor_msgs/msg/JointState|nav_msgs/msg/Odometry|tf2_msgs/msg/TFMessage) TOPICS+=("$topic");;
    *) echo "Refusing non-sensor topic: $topic ($TYPE)" >&2; exit 2;;
  esac
done
(( ${#TOPICS[@]} > 0 )) || { echo 'No available topics' >&2; exit 2; }
FREE_KB="$(df -Pk "$(dirname "$OUT")" | awk 'NR==2 {print $4}')"
(( FREE_KB >= ${MIN_FREE_KB:-2097152} )) || { echo 'Insufficient free space (default reserve 2GiB)' >&2; exit 2; }
printf 'Duration: %ss, free: %s KiB, output: %s\n' "$DURATION" "$FREE_KB" "$OUT"
printf 'Selected: %s\n' "${TOPICS[@]}"
echo 'Review ros2 topic info --verbose for each sensor. Preview only unless --execute-reviewed is supplied.'
[[ "${1:-}" == --execute-reviewed ]] || exit 0
# /tf_static must retain transient-local durability. Other topics use discovered offered QoS.
QOS_FILE="$(mktemp)"
trap 'rm -f "$QOS_FILE"' EXIT
printf '/tf_static:\n  history: keep_last\n  depth: 100\n  reliability: reliable\n  durability: transient_local\n' > "$QOS_FILE"
# SIGINT lets rosbag2 flush metadata. Monitor free space each second and stop at reserve.
BAG_PID=""
RECORDER_RC=0
FORCED_STOP=0
stop_recorder() {
  [[ -n "$BAG_PID" ]] || return 0
  if kill -0 "$BAG_PID" 2>/dev/null; then
    kill -INT "$BAG_PID" 2>/dev/null || :
    for ((flush=0; flush<100; flush++)); do
      kill -0 "$BAG_PID" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$BAG_PID" 2>/dev/null; then
      FORCED_STOP=1
      echo 'Recorder did not flush within 10s; terminating this recorder only.' >&2
      kill -TERM "$BAG_PID" 2>/dev/null || :
      for ((flush=0; flush<20; flush++)); do
        kill -0 "$BAG_PID" 2>/dev/null || break
        sleep 0.1
      done
      kill -0 "$BAG_PID" 2>/dev/null && kill -KILL "$BAG_PID" 2>/dev/null || :
    fi
  fi
  wait "$BAG_PID" || RECORDER_RC=$?
  BAG_PID=""
}
cleanup() {
  stop_recorder
  rm -f "$QOS_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ros2 bag record --qos-profile-overrides-path "$QOS_FILE" -o "$OUT" "${TOPICS[@]}" &
BAG_PID=$!
for ((i=0; i<DURATION; i++)); do
  kill -0 "$BAG_PID" 2>/dev/null || break
  sleep 1
  FREE_KB="$(df -Pk "$(dirname "$OUT")" | awk 'NR==2 {print $4}')"
  (( FREE_KB >= ${MIN_FREE_KB:-2097152} )) || { echo 'Disk reserve reached'; break; }
done
stop_recorder
RC=$RECORDER_RC
(( FORCED_STOP == 0 )) || { echo 'Recording interrupted without graceful flush' >&2; exit 1; }
[[ -s "$OUT/metadata.yaml" ]] || { echo "Recording failed: exit=$RC, metadata missing" >&2; exit 1; }
if (( RC != 0 && RC != 130 )); then echo "Recorder failed: exit=$RC" >&2; exit 1; fi
ros2 bag info "$OUT"
echo "Recorded bag: $OUT; retain metadata.yaml (timestamps, types, offered QoS)."
