"""Executable Foxy integration acceptance in isolated ROS_DOMAIN_ID.

Creates only explicitly labelled synthetic map and sensor fixtures. No robot claim.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from rclpy.action import ActionClient
from nav_msgs.msg import OccupancyGrid, Path as NavPath
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
from std_msgs.msg import String
from slam_toolbox.srv import SerializePoseGraph
from lifecycle_msgs.srv import GetState
from tf2_ros import StaticTransformBroadcaster
from geometry_msgs.msg import TransformStamped
from sensor_msgs.msg import PointCloud2

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'logs/ros-integration';OUT.mkdir(parents=True,exist_ok=True)
if os.environ.get('G1_NAV_TEST_ONLY')!='1' or os.environ.get('ROS_DOMAIN_ID')!='87':
    raise SystemExit('Requires isolated SYNTHETIC_TEST G1_NAV_TEST_ONLY=1 ROS_DOMAIN_ID=87')
site=yaml.safe_load((ROOT/'src/g1_nav_config/config/site.example.yaml').read_text())
site['data_source']='SYNTHETIC_TEST'
for key in ('calibration','timing','filter'):site[key].update(verified=True,evidence_id='SYNTHETIC_TEST_ONLY_NOT_HARDWARE')
site['calibration'].update(translation_xyz=[0.,0.,0.],quaternion_xyzw=[0.,0.,0.,1.])
site['filter'].update(ground_z=-.5,ground_margin=.05,min_height=.1,max_height=1.5,scan_time=.1)
site['robot'].update(footprint_verified=True,safe_environment_confirmed=True,blind_spots_reviewed=True,
    footprint=[[-.25,-.2],[.25,-.2],[.25,.2],[-.25,.2]])
site_path=OUT/'synthetic-site.yaml';site_path.write_text(yaml.safe_dump(site))
fault=OUT/'fault.txt';fault.write_text('')
processes=[]; files=[]
def start(label,cmd):
    f=open(OUT/(label+'.log'),'w');files.append(f)
    p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    processes.append(p);return p
def stop(p):
    if p.poll() is None:
        # Signal the launcher once; it forwards shutdown to its children.
        p.send_signal(signal.SIGINT)
        try:p.wait(15)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGTERM);p.wait(10)
def launch(mode,map_path=None):
    cmd=['ros2','launch','g1_nav_bringup',mode+'.launch.py','site:='+str(site_path)]
    if map_path:cmd+=['map:='+str(map_path)]
    return start(mode,cmd)
rclpy.init();node=Node('SYNTHETIC_TEST_acceptance')
latest={};counts={}
def receive(key):
    def callback(msg):latest[key]=msg;counts[key]=counts.get(key,0)+1
    return callback
node.create_subscription(String,'/g1_nav/health',receive('health'),10)
node.create_subscription(String,'/g1_nav/command_observer',receive('observer'),10)
node.create_subscription(Twist,'/g1_nav/cmd_vel_safe',receive('safe'),10)
node.create_subscription(Twist,'/cmd_vel',receive('cmd'),10)
node.create_subscription(NavPath,'/plan',receive('path'),10)
node.create_subscription(OccupancyGrid,'/local_costmap/costmap',receive('costmap'),10)
node.create_subscription(OccupancyGrid,'/map',receive('map'),QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
# Intentional mismatch probe: pipeline uses BEST_EFFORT and still receives data.
node.create_subscription(PointCloud2,'/utlidar/cloud_livox_mid360',receive('incompatible_qos'),QoSProfile(depth=1))
def wait(predicate,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        rclpy.spin_once(node,timeout_sec=.05)
        if predicate():return
    raise AssertionError('timeout; counts='+str(counts)+' health='+str(getattr(latest.get('health'),'data','MISSING')))
def health():return json.loads(latest['health'].data) if 'health' in latest else {}
results=[]
def passed(label):
    results.append({'test':label,'status':'PASS','data_source':'SYNTHETIC_TEST'});print('PASS',label,flush=True)
def child_pid(executable, group):
    matches=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            stat=(entry/'stat').read_text().rsplit(')',1)[1].split()
            argv=(entry/'cmdline').read_bytes().split(b'\0')
            if int(stat[2])==group and any(Path(arg.decode()).name==executable for arg in argv if arg):
                matches.append(int(entry.name))
        except (OSError,ValueError):pass
    assert len(matches)==1,(executable,matches)
    return matches[0]
try:
    fixture=start('fixture',[sys.executable,str(ROOT/'tests/ros_fixture.py'),str(fault)])
    mapping=launch('mapping')
    wait(lambda: health().get('healthy') is True,30);passed('source_scan_tf_health')
    assert counts.get('incompatible_qos',0)==0;passed('incompatible_qos_probe_no_messages_pipeline_receives')
    wait(lambda:'map' in latest and latest['map'].info.width>0 and any(x>=0 for x in latest['map'].data),100)
    passed('slam_toolbox_nonempty_map')
    subprocess.run(['ros2','run','nav2_map_server','map_saver_cli','-f',str(OUT/'synthetic-map'),
                    '--ros-args','-p','save_map_timeout:=10000','-p','map_subscribe_transient_local:=true'],check=True,timeout=25)
    assert (OUT/'synthetic-map.yaml').is_file();passed('occupancy_map_saved')
    client=node.create_client(SerializePoseGraph,'/slam_toolbox/serialize_map')
    assert client.wait_for_service(timeout_sec=10)
    req=SerializePoseGraph.Request();req.filename=str(OUT/'synthetic-posegraph')
    future=client.call_async(req);wait(lambda:future.done(),20)
    assert (OUT/'synthetic-posegraph.posegraph').is_file();passed('posegraph_saved')
    stop(mapping)
    latest.clear();counts.clear()
    nav=launch('navigation_dryrun',OUT/'synthetic-map.yaml')
    wait(lambda:health().get('healthy') is True,30)
    pose_pub=node.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
    # Wait for AMCL lifecycle, then send a single fixture-specific initial pose.
    state_client=node.create_client(GetState,'/amcl/get_state')
    assert state_client.wait_for_service(timeout_sec=50)
    until=time.monotonic()+30
    while time.monotonic()<until:
        state=state_client.call_async(GetState.Request());wait(lambda:state.done(),5)
        if state.result().current_state.id==3:break
    else:raise AssertionError('AMCL did not become active')
    wait(lambda:'map' in latest,10)
    p=PoseWithCovarianceStamped();p.header.frame_id='map';p.header.stamp=node.get_clock().now().to_msg()
    p.pose.pose.orientation.w=1.;p.pose.covariance[0]=.05;p.pose.covariance[7]=.05;p.pose.covariance[35]=.05
    pose_pub.publish(p)
    wait(lambda:health().get('map_ready') is True,25)
    wait(lambda:'costmap' in latest,45);passed('map_reloaded_amcl_and_costmap_active')
    planner=ActionClient(node,ComputePathToPose,'/compute_path_to_pose')
    assert planner.wait_for_server(timeout_sec=30)
    goal=ComputePathToPose.Goal();goal.pose.header.frame_id='map';goal.pose.header.stamp=node.get_clock().now().to_msg()
    goal.pose.pose.position.x=1.;goal.pose.pose.orientation.w=1.;goal.planner_id='GridBased'
    sent=planner.send_goal_async(goal);wait(lambda:sent.done(),15)
    assert sent.result().accepted
    result=sent.result().get_result_async();wait(lambda:result.done(),30)
    assert len(result.result().result.path.poses)>2;passed('navfn_real_action_nonempty_path')
    navigator=ActionClient(node,NavigateToPose,'/navigate_to_pose');assert navigator.wait_for_server(timeout_sec=10)
    ng=NavigateToPose.Goal();ng.pose=goal.pose
    nf=navigator.send_goal_async(ng);wait(lambda:nf.done(),10);assert nf.result().accepted
    wait(lambda:'cmd' in latest and abs(latest['cmd'].linear.x)>0,30);passed('dwb_generates_cmd_vel_without_sdk')
    wait(lambda:'safe' in latest and latest['safe'].linear.x>0,10);passed('healthy_safe_preview')
    for injected in ('dynamic_obstacle','cloud_loss','odom_loss','stale_time','future_time','wrong_frame'):
        fault.write_text(injected)
        wait(lambda:'safe' in latest and latest['safe'].linear.x==0. and
            ('OBSTACLE' in json.loads(latest['observer'].data)['reason'] or health().get('healthy') is False),10)
        assert json.loads(latest['observer'].data)['sdk_write_calls']==0
        passed('fault_stop_'+injected)
        if injected=='dynamic_obstacle':
            def obstacle_in_costmap():
                m=latest.get('costmap')
                if m is None:return False
                x=int((.45-m.info.origin.position.x)/m.info.resolution)
                y=int((0.-m.info.origin.position.y)/m.info.resolution)
                return 0<=x<m.info.width and 0<=y<m.info.height and m.data[y*m.info.width+x]>=90
            wait(obstacle_in_costmap,10);passed('dynamic_obstacle_marked_in_local_costmap')
        fault.write_text('');wait(lambda:health().get('healthy') is True,15)
    nf.result().cancel_goal_async()
    for executable,label in (('tf_adapter','tf_loss'),('pipeline','health_heartbeat_loss')):
        pid=child_pid(executable,nav.pid)
        os.kill(pid,signal.SIGSTOP)
        try:
            wait(lambda:'observer' in latest and json.loads(latest['observer'].data)['safe_preview']==[0.,0.,0.] and
                json.loads(latest['observer'].data)['reason']=='HEALTH_TIMEOUT_OR_INHIBIT',10)
            passed('independent_timer_stop_'+label)
        finally:os.kill(pid,signal.SIGCONT)
        wait(lambda:health().get('healthy') is True,15)
    duplicate=StaticTransformBroadcaster(node)
    t=TransformStamped();t.header.frame_id='robot_center';t.child_frame_id='livox_frame'
    t.header.stamp=node.get_clock().now().to_msg();t.transform.rotation.w=1.
    duplicate.sendTransform(t)
    wait(lambda:any('TF_DUPLICATE_OWNER' in reason for reason in health().get('reasons',[])),10)
    wait(lambda:json.loads(latest['observer'].data)['safe_preview']==[0.,0.,0.],5)
    passed('duplicate_tf_owner_latched_inhibit')
    passed('sdk_write_count_zero_all_ros_phases')
finally:
    (OUT/'results.json').write_text(json.dumps({'results':results,'live':'DISABLED','robot':'ROBOT_VERIFICATION_PENDING'},indent=2))
    (OUT/'last-health.json').write_text(json.dumps(health(),indent=2))
    for process in reversed(processes):stop(process)
    node.destroy_node();rclpy.shutdown()
    for f in files:f.close()
    if sys.exc_info()[0] is not None:
        for path in OUT.glob('*.log'):
            print('\nDIAGNOSTIC LOG', path.name)
            print('\n'.join(path.read_text(errors='replace').splitlines()[-60:]))
