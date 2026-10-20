"""Explicit legacy navigation cleanup; never match raw Unitree DDS/factory drivers."""
import argparse
import json
import os
from pathlib import Path
import signal
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from tf2_msgs.msg import TFMessage

EXECUTABLES = {'async_slam_toolbox_node','sync_slam_toolbox_node','pointcloud_to_laserscan_node',
    'planner_server','controller_server','bt_navigator','waypoint_follower','recoveries_server',
    'behavior_server','map_server','amcl','lifecycle_manager','costmap_2d_node',
    'pipeline','tf_adapter','tf_authority','dry_bridge','live_bridge','runtime_preflight',
    'velocity_smoother','goal_adapter','waypoint_client','resource_watchdog','timestamp_fixer'}


def ancestors(pid):
    found=set()
    while pid>1 and pid not in found:
        found.add(pid)
        try:pid=int(Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):break
    return found


def legacy_command(argv):
    tokens=[Path(a).name for a in argv[:3]]
    if any(t in EXECUTABLES for t in tokens):return True
    # Old Python scripts run directly rather than through installed entry points.
    if any(t in ('fix_stamp.py','fix_stamp_final.py') for t in tokens):return True
    if 'ros2' in tokens and 'launch' in argv and any(
            a in ('g1_nav_bringup','nav2_bringup','slam_toolbox','gdps_g1_navigation','pointcloud_to_laserscan') for a in argv):return True
    return False


def candidates():
    excluded=ancestors(os.getpid());found=[]
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            pid=int(entry.name)
            if pid in excluded or entry.stat().st_uid!=os.getuid():continue
            argv=[a.decode(errors='replace') for a in (entry/'cmdline').read_bytes().split(b'\0') if a]
            if legacy_command(argv):found.append({'pid':pid,'argv':argv})
        except (OSError,ValueError):continue
    return found


def main(args=None):
    parser=argparse.ArgumentParser();parser.add_argument('--keep-legacy',action='store_true')
    parser.add_argument('--check-only',action='store_true',help='this executable always checks/cleans only')
    from rclpy.utilities import remove_ros_args
    options=parser.parse_args(remove_ros_args(args=args)[1:])
    old=candidates()
    print('LEGACY_PREFLIGHT '+json.dumps(old),flush=True)
    if old:print('WARN legacy navigation detected; '+('retaining by request' if options.keep_legacy else 'terminating only listed navigation processes'),flush=True)
    if not options.keep_legacy:
        # Stop ROS launch supervisors first to prevent respawning their children.
        for item in sorted(old,key=lambda x:0 if 'launch' in x['argv'] else 1):
            try:os.kill(item['pid'],signal.SIGINT)
            except ProcessLookupError:pass
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and candidates():time.sleep(.2)
        for item in candidates():
            try:os.kill(item['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
        time.sleep(.5)
    rclpy.init(args=[]);node=Node('g1_nav_legacy_preflight')
    edges={};errors=[]
    def tf(msg):
        for t in msg.transforms:
            child=t.child_frame_id
            # No new broadcaster may start over an existing odometry/base alias edge.
            if child in ('robot_center','base_link','base_footprint','livox_frame'):
                errors.append('EXISTING_TF_OWNER:'+t.header.frame_id+'->'+child)
            edges[child]=t.header.frame_id
    node.create_subscription(TFMessage,'/tf',tf,100)
    node.create_subscription(TFMessage,'/tf_static',tf,QoSProfile(depth=100,durability=DurabilityPolicy.TRANSIENT_LOCAL))
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
    scan=node.count_publishers('/scan')
    remaining=candidates()
    if scan:errors.append('EXISTING_SCAN_PUBLISHERS:'+str(scan))
    if remaining and not options.keep_legacy:errors.append('LEGACY_RESPAWN_OR_STOP_FAILED')
    report={'remaining':remaining,'scan_publishers':scan,'tf_edges':edges,'errors':sorted(set(errors))}
    print('PREFLIGHT_RESULT '+json.dumps(report),flush=True)
    node.destroy_node();rclpy.shutdown()
    raise SystemExit(2 if errors else 0)
