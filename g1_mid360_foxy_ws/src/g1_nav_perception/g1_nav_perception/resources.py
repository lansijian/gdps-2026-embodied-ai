"""Bound allocations before Foxy C++ map/costmap nodes start. No image decode."""
import math
from pathlib import Path
import re
import struct
from .core import Blocked, finite

MAX_MAP_CELLS = 4_000_000
MAX_MAP_SIDE = 4096


def grid(width, height, resolution, limit, label):
    if not finite((width, height, resolution)) or not (.02 <= resolution <= .2 and 0 < width <= 200 and 0 < height <= 200):
        raise Blocked('RESOURCE_BOUND: '+label+' requires finite positive dimensions <=200m and resolution [0.02,0.2]m')
    cells = math.ceil(width/resolution)*math.ceil(height/resolution)
    if cells > limit:
        raise Blocked('RESOURCE_BOUND: '+label+' exceeds '+str(limit)+' cells')
    return cells


def image_shape(path):
    path = Path(path)
    if path.stat().st_size > 64*1024*1024:
        raise Blocked('RESOURCE_BOUND: map image file >64MiB')
    with path.open('rb') as stream:
        head = stream.read(4096)
    if head.startswith(b'\x89PNG\r\n\x1a\n') and head[12:16] == b'IHDR' and len(head) >= 33:
        width, height = struct.unpack('>II', head[16:24])
    elif head.startswith((b'P5', b'P2')):
        tokens = re.sub(br'#[^\r\n]*', b'', head).split()
        try:
            width, height, maximum = map(int, tokens[1:4])
            if not 0 < maximum <= 65535:
                raise ValueError()
        except (ValueError, IndexError):
            raise Blocked('MAP_INVALID: unsupported/truncated PGM header')
        if head.startswith(b'P5') and path.stat().st_size < width*height*(1 if maximum < 256 else 2):
            raise Blocked('MAP_INVALID: truncated PGM pixels')
    else:
        raise Blocked('MAP_INVALID: use saved PGM or PNG occupancy image')
    if not (0 < width <= MAX_MAP_SIDE and 0 < height <= MAX_MAP_SIDE and width*height <= MAX_MAP_CELLS):
        raise Blocked('RESOURCE_BOUND: map exceeds 4096 pixels/side or 4000000 cells')
    return width, height


def validate_map(mapping, image):
    width, height = image_shape(image)
    res = mapping.get('resolution')
    origin = mapping.get('origin')
    if not isinstance(origin, list) or len(origin) != 3 or not finite(origin):
        raise Blocked('MAP_INVALID: origin must be three finite numbers')
    if not finite((res,)) or not .02 <= res <= .2:
        raise Blocked('RESOURCE_BOUND: map resolution must be [0.02,0.2]m')
    grid(width*res, height*res, res, MAX_MAP_CELLS+MAX_MAP_SIDE*2+1, 'map')
    return {'width_pixels': width, 'height_pixels': height, 'cells': width*height,
            'resolution': res, 'note': 'cell limit is an allocation guard, not an RSS prediction'}


def validate_nav(nav):
    counts = {}
    for name in ('local_costmap', 'global_costmap'):
        params = nav[name][name]['ros__parameters']
        counts[name] = grid(params['width'], params['height'], params['resolution'],
                            250_000 if name == 'local_costmap' else MAX_MAP_CELLS, name)
        if params['robot_base_frame'] != 'robot_center':
            raise Blocked('FRAME_CONFIG: costmaps must use actual robot_center')
    return counts
