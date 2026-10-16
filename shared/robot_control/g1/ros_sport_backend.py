"""Optional ROS 2 unitree_api Request publisher (control path A).

Inspired by guruadp/unitree-g1-slam-nav cmdvel_to_sport.py (Apache-2.0,
commit b9a1fbd). Rewritten to sit behind G1MotionAdapter.

UNVERIFIED on this team's G1 EDU:
- topic `/api/sport/request`
- message `unitree_api/msg/Request`
Do not enable this backend until those names exist on the robot.
"""

from __future__ import annotations

import json
import time

from .command import VelocityCommand
from .loco_backend import G1_LOCO_SET_VELOCITY_API_ID


class RosSportRequestBackend:
    name = "ros_sport_request"

    def __init__(self, node, topic: str = "/api/sport/request") -> None:
        self._node = node
        self._topic = topic
        self._pub = None

    def connect(self) -> int:
        try:
            from unitree_api.msg import Request
        except ImportError:
            return -20
        try:
            self._pub = self._node.create_publisher(Request, self._topic, 10)
            return 0
        except Exception:
            return -21

    def set_velocity(self, command: VelocityCommand) -> int:
        if self._pub is None:
            return -2
        try:
            from unitree_api.msg import Request
        except ImportError:
            return -20
        req = Request()
        header = getattr(req, "header", None)
        if header is None:
            return -22
        identity = getattr(header, "identity", None)
        lease = getattr(header, "lease", None)
        policy = getattr(header, "policy", None)
        if identity is None or lease is None or policy is None:
            return -22
        identity.id = time.monotonic_ns()
        identity.api_id = G1_LOCO_SET_VELOCITY_API_ID
        lease.id = 0
        policy.priority = 0
        policy.noreply = False
        req.parameter = json.dumps(
            {
                "velocity": [command.vx, command.vy, command.wz],
                "duration": command.duration_s,
            }
        )
        if hasattr(req, "binary"):
            req.binary = []
        self._pub.publish(req)
        return 0

    def stop_move(self) -> int:
        return self.set_velocity(VelocityCommand(source="stop_move"))

    def close(self) -> None:
        self._pub = None
