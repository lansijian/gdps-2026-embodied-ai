"""Facade for the existing controller using official Foxy tf2 at sensor time."""
from __future__ import annotations
from gdps_qi.math_se3 import transform_from_pose
from gdps_qi.transforms.transform_manager import TransformError


class RosTfProvider:
    """No custom live cache; Buffer/TransformListener own subscriptions and history."""
    def __init__(self, node):
        from tf2_ros import Buffer, TransformListener
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, node)

    def can_transform(self, parent, child):
        from rclpy.time import Time
        return self.buffer.can_transform(parent, child, Time())

    def lookup(self, parent, child, stamp=None):
        from rclpy.time import Time
        try:
            tr = self.buffer.lookup_transform(parent, child, Time() if stamp is None else Time(seconds=stamp))
            t,q = tr.transform.translation,tr.transform.rotation
            return transform_from_pose((t.x,t.y,t.z),(q.x,q.y,q.z,q.w))
        except Exception as exc:
            raise TransformError(str(exc)) from exc
