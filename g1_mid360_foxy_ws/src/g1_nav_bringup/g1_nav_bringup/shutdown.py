"""Orderly shutdown of this project's Nav2 managers; no robot/SLAM API calls."""
import argparse
import time
import rclpy
from rclpy.node import Node
from nav2_msgs.srv import ManageLifecycleNodes


def main(args=None):
    parser=argparse.ArgumentParser(description='Deactivate, clean up and shut down this workspace Nav2 nodes before Ctrl-C')
    parser.add_argument('--localization-only',action='store_true')
    options=parser.parse_args(args)
    rclpy.init(args=[]);node=Node('g1_nav_orderly_shutdown')
    managers=['lifecycle_manager_navigation']
    try:
        for name in managers:
            client=node.create_client(ManageLifecycleNodes,'/'+name+'/manage_nodes')
            if not client.wait_for_service(timeout_sec=5):
                raise RuntimeError('Project lifecycle manager unavailable: '+name)
            request=ManageLifecycleNodes.Request();request.command=ManageLifecycleNodes.Request.SHUTDOWN
            result=client.call_async(request);deadline=time.monotonic()+25
            while rclpy.ok() and not result.done() and time.monotonic()<deadline:
                rclpy.spin_once(node,timeout_sec=.1)
            if not result.done() or not result.result().success:
                raise RuntimeError('Project lifecycle shutdown failed: '+name)
            node.get_logger().info('SHUTDOWN_COMPLETE '+name+'; LIVE_DISABLED')
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
