"""Offline numeric review of manually selected real floor/obstacle XYZ samples."""
import argparse
import csv
import json
from pathlib import Path
import sys
import yaml
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/g1_nav_perception'))
from g1_nav_perception.core import rotate, quaternion, finite

p=argparse.ArgumentParser()
p.add_argument('--site',required=True);p.add_argument('--floor-csv',required=True)
p.add_argument('--obstacle-csv',required=True);p.add_argument('--output',required=True)
a=p.parse_args();s=yaml.safe_load(Path(a.site).read_text());c=s['calibration'];f=s['filter']
quaternion(c['quaternion_xyzw'])
if not finite(c['translation_xyz']):raise SystemExit('UNKNOWN sensor translation')
def load(path):
    with open(path,newline='') as stream:
        points=[[float(row[k]) for k in ('x','y','z')] for row in csv.DictReader(stream)]
    if len(points)<3 or any(not finite(v) for v in points):raise SystemExit('At least 3 finite selected XYZ rows required')
    return np.asarray([np.asarray(rotate(c['quaternion_xyzw'],v))+np.asarray(c['translation_xyz']) for v in points])
floor,obstacles=load(a.floor_csv),load(a.obstacle_csv)
center=floor.mean(axis=0);_,singular,v=np.linalg.svd(floor-center,full_matrices=False)
if singular[1]<1e-6:raise SystemExit('Degenerate/collinear floor selection')
normal=v[-1];normal*=1 if normal[2]>=0 else -1
report={'status':'NUMERIC_REVIEW_ONLY_NOT_HARDWARE_CERTIFICATION','floor_count':len(floor),
    'obstacle_count':len(obstacles),'floor_mean_z_m':float(center[2]),
    'floor_z_p05_p95_m':np.percentile(floor[:,2],[5,95]).tolist(),
    'floor_normal_up_for_statistics':normal.tolist(),
    'tilt_deg':float(np.degrees(np.arccos(np.clip(normal[2],-1,1)))),
    'plane_rms_m':float(np.sqrt(np.mean(((floor-center)@normal)**2))),
    'floor_in_obstacle_window_ratio':float(np.mean((floor[:,2]>=f['min_height'])&(floor[:,2]<=f['max_height']))),
    'obstacle_retention_ratio':float(np.mean((obstacles[:,2]>=f['min_height'])&(obstacles[:,2]<=f['max_height'])))}
Path(a.output).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
