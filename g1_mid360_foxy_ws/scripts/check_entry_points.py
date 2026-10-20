"""Validate installed executables/import targets without creating nodes or SDK clients."""
import json
from importlib.metadata import distribution
import os
from pathlib import Path
import sys
from ament_index_python.packages import get_package_prefix

rows=[]
for package in ('g1_nav_bringup','g1_nav_perception','g1_nav_tf','g1_nav_bridge','g1_nav_config','g1_ros2_bridge'):
    for entry in distribution(package).entry_points:
        if entry.group!='console_scripts':continue
        executable=Path(get_package_prefix(package))/'lib'/package/entry.name
        if not executable.is_file() or not os.access(str(executable),os.X_OK):
            raise RuntimeError('ENTRY_POINT_NOT_EXECUTABLE: '+str(executable))
        if not callable(entry.load()):raise RuntimeError('ENTRY_POINT_NOT_CALLABLE: '+entry.value)
        rows.append({'package':package,'entry':entry.name,'target':entry.value,'path':str(executable)})
if any(name.startswith('unitree_sdk2py') for name in sys.modules):
    raise RuntimeError('SDK imported during metadata validation')
print(json.dumps({'entries':rows,'count':len(rows),'sdk_imported':False,'nodes_created':0},indent=2))
