#!/usr/bin/env bash
# G1 EDU Dry-run obstacle avoidance + vendor SLAM state probe.
# Read-only: does NOT publish to /api/sport/request, /api/slam_operate/request,
# or any motion topic. local_navigator runs in dry-run + mock mode.
set -u

WORKSPACE="${GDPS_WS:-/home/unitree/gdps-2026-embodied-ai/shared/navigation/ros2_ws}"

echo "===== ENV CHECK ====="
source /opt/ros/foxy/setup.bash 2>/dev/null || { echo "ERROR: cannot source foxy"; exit 1; }
if [ -f "$WORKSPACE/install/setup.bash" ]; then
  source "$WORKSPACE/install/setup.bash"
else
  echo "ERROR: workspace not built at $WORKSPACE"
  exit 1
fi
echo "ROS_DISTRO=$ROS_DISTRO"
echo "RMW=$RMW_IMPLEMENTATION"
echo ""

echo "===== NODE 1: odom_tf  (/dog_odom -> odom->robot_center TF) ====="
ros2 run gdps_g1_navigation odom_tf \
  --ros-args -p odom_topic:=/dog_odom &
PID_ODOM=$!
sleep 1

echo "===== NODE 2: pointcloud_to_laserscan  (permissive height for first run) ====="
# Height filter is in LIDAR frame (no TF to base). MID-360 on G1 head ~1m agl.
# Use -2.0..2.0 to capture all returns; refine after seeing data.
ros2 run gdps_g1_navigation pointcloud_to_laserscan \
  --ros-args -p input_topic:=/utlidar/cloud_livox_mid360 \
             -p output_topic:=/scan \
             -p min_height:=-2.0 \
             -p max_height:=2.0 \
             -p range_min:=0.10 \
             -p range_max:=10.0 \
             -p angle_increment:=0.0175 &
PID_PCL=$!
sleep 1

echo "===== NODE 3: local_navigator  (dry-run + mock, NO motion) ====="
ros2 run gdps_g1_navigation local_navigator &
PID_NAV=$!

echo "Waiting 8s for nodes to receive sensor data..."
sleep 8

echo ""
echo "############################################################"
echo "#  PART A: PointCloud2 -> LaserScan -> ObstacleMonitor      #"
echo "############################################################"

echo ""
echo "--- A1. /scan frame_id, ranges count, angle range ---"
timeout 5 ros2 topic echo /scan --once 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    r = d['ranges']
    valid = [x for x in r if x is not None and 0 < x < 1e6]
    print(f'frame_id     = {d[\"header\"][\"frame_id\"]}')
    print(f'stamp        = {d[\"header\"][\"stamp\"]}')
    print(f'angle_min    = {d[\"angle_min\"]:.4f}')
    print(f'angle_max    = {d[\"angle_max\"]:.4f}')
    print(f'angle_incr   = {d[\"angle_increment\"]:.6f}')
    print(f'range_min    = {d[\"range_min\"]:.3f}')
    print(f'range_max    = {d[\"range_max\"]:.3f}')
    print(f'ranges_count = {len(r)}')
    print(f'valid_count  = {len(valid)}')
    if valid:
        print(f'global_min   = {min(valid):.3f} m')
        print(f'global_max   = {max(valid):.3f} m')
        # front cone: middle 60 deg
        n = len(r); mid = n//2; half = n//6
        front = [x for x in r[mid-half:mid+half] if x is not None and 0 < x < 1e6]
        if front:
            print(f'front_min    = {min(front):.3f} m  (front 60 deg)')
        else:
            print('front_min    = N/A (no returns in front cone)')
except Exception as e:
    print(f'PARSE FAILED: {e}')
    print('raw head:')
" || echo "  (no /scan data received)"

echo ""
echo "--- A2. /scan frequency (5s window) ---"
timeout 6 ros2 topic hz /scan 2>/dev/null || echo "  (could not measure /scan hz)"

echo ""
echo "--- A3. TF: odom -> robot_center exists? ---"
TF_OK=0
timeout 4 ros2 topic echo /tf --once 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for t in d['transforms']:
        print(f\"  {t['header']['frame_id']} -> {t['child_frame_id']}\")
        print(f\"  translation = ({t['transform']['translation']['x']:.3f}, {t['transform']['translation']['y']:.3f}, {t['transform']['translation']['z']:.3f})\")
except Exception as e:
    print(f'  TF parse failed: {e}')
" || echo "  (no /tf received in 4s)"

echo ""
echo "--- A4. ObstacleMonitor decision (/gdps/nav_status) ---"
timeout 5 ros2 topic echo /gdps/nav_status --once 2>/dev/null || echo "  (no nav_status received)"

echo ""
echo "--- A5. Front obstacle distance trend (5 samples, 0.5s apart) ---"
for i in 1 2 3 4 5; do
  timeout 3 ros2 topic echo /scan --once 2>/dev/null | python3 -c "
import sys, json
try:
    d=json.load(sys.stdin); r=d['ranges']; n=len(r); mid=n//2; half=n//6
    f=[x for x in r[mid-half:mid+half] if x is not None and 0<x<1e6]
    print(f'  sample $i: front_min={min(f):.3f} m' if f else '  sample $i: front_min=N/A')
except: pass
" 2>/dev/null
  sleep 0.5
done

echo ""
echo "############################################################"
echo "#  PART B: Vendor SLAM state probe                         #"
echo "############################################################"

echo ""
echo "--- B1. /slam_info message type & first message ---"
timeout 4 ros2 topic info /slam_info 2>/dev/null
echo ""
echo "  First /slam_info content:"
timeout 4 ros2 topic echo /slam_info --once 2>/dev/null | head -40 || echo "  (no /slam_info data)"

echo ""
echo "--- B2. /unitree/slam_mapping/odom  (any data in 6s?) ---"
timeout 6 ros2 topic echo /unitree/slam_mapping/odom --once 2>/dev/null | head -15 || echo "  (NO data from slam_mapping/odom in 6s)"

echo ""
echo "--- B3. /unitree/slam_relocation/odom  (any data in 6s?) ---"
timeout 6 ros2 topic echo /unitree/slam_relocation/odom --once 2>/dev/null | head -15 || echo "  (NO data from slam_relocation/odom in 6s)"

echo ""
echo "--- B4. /global_map  (any data in 6s?) ---"
timeout 6 ros2 topic echo /global_map --once 2>/dev/null | python3 -c "
import sys, json
try:
    d=json.load(sys.stdin)
    info=d['info']
    print(f'  frame_id    = {d[\"header\"][\"frame_id\"]}')
    print(f'  resolution  = {info[\"resolution\"]}')
    print(f'  width       = {info[\"width\"]}')
    print(f'  height      = {info[\"height\"]}')
    print(f'  origin      = {info[\"origin\"]}')
    data=d['data']
    occ=sum(1 for x in data if x>0)
    free=sum(1 for x in data if x==0)
    unk=sum(1 for x in data if x<0)
    print(f'  cells       = total={len(data)} occupied={occ} free={free} unknown={unk}')
except Exception as e:
    print(f'  map parse failed: {e}')
" 2>/dev/null || echo "  (NO /global_map data in 6s)"

echo ""
echo "--- B5. /api/slam_operate/request  topic info (NO publish) ---"
ros2 topic info /api/slam_operate/request 2>/dev/null || echo "  (topic not found)"
ros2 topic info /api/slam_operate/response 2>/dev/null || echo "  (no response topic)"

echo ""
echo "############################################################"
echo "#  CLEANUP                                                  #"
echo "############################################################"
kill $PID_ODOM $PID_PCL $PID_NAV 2>/dev/null
wait 2>/dev/null
echo "All background nodes stopped."
echo ""
echo "=== DRY-RUN + SLAM PROBE COMPLETE ==="
