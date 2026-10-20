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
timeout 8 python3 - "$SCAN_TOPIC" <<'PY' || echo "NOTE: front-wall sample skipped (no scan or rclpy unavailable)"
import math
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
deadline = time.monotonic() + 6.0
while not samples and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
if samples:
    msg = samples[0]

    def range_at(angle):
        index = int((angle - msg.angle_min) / msg.angle_increment)
        if 0 <= index < len(msg.ranges):
            return msg.ranges[index]
        return float('nan')

    print('angle 0  range: %.3f m (the front wall should appear here)' % range_at(0.0))
    print('angle pi range: %.3f m' % range_at(math.pi))
else:
    print('no scan sample within timeout')
node.destroy_node()
rclpy.shutdown()
PY

echo
if [[ $fail -ne 0 ]]; then
  echo "RESULT: FAIL (see MISSING lines above)"
  exit 1
fi
echo "RESULT: all topics/frames published"
