"""Foxy /goal_pose adapter and a FollowWaypoints action client (no home-grown planner)."""
import json
import math
from pathlib import Path
import time
import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose, FollowWaypoints
from action_msgs.msg import GoalStatus


def read_waypoints(path):
    value=yaml.safe_load(Path(path).read_text())
    if not isinstance(value,dict) or value.get('frame_id')!='map':raise ValueError('waypoints frame_id must be map')
    points=value.get('waypoints')
    if not isinstance(points,list) or not 1<=len(points)<=1000:raise ValueError('waypoints must contain 1..1000 entries')
    for p in points:
        if set(p)!={'x','y','yaw'} or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p.values()):
            raise ValueError('waypoint requires finite x,y,yaw')
    return points


class Goals(Node):
    def __init__(self):
        super().__init__('g1_nav_goal_adapter')
        self.client=ActionClient(self,NavigateToPose,'/navigate_to_pose');self.handle=None;self.pending=None
        self.create_subscription(PoseStamped,'/goal_pose',self.goal,5)
    def goal(self,msg):
        if msg.header.frame_id!='map' or not self.client.server_is_ready():
            self.get_logger().warning('GOAL_REJECTED: map frame and active NavigateToPose server required');return
        if self.pending and not self.pending.done():
            self.get_logger().warning('GOAL_SEND_IN_PROGRESS');return
        if self.handle:self.handle.cancel_goal_async()
        request=NavigateToPose.Goal();request.pose=msg
        self.pending=self.client.send_goal_async(request)
        def accepted(future):
            self.handle=future.result();self.get_logger().info('GOAL_ACCEPTED='+str(self.handle.accepted))
        self.pending.add_done_callback(accepted)


class Waypoints(Node):
    def __init__(self):
        super().__init__('g1_nav_waypoint_follower')
        self.declare_parameter('waypoints_file','');self.declare_parameter('loop',False)
        self.declare_parameter('report_file',str(Path.home()/'.ros/g1_nav-waypoints.json'))
        self.points=read_waypoints(self.get_parameter('waypoints_file').value)
        self.client=ActionClient(self,FollowWaypoints,'/follow_waypoints')
        self.active=None;self.pending=False;self.rounds=[];self.done=False;self.started=time.monotonic()
        self.create_timer(1.,self.tick)
    def tick(self):
        if self.done or self.pending or self.active:return
        if not self.client.server_is_ready():
            if time.monotonic()-self.started>90:raise RuntimeError('FOLLOW_WAYPOINTS_SERVER_TIMEOUT')
            return
        request=FollowWaypoints.Goal()
        for p in self.points:
            pose=PoseStamped();pose.header.frame_id='map';pose.header.stamp=self.get_clock().now().to_msg()
            pose.pose.position.x=float(p['x']);pose.pose.position.y=float(p['y'])
            pose.pose.orientation.z=math.sin(p['yaw']/2);pose.pose.orientation.w=math.cos(p['yaw']/2)
            request.poses.append(pose)
        self.pending=True;future=self.client.send_goal_async(request)
        future.add_done_callback(self.accepted)
    def accepted(self,future):
        self.pending=False;self.active=future.result()
        if not self.active.accepted:self.finish({'accepted':False,'status':'REJECTED'});return
        self.active.get_result_async().add_done_callback(self.result)
    def result(self,future):
        result=future.result()
        self.finish({'accepted':True,'status':result.status,'missed_waypoints':list(result.result.missed_waypoints)})
    def finish(self,report):
        self.rounds.append(report);self.active=None
        self.done=(not self.get_parameter('loop').value or report.get('status')!=GoalStatus.STATUS_SUCCEEDED or bool(report.get('missed_waypoints')))
        path=Path(self.get_parameter('report_file').value);path.parent.mkdir(parents=True,exist_ok=True)
        payload={'frame_id':'map','rounds':self.rounds,'finished':self.done,'realtime':time.time()}
        path.write_text(json.dumps(payload,indent=2));self.get_logger().info('WAYPOINT_REPORT '+json.dumps(payload))
    def destroy_node(self):
        if self.active:self.active.cancel_goal_async()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args);node=Goals()
    from g1_nav_perception.runtime import spin
    spin(node)


def waypoint_main(args=None):
    rclpy.init(args=args);node=Waypoints()
    from g1_nav_perception.runtime import spin
    spin(node)
