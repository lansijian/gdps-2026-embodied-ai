"""ROS 2 Foxy adapters for the tourism guide node (lazy imports).

The module imports cleanly on macOS/Windows without ROS; rclpy is imported only
inside start().  Topics follow docs/interfaces/tourism-guide.md:
  /tourism/guide_event (std_msgs/String, JSON out)
  /tourism/start       (std_msgs/String, JSON in)
  /navigate_to_pose    (nav2_msgs/action/NavigateToPose client)
  /g1_nav/health       (std_msgs/String, JSON in, optional)
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class RosConfig:
    node_name: str = "tourism_guide"
    event_topic: str = "/tourism/guide_event"
    start_topic: str = "/tourism/start"
    health_topic: str = "/g1_nav/health"
    action_name: str = "/navigate_to_pose"
    action_wait_s: float = 20.0


class RosBridge:
    """Owns the rclpy node, spins it in a thread and bridges to asyncio."""

    def __init__(self, config: Optional[RosConfig] = None) -> None:
        self.config = config or RosConfig()
        self._node = None
        self._executor = None
        self._thread: Optional[threading.Thread] = None
        self._publisher = None
        self._action_client = None
        self._goal_handle = None
        self._lock = threading.Lock()
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.health: Dict[str, Any] = {}
        self.healthy = True
        self.started = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        import rclpy  # lazy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from std_msgs.msg import String

        rclpy.init(args=None)
        self._node = Node(self.config.node_name)
        self._publisher = self._node.create_publisher(String, self.config.event_topic, 10)
        self._node.create_subscription(String, self.config.start_topic, self._on_start, 10)
        self._node.create_subscription(String, self.config.health_topic, self._on_health, 10)
        self._executor = MultiThreadedExecutor(num_threads=2)
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()
        self.started = True
        self.publish_event({"type": "READY", "ts": time.time(), "source": "tourism_guide"})

    def stop(self) -> None:
        try:
            if self._executor is not None:
                self._executor.shutdown()
            if self._node is not None:
                self._node.destroy_node()
        finally:
            try:
                import rclpy

                rclpy.shutdown()
            except Exception:
                pass
            self.started = False

    # -- publisher ---------------------------------------------------------
    def publish_event(self, payload: Dict[str, Any]) -> None:
        if not self.started or self._publisher is None:
            return
        try:
            from std_msgs.msg import String

            message = String()
            message.data = json.dumps(payload, ensure_ascii=False)
            with self._lock:
                self._publisher.publish(message)
        except Exception:
            pass

    # -- subscribers -------------------------------------------------------
    def _on_start(self, message) -> None:
        try:
            payload = json.loads(message.data) if message.data else {}
        except ValueError:
            payload = {"mode": "tour"}
        self._events.put({"type": "start", "payload": payload})

    def _on_health(self, message) -> None:
        try:
            self.health = json.loads(message.data) if message.data else {}
        except ValueError:
            self.health = {"raw": message.data}
        self.healthy = bool(self.health.get("ok", True))
        self._events.put({"type": "health", "payload": self.health})

    def poll_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        try:
            while True:
                events.append(self._events.get_nowait())
        except queue.Empty:
            pass
        return events

    # -- navigation action -------------------------------------------------
    def _ensure_action_client(self):
        if self._action_client is not None:
            return self._action_client
        from nav2_msgs.action import NavigateToPose
        from rclpy.action import ActionClient

        self._action_client = ActionClient(self._node, NavigateToPose, self.config.action_name)
        return self._action_client

    def send_goal(self, payload: Dict[str, Any]) -> None:
        """Send one NavigateToPose goal; the result is queued as an event."""

        from geometry_msgs.msg import PoseStamped
        import math

        client = self._ensure_action_client()
        if not client.wait_for_server(timeout_sec=self.config.action_wait_s):
            self._events.put({"type": "nav_failed", "station_id": payload.get("station_id"), "reason": "action_server_unavailable"})
            return
        goal = NavigateToPose.Goal()
        pose = PoseStamped()
        pose.header.frame_id = str(payload.get("frame_id") or "map")
        self._node.get_clock().now()
        pose.header.stamp = self._node.get_clock().now().to_msg()
        pose.pose.position.x = float(payload.get("x", 0.0))
        pose.pose.position.y = float(payload.get("y", 0.0))
        yaw = float(payload.get("yaw", 0.0))
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        goal.pose = pose
        station_id = payload.get("station_id")
        future = client.send_goal_async(goal)
        future.add_done_callback(lambda done: self._on_goal_accepted(done, station_id))

    def _on_goal_accepted(self, future, station_id: Optional[str]) -> None:
        try:
            handle = future.result()
        except Exception as exc:
            self._events.put({"type": "nav_failed", "station_id": station_id, "reason": str(exc)})
            return
        if handle is None or not handle.accepted:
            self._events.put({"type": "nav_failed", "station_id": station_id, "reason": "goal_rejected"})
            return
        self._goal_handle = handle
        result_future = handle.get_result_async()
        result_future.add_done_callback(lambda done: self._on_goal_result(done, station_id))

    def _on_goal_result(self, future, station_id: Optional[str]) -> None:
        try:
            result = future.result()
            status = int(result.status)
        except Exception as exc:
            self._events.put({"type": "nav_failed", "station_id": station_id, "reason": str(exc)})
            return
        # action_msgs GoalStatus: 4 = STATUS_SUCCEEDED
        if status == 4:
            self._events.put({"type": "nav_arrived", "station_id": station_id})
        else:
            self._events.put({"type": "nav_failed", "station_id": station_id, "reason": "status_%d" % status})

    def cancel_goal(self) -> None:
        handle = self._goal_handle
        if handle is None:
            return
        try:
            handle.cancel_goal_async()
        except Exception:
            pass
        self._goal_handle = None


__all__ = ["RosConfig", "RosBridge"]
