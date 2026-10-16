#!/usr/bin/env bash
# Read-only G1 EDU sensor diagnostics on the robot (ROS 2 Foxy).
# Subscribes/echoes/info/hz ONLY. Never publishes, never changes config, never moves.
# Usage: bash scripts/g1/sensor_diag.sh
set -euo pipefail

echo "=== env ==="
echo "ROS_DISTRO=${ROS_DISTRO:-unset}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-unset}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}"

if ! command -v ros2 >/dev/null 2>&1; then
  if [[ -f /opt/ros/foxy/setup.bash ]]; then
    echo "sourcing /opt/ros/foxy/setup.bash"
    # shellcheck disable=SC1091
    source /opt/ros/foxy/setup.bash
  else
    echo "ERROR: ros2 not on PATH and /opt/ros/foxy missing"
    exit 1
  fi
fi

hz() {
  # $1 = topic, $2 = seconds
  local topic="$1" secs="${2:-8}"
  echo "--- hz $topic (${secs}s) ---"
  timeout "${secs}s" ros2 topic hz "$topic" 2>&1 || echo "(hz ended/empty for $topic)"
}

info() {
  echo "--- info -v $1 ---"
  ros2 topic info -v "$1" 2>&1 || echo "(info failed for $1)"
}

echo
echo "=== topic info (publishers/subscribers/QoS) ==="
info /utlidar/cloud_livox_mid360
info /dog_odom
info /state_estimator/fusion_odom
info /unitree_slam/high_rate_odometry
info /global_map
info /api/sport/request

echo
echo "=== topic hz (rate check) ==="
hz /utlidar/cloud_livox_mid360 8
hz /dog_odom 6
hz /state_estimator/fusion_odom 6
hz /unitree_slam/high_rate_odometry 6
hz /global_map 4

echo
echo "=== TF presence ==="
for t in /tf /tf_static; do
  echo "--- $t ---"
  ros2 topic info "$t" 2>&1 || echo "(no $t)"
done
echo "--- tf echo (3s) ---"
timeout 3s ros2 topic echo /tf --once 2>&1 || echo "(no /tf echo)"

echo
echo "=== PointCloud2 summary (subscribe one msg, read-only) ==="
python3 - <<'PY'
import sys
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                 history=HistoryPolicy.KEEP_LAST, depth=1)

class PC(Node):
    def __init__(self):
        super().__init__("gdps_pc_diag")
        self.got = False
        self.create_subscription(PointCloud2, "/utlidar/cloud_livox_mid360", self.cb, qos)
        self.timer = self.create_timer(6.0, self._timeout)
    def cb(self, m):
        if self.got:
            return
        self.got = True
        n = m.width * m.height
        stamp = m.header.stamp
        print(f"frame_id={m.header.frame_id!r}")
        print(f"stamp={stamp.sec}.{stamp.nanosec:09d}")
        print(f"width={m.width} height={m.height} points~={n}")
        print(f"point_step={m.point_step} row_step={m.row_step} is_dense={m.is_dense}")
        print(f"fields={[f.name for f in m.fields]}")
        self.destroy_node()
        rclpy.shutdown()
    def _timeout(self):
        if not self.got:
            print("TIMEOUT: no PointCloud2 received in 6s")
            self.destroy_node()
            rclpy.shutdown()

rclpy.init()
rclpy.spin(PC())
PY

echo
echo "=== Odometry summary (subscribe one msg each, read-only) ==="
python3 - <<'PY'
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry

TOPICS = ["/dog_odom", "/state_estimator/fusion_odom", "/unitree_slam/high_rate_odometry"]

class OdomDiag(Node):
    def __init__(self):
        super().__init__("gdps_odom_diag")
        self.received = set()
        for t in TOPICS:
            self.create_subscription(Odometry, t, self._make(t), 10)
        self.create_timer(8.0, self._timeout)
    def _make(self, topic):
        def cb(m):
            if topic in self.received:
                return
            self.received.add(topic)
            p = m.pose.pose.position
            o = m.pose.pose.orientation
            tw = m.twist.twist
            print(f"[{topic}]")
            print(f"  frame_id={m.header.frame_id!r} child_frame_id={m.child_frame_id!r}")
            s = m.header.stamp
            print(f"  stamp={s.sec}.{s.nanosec:09d}")
            print(f"  pos=({p.x:.4f},{p.y:.4f},{p.z:.4f}) ori=({o.x:.3f},{o.y:.3f},{o.z:.3f},{o.w:.3f})")
            print(f"  lin=({tw.linear.x:.4f},{tw.linear.y:.4f},{tw.linear.z:.4f}) ang=({tw.angular.x:.4f},{tw.angular.y:.4f},{tw.angular.z:.4f})")
            if len(self.received) == len(TOPICS):
                self.destroy_node(); rclpy.shutdown()
        return cb
    def _timeout(self):
        missing = [t for t in TOPICS if t not in self.received]
        if missing:
            print(f"TIMEOUT no odom from: {missing}")
        self.destroy_node(); rclpy.shutdown()

rclpy.init()
rclpy.spin(OdomDiag())
PY

echo
echo "=== unitree_sdk2py import check ==="
python3 - <<'PY'
try:
    import unitree_sdk2py
    print("unitree_sdk2py OK:", getattr(unitree_sdk2py, "__file__", "imported"))
    try:
        from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        print("LocoClient import OK")
    except Exception as e:
        print("LocoClient import FAIL:", type(e).__name__, e)
except Exception as e:
    print("unitree_sdk2py missing:", type(e).__name__, e)
PY

echo
echo "=== DONE (read-only; no motion sent) ==="
