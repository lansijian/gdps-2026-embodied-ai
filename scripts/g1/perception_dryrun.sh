#!/usr/bin/env bash
# G1 EDU pure-perception dry-run.
#
# Round 1: ONLY pointcloud_to_laserscan is started. No local_navigator,
# no cmdvel_bridge, no motion commands. Verifies MID-360 point cloud ->
# LaserScan conversion and reports front-sector obstacle distance.
#
# Safety:
#   - Does NOT publish to /api/sport/request or /api/slam_operate/request.
#   - Does NOT start any node that could command motion.
#   - All background processes tracked by PID and killed on exit/interrupt.
#   - Dependency check is read-only (ros2 pkg prefix), no apt install.

set -u

WORKSPACE="${GDPS_WS:-/home/unitree/gdps-2026-embodied-ai/shared/navigation/ros2_ws}"
PC_TOPIC="${PC_TOPIC:-/utlidar/cloud_livox_mid360}"
SCAN_TOPIC="${SCAN_TOPIC:-/scan}"
DURATION="${DURATION:-10}"

# Redirect ROS logs to a writable location (Foxy may not have /root/.ros writable).
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/gdps_ros_logs}"
mkdir -p "$ROS_LOG_DIR"

PCL_PID=""

cleanup() {
    echo
    echo "[$(date +%T)] cleanup: stopping background nodes..."
    if [ -n "$PCL_PID" ] && kill -0 "$PCL_PID" 2>/dev/null; then
        kill "$PCL_PID" 2>/dev/null
        wait "$PCL_PID" 2>/dev/null
        echo "  stopped pointcloud_to_laserscan (pid $PCL_PID)"
    fi
    echo "[$(date +%T)] cleanup done."
}
trap cleanup EXIT INT TERM

echo "============================================================"
echo " GDPS G1  PURE PERCEPTION DRY-RUN"
echo "============================================================"
echo "PC_TOPIC   = $PC_TOPIC"
echo "SCAN_TOPIC = $SCAN_TOPIC"
echo "DURATION   = ${DURATION}s"
echo "ROS_LOG_DIR= $ROS_LOG_DIR"
echo

source /opt/ros/foxy/setup.bash || { echo "ERROR: source foxy failed"; exit 1; }
if [ -f "$WORKSPACE/install/setup.bash" ]; then
    source "$WORKSPACE/install/setup.bash"
else
    echo "ERROR: workspace not built at $WORKSPACE"
    exit 1
fi
echo "ROS_DISTRO = $ROS_DISTRO"
echo "RMW        = ${RMW_IMPLEMENTATION:-<default>}"
echo

# ------------------------------------------------------------------
echo "===== [1/4] PointCloud2 input frame + fields (raw MID-360) ====="
python3 -c "
import rclpy, math
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import PointCloud2
qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=5)
class P(Node):
    def __init__(self):
        super().__init__('gdps_pc_probe')
        self.done=False
        self.create_subscription(PointCloud2, '$PC_TOPIC', self.cb, qos)
        self.t = self.create_timer(6.0, lambda: rclpy.shutdown())
    def cb(self, msg):
        if self.done: return
        self.done=True
        print('frame_id     =', msg.header.frame_id)
        print('height x w   =', msg.height, 'x', msg.width)
        print('point_step   =', msg.point_step, ' row_step =', msg.row_step)
        print('is_bigendian =', msg.is_bigendian)
        print('fields       =', [(f.name, f.offset, f.datatype) for f in msg.fields])
        try:
            from sensor_msgs_py import point_cloud2
            pts = list(point_cloud2.read_points(msg, field_names=('x','y','z'), skip_nans=True))
            n = min(len(pts), 3000)
            if n:
                xs=[p[0] for p in pts[:n]]; ys=[p[1] for p in pts[:n]]; zs=[p[2] for p in pts[:n]]
                print('x range      = [%.3f, %.3f]' % (min(xs), max(xs)))
                print('y range      = [%.3f, %.3f]' % (min(ys), max(ys)))
                print('z range      = [%.3f, %.3f]' % (min(zs), max(zs)))
                print('xy dist      = [%.3f, %.3f] m' % (min(math.hypot(p[0],p[1]) for p in pts[:n]), max(math.hypot(p[0],p[1]) for p in pts[:n])))
                print('sample pts   =', len(pts))
        except Exception as e:
            print('decode note  =', e)
rclpy.init(); n=P(); rclpy.spin(n); n.destroy_node(); rclpy.shutdown()
"
echo

# ------------------------------------------------------------------
echo "===== [2/4] Start pointcloud_to_laserscan (ONLY this node) ====="
ros2 run gdps_g1_navigation pointcloud_to_laserscan \
  --ros-args -p input_topic:="$PC_TOPIC" \
             -p output_topic:="$SCAN_TOPIC" \
             -p min_height:=-2.0 \
             -p max_height:=2.0 \
             -p range_min:=0.10 \
             -p range_max:=10.0 \
             -p angle_increment:=0.0175 &
PCL_PID=$!
echo "pointcloud_to_laserscan pid = $PCL_PID"
echo "waiting 4s for node init..."
sleep 4

if ! kill -0 "$PCL_PID" 2>/dev/null; then
    echo "ERROR: pointcloud_to_laserscan exited early (see stderr above)"
    exit 1
fi
echo "node running."
echo

# ------------------------------------------------------------------
echo "===== [3/4] LaserScan diagnostic probe (${DURATION}s) ====="
python3 -c "
import rclpy, math, time
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan
qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=5)
F = math.radians(30.0)
class P(Node):
    def __init__(self, dur):
        super().__init__('gdps_scan_probe')
        self.dur=dur; self.cnt=0; self.t0=time.time()
        self.tf=None; self.amin=None; self.amax=None; self.ainc=None
        self.rmin=None; self.rmax=None; self.nr=0; self.nv=0
        self.gmin=None; self.gmax=None; self.fmin=None; self.fv=0
        self.lmin=None; self.rmin2=None
        self.first=None; self.last=None
        self.create_subscription(LaserScan, '$SCAN_TOPIC', self.cb, qos)
        self.create_timer(1.0, self.tick)
    def cb(self, m):
        self.cnt+=1; now=time.time()
        if self.first is None: self.first=now
        self.last=now
        self.tf=m.header.frame_id
        self.amin=m.angle_min; self.amax=m.angle_max; self.ainc=m.angle_increment
        self.rmin=m.range_min; self.rmax=m.range_max; self.nr=len(m.ranges)
        v=[]; f=[]; l=[]; r=[]
        for i, raw in enumerate(m.ranges):
            if raw is None or math.isnan(raw) or math.isinf(raw): continue
            if raw<=m.range_min or raw>=m.range_max: continue
            a=math.atan2(math.sin(m.angle_min+i*m.angle_increment), math.cos(m.angle_min+i*m.angle_increment))
            v.append(raw)
            if abs(a)<=F: f.append(raw)
            elif 0.15<a<=1.2: l.append(raw)
            elif -1.2<=a<-0.15: r.append(raw)
        self.nv=len(v)
        if v: self.gmin=min(v); self.gmax=max(v)
        if f: self.fmin=min(f); self.fv=len(f)
        else: self.fv=0
        if l: self.lmin=min(l)
        if r: self.rmin2=min(r)
    def tick(self):
        if time.time()-self.t0>=self.dur:
            self.report(); rclpy.shutdown()
    def report(self):
        print('--- /scan report ---')
        print('frame_id        =', self.tf)
        print('messages        =', self.cnt)
        if self.cnt>1 and self.last and self.first and self.last>self.first:
            print('measured rate   = %.1f Hz' % ((self.cnt-1)/(self.last-self.first)))
        print('angle_min       =', self.amin)
        print('angle_max       =', self.amax)
        print('angle_increment =', self.ainc)
        print('range_min       =', self.rmin)
        print('range_max       =', self.rmax)
        print('ranges_count    =', self.nr)
        print('valid_count     =', self.nv)
        if self.gmin is not None:
            print('global_min      = %.3f m' % self.gmin)
            print('global_max      = %.3f m' % self.gmax)
        if self.amin is not None and self.ainc:
            fi=int(round((0.0-self.amin)/self.ainc))
            print('front(0rad) idx = %d / %d' % (fi, self.nr))
        print('front sector    = +/-30 deg, valid =', self.fv)
        if self.fmin is not None: print('FRONT_MIN       = %.3f m' % self.fmin)
        else: print('FRONT_MIN       = N/A')
        if self.lmin is not None: print('left_min        = %.3f m' % self.lmin)
        if self.rmin2 is not None: print('right_min       = %.3f m' % self.rmin2)
rclpy.init(); n=P($DURATION); rclpy.spin(n); n.destroy_node(); rclpy.shutdown()
"
echo

# ------------------------------------------------------------------
echo "===== [4/4] Read-only dependency check (NO apt install) ====="
for pkg in slam_toolbox nav2_bringup pointcloud_to_laserscan \
           nav2_map_server nav2_planner nav2_controller \
           nav2_bt_navigator nav2_waypoint_follower nav2_lifecycle_manager; do
    if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
        echo "  [INSTALLED] $pkg"
    else
        echo "  [MISSING]   $pkg"
    fi
done
echo

echo "============================================================"
echo " PURE PERCEPTION DRY-RUN COMPLETE"
echo "============================================================"
