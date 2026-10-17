"""Read-only ROS adapters and bounded evidence extraction; not a bag format.

rosbag2 owns raw messages/QoS. JSON/NPY are derived analysis artifacts only.
No motion SDK, publisher, service call, or navigation runtime is imported.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np


def stamp(msg):
    return float(msg.header.stamp.sec) + msg.header.stamp.nanosec * 1e-9


def sectors(ranges, angles, minimum=0.05, maximum=30.0):
    r, a = np.asarray(ranges), np.asarray(angles)
    valid = np.isfinite(r) & np.isfinite(a) & (r > minimum) & (r < maximum)
    result = {"valid_points": int(valid.sum())}
    for name, center in (("front", 0), ("left", math.pi / 2), ("back", math.pi), ("right", -math.pi / 2)):
        delta = np.arctan2(np.sin(a - center), np.cos(a - center))
        values = r[valid & (np.abs(delta) <= math.pi / 4)]
        result[name + "_m"] = float(values.min()) if values.size else None
        result[name + "_points"] = int(values.size)
    return result


def series_stats(items):
    ts = [x["stamp"] for x in items]
    diffs = np.diff(ts)
    return {"count": len(items), "first_stamp": ts[0] if ts else None,
            "last_stamp": ts[-1] if ts else None,
            "hz": (len(ts)-1)/(ts[-1]-ts[0]) if len(ts)>1 and ts[-1]>ts[0] else None,
            "non_monotonic": int((diffs <= 0).sum()),
            "max_gap_s": float(diffs.max()) if diffs.size else None}


def odom_delta(a, b):
    dx,dy = b['x']-a['x'], b['y']-a['y']
    q=a.get('orientation_xyzw')
    result={'dx':dx,'dy':dy,'frame_id':a['frame_id']}
    if q is not None:
        x,y,z,w=q
        yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
        result.update(initial_yaw_rad=yaw, forward_m=math.cos(yaw)*dx+math.sin(yaw)*dy,
                      lateral_left_m=-math.sin(yaw)*dx+math.cos(yaw)*dy)
    return result


def target_pixel(rgb):
    # A unique Hough circle is a geometric candidate, not a recognized sample identity.
    # No synthetic image, slot hint, OCR stub, or NumPy brightness centroid fallback.
    import cv2
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cs = cv2.HoughCircles(cv2.GaussianBlur(gray, (9,9), 2), cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=30, param1=80, param2=28, minRadius=8, maxRadius=80)
    if cs is None or len(cs[0]) != 1:
        return None
    return float(cs[0][0][0]), float(cs[0][0][1])


class EvidenceCollector:
    def __init__(self, args, source):
        self.args, self.source = args, source
        self.root = Path(args.out_dir)
        if self.root.exists() and any(self.root.iterdir()):
            raise FileExistsError("Evidence directory is not empty; choose a new out-dir")
        self.root.mkdir(parents=True, exist_ok=True)
        self.rows = {key: [] for key in ("pc", "scan", "odom", "frames", "tf_edges")}
        self.counts, self.errors, self.discovery, self.qos = {}, [], [], {}
        self.bridge = None
        self.filters = []
        self.buffer = None
        try:
            from tf2_ros import Buffer
            from rclpy.duration import Duration
            self.buffer = Buffer(cache_time=Duration(seconds=180.0))
        except ImportError as exc:
            self.errors.append({"topic": "/tf", "error": str(exc)})
        try:
            import message_filters
            self.filters = [message_filters.SimpleFilter() for _ in range(3)]
            self.sync = message_filters.ApproximateTimeSynchronizer(self.filters, 12, args.slop)
            self.sync.registerCallback(self.rgbd)
        except ImportError as exc:
            self.errors.append({"topic": "rgbd_sync", "error": str(exc)})
        self.pending = []
        self.static_edges = set()
        self.dynamic_edges = set()
        self.tf_failures = []
        self.last_saved_stamp = None
        self.message_bag_stamps = {}

    def ingest(self, topic, msg, bag_stamp=None):
        self.counts[topic] = self.counts.get(topic, 0) + 1
        try:
            if topic in ("/tf", "/tf_static"):
                for tr in msg.transforms:
                    edge = (tr.header.frame_id, tr.child_frame_id)
                    if topic == "/tf_static":
                        self.buffer.set_transform_static(tr, "rosbag2_or_sensor")
                        self.static_edges.add(edge)
                    else:
                        self.buffer.set_transform(tr, "rosbag2_or_sensor")
                        self.dynamic_edges.add(edge)
                    self.rows["tf_edges"].append({"parent": edge[0], "child": edge[1], "stamp": stamp(tr),
                                                  "static": topic == "/tf_static", "bag_stamp_ns": bag_stamp,
                                                  "recorded_receive_delay_s": bag_stamp * 1e-9-stamp(tr) if bag_stamp is not None and topic != "/tf_static" else None})
            elif topic in (self.args.rgb_topic, self.args.depth_topic, self.args.camera_info_topic):
                idx = (self.args.rgb_topic, self.args.depth_topic, self.args.camera_info_topic).index(topic)
                history = self.message_bag_stamps.setdefault(topic, {})
                history[stamp(msg)] = bag_stamp
                while len(history) > 24:
                    history.pop(next(iter(history)))
                if self.filters:
                    self.filters[idx].signalMessage(msg)
            elif topic == self.args.pc_topic:
                from sensor_msgs_py import point_cloud2
                # Foxy read_points supports field_names and skip_nans; preserves padded rows/endian.
                pts = np.asarray(list(point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)), dtype=float)
                if pts.size:
                    pts = pts.reshape(-1, 3)
                    finite = pts[np.isfinite(pts).all(axis=1)]
                    band = finite[(finite[:, 2] >= self.args.min_height) & (finite[:, 2] <= self.args.max_height)]
                    sec = sectors(np.hypot(band[:, 0], band[:, 1]), np.arctan2(band[:, 1], band[:, 0]))
                    sec["finite_xyz_points"] = len(finite)
                else:
                    sec = sectors([], [])
                self.rows["pc"].append({"stamp": stamp(msg), "bag_stamp_ns": bag_stamp,
                    "frame_id": msg.header.frame_id, "raw_points": msg.width * msg.height,
                    "height_band_m": [self.args.min_height, self.args.max_height], **sec})
            elif topic == self.args.scan_topic:
                angles = msg.angle_min + np.arange(len(msg.ranges)) * msg.angle_increment
                self.rows["scan"].append({"stamp": stamp(msg), "bag_stamp_ns": bag_stamp,
                    "frame_id": msg.header.frame_id, **sectors(msg.ranges, angles, msg.range_min, msg.range_max)})
            elif topic == self.args.odom_topic:
                p, q = msg.pose.pose.position, msg.pose.pose.orientation
                self.rows["odom"].append({"stamp": stamp(msg), "bag_stamp_ns": bag_stamp,
                    "frame_id": msg.header.frame_id, "child": msg.child_frame_id,
                    "x": p.x, "y": p.y, "z": p.z, "orientation_xyzw": [q.x, q.y, q.z, q.w]})
        except Exception as exc:
            if len(self.errors) < 100:
                self.errors.append({"topic": topic, "error": str(exc)})

    def rgbd(self, rgb, depth, info):
        # Foxy synchronizer holds its internal lock during callbacks; never raise here.
        try:
            self._rgbd(rgb, depth, info)
        except Exception as exc:
            if len(self.errors) < 100:
                self.errors.append({"topic": "rgbd_sync", "error": str(exc)})

    def _rgbd(self, rgb, depth, info):
        if len(self.rows["frames"]) >= self.args.max_frames:
            return
        if self.last_saved_stamp is not None and stamp(rgb) - self.last_saved_stamp < self.args.sample_period:
            return
        from cv_bridge import CvBridge
        if self.bridge is None:
            self.bridge = CvBridge()
        from image_geometry import PinholeCameraModel
        from gdps_qi.adapters.camera import CameraInfo
        # Raw -> rectified pixels and rays handled by the official Foxy camera model.
        model = PinholeCameraModel()
        model.fromCameraInfo(info)
        image = self.bridge.imgmsg_to_cv2(rgb, desired_encoding="rgb8")
        raw_depth = self.bridge.imgmsg_to_cv2(depth, desired_encoding="passthrough")
        scale = 1.0 if depth.encoding == "32FC1" else self.args.depth_scale
        if depth.encoding not in ("32FC1", "16UC1"):
            raise ValueError("unsupported_depth_encoding:" + depth.encoding)
        import cv2
        # Registered raw RGB/depth share K. For mono R=I, rectify both with the same map;
        # nearest-neighbour depth preserves measured Z without interpolating holes.
        rectified = False
        raw_image = image.copy()
        raw_depth_copy = raw_depth.copy()
        if np.allclose(np.asarray(info.r).reshape(3,3), np.eye(3)) and abs(model.Tx()) < 1e-12 and abs(model.Ty()) < 1e-12:
            image = np.empty_like(image)
            model.rectifyImage(raw_image, image)
            raw_depth = cv2.remap(raw_depth, model.mapx, model.mapy, cv2.INTER_NEAREST)
            rectified = True
        scaled = raw_depth.astype(np.float32) * scale if scale is not None else None
        camera = CameraInfo(info.width, info.height, float(model.fx()), float(model.fy()), float(model.cx()),
            float(model.cy()), info.header.frame_id, () if rectified else tuple(info.d), "ros_header_camera_info", False)
        principal_ray = model.projectPixelTo3dRay((camera.cx, camera.cy))
        if not np.isfinite(principal_ray).all():
            raise ValueError("invalid_camera_projection_matrix")
        idx = len(self.rows["frames"])
        rgb_file = "rgb_%03d.npy" % idx
        depth_file = "depth_%03d.npy" % idx
        np.save(self.root / rgb_file, image, allow_pickle=False)
        np.save(self.root / ("raw_rgb_%03d.npy" % idx), raw_image, allow_pickle=False)
        np.save(self.root / ("raw_depth_%03d.npy" % idx), raw_depth_copy, allow_pickle=False)
        if not cv2.imwrite(str(self.root / ("rgb_%03d.png" % idx)), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)):
            raise OSError("PNG sample export failed")
        if scaled is not None:
            np.save(self.root / depth_file, scaled, allow_pickle=False)
        # Matching resolution is not proof of registration: explicit provenance + frame identity required.
        aligned = (self.args.registered_depth and bool(self.args.registration_source)
                   and rgb.header.frame_id == depth.header.frame_id == info.header.frame_id
                   and image.shape[:2] == raw_depth.shape[:2] and rectified)
        row = {"bag_stamps_ns": {topic: self.message_bag_stamps.get(topic, {}).get(stamp(msg))
                for topic,msg in ((self.args.rgb_topic,rgb),(self.args.depth_topic,depth),(self.args.camera_info_topic,info))},
            "stamp": stamp(rgb), "rgb_stamp_sec": stamp(rgb), "depth_stamp_sec": stamp(depth),
            "camera_info_stamp_sec": stamp(info), "rgb_frame_id": rgb.header.frame_id,
            "depth_frame_id": depth.header.frame_id, "rectified": rectified,
            "raw_camera_info": {"k": list(info.k), "d": list(info.d), "r": list(info.r), "p": list(info.p)}, "info": asdict(camera), "rgb_file": rgb_file,
            "depth_file": depth_file if scaled is not None else None, "depth_scale_confirmed": scale is not None,
            "depth_aligned_to_rgb": bool(aligned), "registration_source": self.args.registration_source,
            "intrinsics_trusted": bool(camera.fx > 0 and camera.fy > 0),
            "principal_ray": list(principal_ray), "camera_model_backend": "image_geometry.PinholeCameraModel", "tf": None}
        uv = target_pixel(image)
        if uv is not None:
            row["target_candidate"] = {"uv": list(uv), "ray_camera": list(model.projectPixelTo3dRay(uv)),
                                       "identity": "UNVERIFIED_circle_candidate", "backend": "image_geometry.PinholeCameraModel"}
        # Non-mono/non-identity rectification requires official depth_image_proc upstream; fail closed.
        self.rows["frames"].append(row)
        self.pending.append(row)
        self.last_saved_stamp = stamp(rgb)

    def finish(self):
        from rclpy.time import Time
        from gdps_qi.math_se3 import transform_from_pose
        lookups = []
        for row in self.pending:
            try:
                tr = self.buffer.lookup_transform(self.args.base_frame, row["rgb_frame_id"],
                                                 Time(seconds=row["stamp"]))
                t, q = tr.transform.translation, tr.transform.rotation
                row["tf"] = transform_from_pose([t.x, t.y, t.z], [q.x, q.y, q.z, q.w]).tolist()
                row["tf_stamp"] = stamp(tr)
            except Exception as exc:
                row["tf_error"] = str(exc)
        # Per-edge latest query plus age. Static zero stamps are timeless, dynamic zero stamps are invalid.
        latest_sensor = max((v[-1]["stamp"] for k,v in self.rows.items() if k != "tf_edges" and v), default=None)
        reference = latest_sensor if self.source == "RECORDED_REPLAY" else self.args.ros_now
        pairs = set(self.static_edges | self.dynamic_edges)
        pairs.update([(self.args.base_frame, self.args.camera_frame), (self.args.base_frame, self.args.lidar_frame),
                      ("odom", self.args.base_frame)])
        for parent, child in sorted(pairs):
            item = {"parent": parent, "child": child, "ok": False}
            try:
                tr = self.buffer.lookup_transform(parent, child, Time())
                ts = stamp(tr)
                # A zero latest stamp is static only if every edge on the path is static.
                static_only = self._static_path(parent, child)
                age = None if static_only or reference is None else reference - ts
                item.update(stamp=ts, static=static_only, age_s=age,
                            stale=not static_only and (age is None or age < -self.args.slop or age > self.args.tf_max_age),
                            ok=True)
            except Exception as exc:
                item["error"] = str(exc)
            lookups.append(item)
        report = {"schema": "gdps-derived-evidence-v1", "data_source": self.source,
            "field_verified": False, "live_motion": False, "counts": self.counts,
            "discovery": self.discovery, "qos": self.qos, "errors": self.errors,
            "rows": self.rows, "tf_lookups": lookups, "time_reference": reference,
            "settings": {"slop": self.args.slop, "tf_max_age": self.args.tf_max_age},
            "limits": {"max_frames": self.args.max_frames, "sample_period": self.args.sample_period}}
        (self.root / "evidence.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        return report

    def _static_path(self, start, goal):
        todo, seen = [start], set()
        while todo:
            node = todo.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            for a,b in self.static_edges - self.dynamic_edges:
                if a == node: todo.append(b)
                if b == node: todo.append(a)
        return False


def add_capture_arguments(p):
    p.add_argument("--rgb-topic", default="")
    p.add_argument("--depth-topic", default="")
    p.add_argument("--camera-info-topic", default="")
    p.add_argument("--pc-topic", default="/utlidar/cloud_livox_mid360")
    p.add_argument("--scan-topic", default="/scan")
    p.add_argument("--odom-topic", default="/dog_odom")
    p.add_argument("--base-frame", default="robot_center")
    p.add_argument("--camera-frame", default="camera_color_optical_frame")
    p.add_argument("--lidar-frame", default="livox_frame")
    p.add_argument("--slop", type=float, default=0.05)
    p.add_argument("--tf-max-age", type=float, default=0.25)
    p.add_argument("--depth-scale", type=float, default=None, help="verified metres/unit for 16UC1")
    p.add_argument("--registered-depth", action="store_true")
    p.add_argument("--registration-source", default="", help="driver/calibration evidence reference")
    p.add_argument("--min-height", type=float, default=0.05)
    p.add_argument("--max-height", type=float, default=1.0)
    p.add_argument("--max-frames", type=int, default=20)
    p.add_argument("--sample-period", type=float, default=0.5)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--out-dir", default="field_evidence")


def capture_live(args, source="REAL_SENSOR"):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from sensor_msgs.msg import Image, CameraInfo, PointCloud2, LaserScan
    from nav_msgs.msg import Odometry
    from tf2_msgs.msg import TFMessage
    rclpy.init()
    node = rclpy.create_node("gdps_readonly_field_evidence")
    collector = EvidenceCollector(args, source)
    listener = None
    if collector.buffer is not None:
        from tf2_ros import TransformListener
        listener = TransformListener(collector.buffer, node)
    collector.discovery = [{"topic": t, "types": ty} for t,ty in node.get_topic_names_and_types()]
    # Auto-discover only an unambiguous camera family; ambiguous graphs need reviewed CLI topics.
    if not args.rgb_topic:
        options = [t for t,ty in node.get_topic_names_and_types() if "sensor_msgs/msg/Image" in ty
                   and ("color" in t or "rgb" in t) and "depth" not in t]
        if len(options) == 1: args.rgb_topic = options[0]
    if not args.depth_topic:
        options = [t for t,ty in node.get_topic_names_and_types() if "sensor_msgs/msg/Image" in ty and "depth" in t]
        if len(options) == 1: args.depth_topic = options[0]
    if not args.camera_info_topic:
        options = [t for t,ty in node.get_topic_names_and_types() if "sensor_msgs/msg/CameraInfo" in ty]
        if len(options) == 1: args.camera_info_topic = options[0]
    static_qos = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
    subs = []
    for topic, typ in ((args.rgb_topic, Image), (args.depth_topic, Image), (args.camera_info_topic, CameraInfo),
                       (args.pc_topic, PointCloud2), (args.scan_topic, LaserScan), (args.odom_topic, Odometry),
                       ("/tf", TFMessage), ("/tf_static", TFMessage)):
        if topic:
            qos = static_qos if topic == "/tf_static" else qos_profile_sensor_data
            subs.append(node.create_subscription(typ, topic, lambda msg, t=topic: collector.ingest(t, msg), qos))
            collector.qos[topic] = str(qos)
    deadline = time.monotonic() + min(max(args.timeout, 0.1), 120)
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        args.ros_now = node.get_clock().now().nanoseconds * 1e-9
        return collector.finish()
    finally:
        node.destroy_node()
        rclpy.shutdown()
