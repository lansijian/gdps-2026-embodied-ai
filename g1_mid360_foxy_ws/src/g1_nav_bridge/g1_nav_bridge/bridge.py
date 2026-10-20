"""Stamped command gate. LIVE is opt-in and never enabled by the default launch."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped
from std_msgs.msg import String
from g1_nav_perception.pipeline import load_site
from g1_nav_perception.core import DryGate, stamp_seconds
from .motion_lock import MotionLock


class Bridge(Node):
    def __init__(self):
        super().__init__('g1_nav_dry_bridge')
        site=load_site(self)
        for key,value in (('allow_live',False),('dry_run',True),('legacy',False),('sdk_interface',''),('sdk_domain',-1)):
            self.declare_parameter(key,value)
        self.live=self.get_parameter('allow_live').value and not self.get_parameter('dry_run').value
        if self.live and (not self.get_parameter('sdk_interface').value or self.get_parameter('sdk_domain').value<0):
            raise RuntimeError('LIVE_BLOCKED: explicit sdk_interface and sdk_domain required')
        self.gate=DryGate(site['limits']);self.lock=MotionLock.acquire('g1_nav_bridge')
        self.health=None;self.health_received=None;self.backend=None;self.future=None;self.rpc_started=0.
        self.sdk_error='';self.sdk_writes=0;self.executor=ThreadPoolExecutor(max_workers=1) if self.live else None
        self.safe=self.create_publisher(TwistStamped,'/g1_nav/cmd_vel_safe',5)
        self.observer=self.create_publisher(String,'/g1_nav/command_observer',10)
        self.create_subscription(TwistStamped,'/g1_nav/cmd_vel_stamped',self.command,5)
        if self.get_parameter('legacy').value:
            self.get_logger().warning('LEGACY_TWIST_ENABLED: /g1_nav/cmd_vel_legacy has no frame validation')
            self.create_subscription(Twist,'/g1_nav/cmd_vel_legacy',self.legacy,5)
        self.create_subscription(String,'/g1_nav/health',self.status,10)
        self.create_timer(.05,self.tick)

    def legacy(self,msg):
        self.gate.command((msg.linear.x,msg.linear.y,msg.linear.z,msg.angular.x,msg.angular.y,msg.angular.z),time.monotonic())

    def command(self,msg):
        if msg.header.frame_id!='robot_center' or not -.03<=time.time()-stamp_seconds(msg.header.stamp)<=.25:
            self.get_logger().warning('STAMPED_CMD_REJECTED: frame must be robot_center and stamp fresh')
            self.gate.last_cmd=None;return
        self.legacy(msg.twist)

    def status(self,msg):
        try:
            data=json.loads(msg.data)
            if not isinstance(data,dict) or data.get('schema_version')!=1:raise ValueError('health schema')
            self.health=data;self.health_received=time.monotonic()
        except (ValueError,TypeError):self.health=None

    def rpc(self,velocity):
        if self.backend is None:
            from .live_backend import LocoBackend
            self.backend=LocoBackend(self.get_parameter('sdk_interface').value,self.get_parameter('sdk_domain').value)
        self.backend.send(velocity)
        return True

    def tick(self):
        now=time.monotonic();h=self.health or {}
        fresh=self.health_received is not None and now-self.health_received<=.3
        unique=self.count_publishers('/g1_nav/health')==1 and self.count_publishers('/g1_nav/cmd_vel_stamped')==1
        ready=fresh and unique and h.get('healthy') is True and h.get('obstacle_stop') is False and h.get('map_ready') is True
        if self.future is not None:
            if self.future.done():
                try:self.future.result();self.sdk_writes+=1
                except Exception as exc:self.sdk_error='SDK_ERROR:'+str(exc)
                self.future=None
            elif now-self.rpc_started>.25:self.sdk_error='SDK_RPC_TIMEOUT_LATCHED'
        reason='OBSTACLE_STOP' if h.get('obstacle_stop') else 'HEALTH_TIMEOUT_OR_INHIBIT'
        velocity=self.gate.tick(now,ready and not self.sdk_error,self.sdk_error or reason)
        out=TwistStamped();out.header.frame_id='robot_center';out.header.stamp=self.get_clock().now().to_msg()
        out.twist.linear.x,out.twist.linear.y,out.twist.angular.z=velocity
        self.safe.publish(out)
        # Do not initialize SDK merely to send a zero while startup health is inhibited.
        if self.live and not self.sdk_error and self.future is None and (ready or self.backend is not None):
            self.rpc_started=now;self.future=self.executor.submit(self.rpc,velocity)
        msg=String();msg.data=json.dumps({'live':'ENABLED' if self.live else 'DISABLED','sdk_write_calls':self.sdk_writes,
            'reason':self.gate.reason,'health_age_s':now-self.health_received if self.health_received else None,
            'safe_preview':list(velocity),'health_reasons':h.get('reasons',[])})
        self.observer.publish(msg)

    def destroy_node(self):
        # Every SDK command has a short finite lease. No action/FSM API is called on exit.
        if self.executor:self.executor.shutdown(wait=False)
        self.lock.release();super().destroy_node()


def main(args=None):
    rclpy.init(args=args);node=Bridge()
    from g1_nav_perception.runtime import spin
    spin(node)
