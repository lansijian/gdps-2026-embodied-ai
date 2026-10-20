"""Foxy Twist -> bounded 20Hz TwistStamped adapter; Nav2 remains the avoidance core."""
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped
from g1_nav_perception.pipeline import load_site
from g1_nav_perception.core import DryGate


class Smoother(Node):
    def __init__(self):
        super().__init__('g1_nav_velocity_smoother')
        self.site=load_site(self);self.gate=DryGate(self.site['limits'])
        self.pub=self.create_publisher(TwistStamped,'/g1_nav/cmd_vel_stamped',5)
        self.create_subscription(Twist,'/g1_nav/cmd_vel_nav2',self.command,5)
        self.create_timer(.05,self.tick)

    def command(self,msg):
        # Only the sole controller_server writer may introduce an unstamped command.
        writers=self.get_publishers_info_by_topic('/g1_nav/cmd_vel_nav2')
        if len(writers)!=1 or writers[0].node_name!='controller_server':
            self.get_logger().warning('RAW_CMD_OWNER_INVALID');self.gate.last_cmd=None;return
        self.gate.command((msg.linear.x,msg.linear.y,msg.linear.z,msg.angular.x,msg.angular.y,msg.angular.z),time.monotonic())

    def tick(self):
        vx,vy,wz=self.gate.tick(time.monotonic(),True)
        out=TwistStamped();out.header.frame_id='robot_center';out.header.stamp=self.get_clock().now().to_msg()
        out.twist.linear.x,out.twist.linear.y,out.twist.angular.z=vx,vy,wz
        self.pub.publish(out)


def main(args=None):
    rclpy.init(args=args);node=Smoother()
    from g1_nav_perception.runtime import spin
    spin(node)
