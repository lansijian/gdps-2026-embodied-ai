"""Vectorized calibrated XYZ crop; preserves the iterator reference semantics."""
import numpy as np
from .core import Blocked, quaternion, finite


def crop(msg, translation, q, minimum, maximum):
    quaternion(q)
    if len(translation) != 3 or not finite(translation):
        raise Blocked('unknown translation')
    fields = {f.name: f for f in msg.fields}
    endian = '>' if msg.is_bigendian else '<'
    formats, offsets = [], []
    for name in ('x', 'y', 'z'):
        f = fields.get(name)
        if f is None or f.datatype not in (7, 8) or f.count != 1:
            raise Blocked('unsupported PointCloud2 XYZ fields')
        size = 4 if f.datatype == 7 else 8
        if f.offset < 0 or f.offset+size > msg.point_step:
            raise Blocked('invalid field offset')
        formats.append(endian+('f4' if size == 4 else 'f8'))
        offsets.append(f.offset)
    if msg.point_step <= 0 or msg.row_step < msg.width*msg.point_step or len(msg.data) < msg.row_step*msg.height:
        raise Blocked('truncated PointCloud2')
    dtype = np.dtype({'names': ['x', 'y', 'z'], 'formats': formats,
                      'offsets': offsets, 'itemsize': msg.point_step})
    view = np.ndarray((msg.height, msg.width), dtype=dtype, buffer=msg.data,
                      strides=(msg.row_step, msg.point_step))
    p = np.column_stack([view[name].reshape(-1) for name in ('x', 'y', 'z')]).astype(np.float64)
    p = p[np.isfinite(p).all(axis=1)]
    count = len(p)
    x, y, z, w = q
    px, py, pz = p[:, 0], p[:, 1], p[:, 2]
    tx, ty, tz = 2*(y*pz-z*py), 2*(z*px-x*pz), 2*(x*py-y*px)
    v = np.column_stack((px+w*tx+y*tz-z*ty+translation[0],
                         py+w*ty+z*tx-x*tz+translation[1],
                         pz+w*tz+x*ty-y*tx+translation[2]))
    below = int(np.count_nonzero(v[:, 2] < minimum))
    keep = v[(v[:, 2] >= minimum) & (v[:, 2] <= maximum) &
             np.isfinite(v).all(axis=1) & (np.abs(v) <= np.finfo(np.float32).max).all(axis=1)]
    stats = {'finite_points': count, 'retained': len(keep), 'below_height': below,
             'retention_ratio': len(keep)/max(1, count), 'ground_candidate_ratio': below/max(1, count)}
    return keep.astype('<f4').tobytes(), len(keep), stats
