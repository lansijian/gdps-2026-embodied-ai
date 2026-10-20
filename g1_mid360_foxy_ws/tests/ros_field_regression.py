"""Actual Foxy DDS regression; run ONLY in isolated test domain, not on robot.

Exercises BE/reliable input publishers -> integrated receipt relay -> official scan.
Not executed by portable pytest. Requires built/sourced ROS workspace.
"""
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time
import yaml


def main():
    if os.environ.get('G1_NAV_TEST_ONLY') != '1' or os.environ.get('ROS_DOMAIN_ID') != '87':
        raise SystemExit('SYNTHETIC_TEST requires G1_NAV_TEST_ONLY=1 ROS_DOMAIN_ID=87; NEVER use a robot domain')
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import PointCloud2, PointField, LaserScan
    from std_msgs.msg import String
    root=Path(__file__).resolve().parents[1]
    logs=root/'logs/field-regression';logs.mkdir(parents=True,exist_ok=True)
    site=logs/'synthetic-audit.yaml'
    site.write_text(yaml.safe_dump({'data_source':'SYNTHETIC_TEST',
                                  'timing':{'strategy':'offset'}}))
    rclpy.init(args=[])
    node=Node('g1_field_regression_fixture')
    scans=[];health=[]
    node.create_subscription(LaserScan,'/scan',lambda m:scans.append(m),QoSProfile(depth=5,reliability=ReliabilityPolicy.BEST_EFFORT))
    node.create_subscription(String,'/g1_nav/health',lambda m:health.append(json.loads(m.data)),10)
    result=[]
    try:
        for policy in (ReliabilityPolicy.BEST_EFFORT,ReliabilityPolicy.RELIABLE):
            scans.clear();health.clear()
            pub=node.create_publisher(PointCloud2,'/utlidar/cloud_livox_mid360',QoSProfile(depth=2,reliability=policy))
            with (logs/(str(policy)+'.log')).open('w') as output:
                process=subprocess.Popen(['ros2','launch','g1_nav_bringup','sensor_check.launch.py','site:='+str(site),'time_strategy:=offset'],
                                         stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    started=time.monotonic();next_send=0.
                    while time.monotonic()-started<20:
                        if time.monotonic()>next_send:
                            m=PointCloud2();m.header.frame_id='livox_frame'
                            now=time.time();m.header.stamp.sec=int(now)+4883
                            m.header.stamp.nanosec=int((now-int(now))*1e9)
                            m.height=1;m.width=1;m.point_step=12;m.row_step=12
                            m.fields=[PointField(name=n,offset=i*4,datatype=7,count=1) for i,n in enumerate(('x','y','z'))]
                            m.data=struct.pack('<fff',1.,0.,.5)
                            pub.publish(m);next_send=time.monotonic()+.1
                        rclpy.spin_once(node,timeout_sec=.02)
                        if len(scans)>5 and health and health[-1]['raw_streams']['cloud']['count']>5:
                            break
                    assert process.poll() is None,'integrated launch exited'
                    assert len(scans)>5,'no actual scan over DDS: '+str(policy)
                    scan=scans[-1]
                    assert scan.header.frame_id=='livox_frame'
                    stamp=scan.header.stamp.sec+scan.header.stamp.nanosec*1e-9
                    assert -.05<=time.time()-stamp<.5
                    assert health[-1]['raw_streams']['cloud']['reason']=='FUTURE_STAMP'
                    assert health[-1]['streams']['cloud']['reason']==''
                    assert health[-1]['offsets']['cloud']['offset_s'] is not None
                    assert abs(health[-1]['offsets']['cloud']['offset_s']+4883)<1.1
                    assert 'BLOCKED_NEEDS_CALIBRATION' in health[-1]['reasons']
                    result.append({'input_qos':str(policy),'scan_received':len(scans),'raw_stamp_future':True,'live':'DISABLED'})
                finally:
                    os.killpg(process.pid,signal.SIGINT)
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            node.destroy_publisher(pub)
    finally:
        node.destroy_node();rclpy.shutdown()
    (logs/'result.json').write_text(json.dumps({'data_source':'SYNTHETIC_TEST','checks':result},indent=2))
    print('PASS actual Foxy QoS matrix, receipt timestamps, raw preservation diagnostics and audit scan')


if __name__=='__main__':
    main()
