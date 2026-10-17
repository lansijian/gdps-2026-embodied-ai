import ast
import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_whitelist_standalone_package_has_no_motion_entry(tmp_path):
    m=runpy.run_path(str(ROOT/'scripts/g1/package_phase44.py'))
    archive=m['build'](tmp_path/'bundle.zip')
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert len(names)==len(set(names))
        assert not any(x in n.lower() for n in names for x in ('robot_control','loco_backend','cmdvel','__pycache__','.env','secret','token'))
        assert 'shared/navigation/perception/obstacle_monitor.py' in names
        assert 'scripts/g1/field_gates_centering.py' in names
        manifest=z.read('MANIFEST.sha256').decode()
        for line in manifest.splitlines():
            digest,name=line.split('  ',1)
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
        for name in names:
            if name.endswith('.py'):
                ast.parse(z.read(name).decode('utf-8'),feature_version=(3,8))
            if name.endswith('.sh'):
                assert b'\r' not in z.read(name)
                assert not z.read(name).startswith(b'\xef\xbb\xbf')
        isolated=tmp_path/'standalone'
        z.extractall(isolated)
    cmd=[sys.executable,str(isolated/'scripts/g1/field_gates_centering.py'),'--out-dir',str(tmp_path/'unknown')]
    result=subprocess.run(cmd,cwd=isolated,capture_output=True,text=True)
    assert result.returncode==1,result.stderr
    gates=json.loads(result.stdout)['gates']
    assert set(gates)==set('ABCDE')
    assert all(x['status']=='UNKNOWN' and not x['field_verified'] for x in gates.values())
    with pytest.raises(FileExistsError): m['build'](archive)


def test_bad_camera_file_does_not_hide_other_gate_reports(tmp_path):
    e={'data_source':'RECORDED_REPLAY','rows':{'frames':[{'rgb_file':'missing.npy','info':None}]}}
    path=tmp_path/'evidence.json';path.write_text(json.dumps(e))
    result=subprocess.run([sys.executable,str(ROOT/'scripts/g1/field_gates_centering.py'),
        '--evidence',str(path)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==1
    g=json.loads(result.stdout)['gates']
    assert g['A']['status']=='FAIL'
    assert g['B']['status']=='UNKNOWN'
    assert g['C']['status']=='FAIL'
    assert g['E']['status']=='UNKNOWN'
    assert len(g)==5
