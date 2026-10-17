#!/usr/bin/env python3
"""Build an explicit whitelist ZIP, no recursive staging or motion entry points."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
QI = 'tracks/quality-inspection/gdps_qi/'
WHITELIST = [
    'scripts/g1/field_gates_centering.py', 'scripts/g1/field_evidence.py',
    'scripts/g1/replay_field_extract.py', 'scripts/g1/record_field_bag.sh',
    'scripts/g1/check_field_dependencies.py', 'scripts/g1/package_phase44.py',
    'scripts/g1/package_phase44.ps1', 'docs/deployment/phase44-field-replay.md',
    'docs/research/phase44-reuse.md', 'docs/research/phase44-source-refs.json',
    'docs/research/phase44-source-audit.json', 'THIRD_PARTY.md',
    'shared/__init__.py', 'shared/navigation/__init__.py',
    'shared/navigation/perception/__init__.py', 'shared/navigation/perception/obstacle_monitor.py',
    'shared/navigation/perception/pointcloud_to_laserscan.py',
] + [QI + p for p in (
    '__init__.py','types.py','math_se3.py','adapters/__init__.py','adapters/camera.py',
    'perception/__init__.py','perception/rgbd_target_geometry.py','perception/camera_geometry.py',
    'perception/message_sync.py','perception/detection_types.py',
    'centering/__init__.py','centering/target_centering_controller.py','centering/manipulation_ready.py',
    'transforms/__init__.py','transforms/transform_manager.py','transforms/frame_registry.py',
    'transforms/tf_chain_report.py','transforms/ros_tf.py')]


def build(output):
    commit = subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    files = {}
    for relative in WHITELIST:
        data = (ROOT / relative).read_bytes()
        if relative.endswith(('.py','.sh','.ps1','.md','.json')):
            data = data.decode('utf-8-sig').replace('\r\n','\n').encode('utf-8')
        files[relative] = data
    manifest = ''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n' for k,v in sorted(files.items()))
    files['MANIFEST.sha256'] = manifest.encode()
    files['BUNDLE.json'] = json.dumps({'source_commit':commit,'phase':'4.4','live_motion':False,
        'whitelist_count':len(WHITELIST),'field_verified':False},indent=2).encode()
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise FileExistsError('Refusing to overwrite existing bundle: '+str(output))
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for relative,data in sorted(files.items()):
            item=zipfile.ZipInfo(relative, (2026,10,17,0,0,0))
            item.compress_type=zipfile.ZIP_DEFLATED
            item.external_attr=(0o100644 << 16)
            z.writestr(item,data)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf-8')
    print(json.dumps({'zip':str(output.resolve()),'sha256':digest,'source_commit':commit,'files':len(files)},indent=2))
    return output

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',default='dist/gdps-s05-phase44-readonly.zip')
    build(p.parse_args().out)
