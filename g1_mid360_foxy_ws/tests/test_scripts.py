import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import tarfile
import zipfile
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('suffix',['.zip','.tar.gz'])
def test_source_packaging_excludes_robot_data_and_has_valid_hash_manifest(tmp_path,suffix):
    source=tmp_path/'workspace';source.mkdir()
    for name in ['README.md','src/pkg/code.py','logs/robot.json','config/site.yaml',
                 'site.yaml','.env','src/pkg/session.db3','external/vendor/code.py','robot_data/raw.csv']:
        p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('content')
    output=tmp_path/('delivery'+suffix)
    subprocess.run([sys.executable,str(ROOT/'scripts/package_workspace.py'),'--source',str(source),
                    '--output',str(output)],check=True,capture_output=True)
    if suffix=='.zip':
        with zipfile.ZipFile(output) as z:
            payload={n:z.read(n) for n in z.namelist()}
    else:
        with tarfile.open(output) as z:
            payload={m.name:z.extractfile(m).read() for m in z.getmembers()}
    manifest=json.loads(payload.pop('SOURCE_MANIFEST.json'))
    assert set(payload)=={'README.md','src/pkg/code.py'}
    assert manifest=={n:hashlib.sha256(data).hexdigest() for n,data in payload.items()}


def test_sdk_source_audit_does_not_import_sdk_or_initialize_dds(tmp_path):
    root=tmp_path/'unitree_sdk2py';(root/'g1/loco').mkdir(parents=True)
    (root/'__init__.py').write_text("raise AssertionError('SDK must never be imported')\n")
    (root/'g1/loco/g1_loco_client.py').write_text('class LocoClient:\n    def SetVelocity(self,vx,vy,omega,duration=1.0): pass\n')
    env=os.environ.copy();env['PYTHONPATH']=str(tmp_path)
    output=tmp_path/'sdk.json'
    subprocess.run([sys.executable,str(ROOT/'scripts/sdk_audit.py'),'--output',str(output)],env=env,check=True,capture_output=True)
    report=json.loads(output.read_text())
    assert report['sdk_imported'] is False and report['live']=='DISABLED'
    assert report['signatures']['SetVelocity']['args']==['self','vx','vy','omega','duration']


def test_floor_calibration_cli_with_explicit_synthetic_points(tmp_path):
    site=yaml.safe_load((ROOT/'src/g1_nav_config/config/site.example.yaml').read_text())
    site['calibration'].update(translation_xyz=[0.,0.,.6],quaternion_xyzw=[1.,0.,0.,0.])
    site['filter'].update(min_height=.1,max_height=1.5)
    (tmp_path/'site.yaml').write_text(yaml.safe_dump(site))
    (tmp_path/'floor.csv').write_text('x,y,z\n0,0,0.6\n1,0,0.6\n0,1,0.6\n1,1,0.6\n')
    (tmp_path/'obstacle.csv').write_text('x,y,z\n1,0,0.3\n1,1,0.3\n1,0,0.2\n')
    output=tmp_path/'result.json'
    subprocess.run([sys.executable,str(ROOT/'scripts/calibration_check.py'),'--site',str(tmp_path/'site.yaml'),
                    '--floor-csv',str(tmp_path/'floor.csv'),'--obstacle-csv',str(tmp_path/'obstacle.csv'),
                    '--output',str(output)],check=True,capture_output=True)
    report=json.loads(output.read_text())
    assert abs(report['floor_mean_z_m'])<1e-8 and report['tilt_deg']<1e-8
    assert report['floor_in_obstacle_window_ratio']==0 and report['obstacle_retention_ratio']==1
