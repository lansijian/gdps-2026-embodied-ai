#!/usr/bin/env python3
"""Report installed dependencies without installation, upgrades, or service changes."""
import importlib
import inspect
import json
import os
import shutil
import sys


def main():
    checks = {}
    for name in ('numpy','cv2','yaml','rclpy','sensor_msgs.msg','nav_msgs.msg','tf2_msgs.msg',
                 'message_filters','cv_bridge','image_geometry','tf2_ros','sensor_msgs_py.point_cloud2','rosidl_runtime_py.utilities'):
        try:
            mod = importlib.import_module(name)
            checks[name] = {'ok': True, 'path': getattr(mod,'__file__',None), 'version': getattr(mod,'__version__',None)}
        except Exception as exc:
            checks[name] = {'ok': False, 'error': str(exc)}
    try:
        import message_filters
        checks['message_filters']['signature'] = str(inspect.signature(message_filters.ApproximateTimeSynchronizer))
    except Exception:
        pass
    out = {'python': sys.version, 'ros_distro': os.environ.get('ROS_DISTRO'), 'ros2_cli': shutil.which('ros2'),
           'dependencies': checks, 'live_motion': False}
    print(json.dumps(out, indent=2))
    return 0 if all(v['ok'] for v in checks.values()) and os.environ.get('ROS_DISTRO')=='foxy' else 1

if __name__ == '__main__':
    raise SystemExit(main())
