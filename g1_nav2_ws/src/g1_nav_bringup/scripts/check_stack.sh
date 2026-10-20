#!/usr/bin/env bash
# Reference: ros2cli topic hz / tf2_ros tf2_echo usage. Read-only field checks; this
# script only prints and inspects, it never modifies any data or configuration.
set -uo pipefail
BASE=${1:-base_link}
SCAN_TOPIC=${SCAN_TOPIC:-/scan}
fail=0

hz() {
  local topic=$1
  echo "== ros2 topic hz $topic (6s window)"
  local out
  out=$(timeout 6 ros2 topic hz "$topic" 2>&1 || true)
  if grep -q 'average rate' <<<"$out"; then
    grep -m1 'average rate' <<<"$out"
  else
    echo "MISSING: no messages on $topic within 6s"
    fail=1
  fi
}

tf() {
  local parent=$1 child=$2
  echo "== tf2_echo $parent $child (4s window)"
  local out
  out=$(timeout 4 ros2 run tf2_ros tf2_echo "$parent" "$child" 2>&1 || true)
  if grep -q 'Translation' <<<"$out"; then
    grep -m1 -A3 'Translation' <<<"$out"
  else
    echo "MISSING: no transform $parent -> $child within 4s"
    fail=1
  fi
}

hz /livox/lidar
hz "$SCAN_TOPIC"
hz /dog_odom
hz /odom
tf odom "$BASE"
tf "$BASE" livox_frame
tf map odom

echo
cat <<'TXT'
== 正墙测试 (front-wall check)
G1 正对约 1 m 的平墙站定，下方 angle 0 读数应约等于墙距 (≈1 m)。
如果 angle 0 很远而 angle pi 约 1 m，说明雷达前后反向：Ctrl+C 停止 launch，
把外参从绕 Y 180° (lidar_qx:=0 lidar_qy:=1 lidar_qz:=0 lidar_qw:=0)
切换为绕 X 180° (lidar_qx:=1 lidar_qy:=0 lidar_qz:=0 lidar_qw:=0) 后重测本脚本。
TXT
timeout 10 python3 - "$SCAN_TOPIC" <<'PY' || echo "NOTE: front-wall sample skipped (no scan or rclpy unavailable)"
import math
import statistics
import sys
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

topic = sys.argv[1]
rclpy.init()
node = rclpy.create_node('front_wall_check')
samples = []
node.create_subscription(LaserScan, topic, samples.append, qos_profile_sensor_data)
deadline = time.monotonic() + 8.0
while len(samples) < 10 and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
node.destroy_node()
rclpy.shutdown()


def window_values(msg, angle):
    center = int(round((angle - msg.angle_min) / msg.angle_increment))
    center = max(0, min(len(msg.ranges) - 1, center))
    lo = max(0, center - 2)
    hi = min(len(msg.ranges), center + 3)
    return [r for r in msg.ranges[lo:hi] if math.isfinite(r)]


if not samples:
    print('no scan sample within timeout')
for label, angle in (('angle 0 ', 0.0), ('angle pi', math.pi)):
    per_frame = []
    for msg in samples[:10]:
        values = window_values(msg, angle)
        if values:
            per_frame.append(statistics.median(values))
    if per_frame:
        print('%s: median %.3f m  min %.3f  max %.3f  (frames %d)' % (
            label, statistics.median(per_frame), min(per_frame), max(per_frame), len(per_frame)))
    elif samples:
        print('%s: no finite rays in the center window' % label)
PY

echo
if [[ $fail -ne 0 ]]; then
  echo "RESULT: FAIL (see MISSING lines above)"
  exit 1
fi
echo "RESULT: all topics/frames published"
