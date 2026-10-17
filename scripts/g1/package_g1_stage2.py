#!/usr/bin/env python3
"""Whitelist read-only tools separately from non-executable historical evidence."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from package_phase44 import WHITELIST as FIELD_FILES

ROOT = Path(__file__).resolve().parents[2]
HISTORY = 'docs/training-logs/quality-inspection/2026-10-17-source-archive/'
READONLY = FIELD_FILES + [
    'shared/robot_control/__init__.py','shared/robot_control/g1/__init__.py',
    'shared/robot_control/g1/loco_readonly.py','shared/robot_control/g1/motion_evidence.py',
    'shared/robot_control/g1/teach_trajectory.py','scripts/g1/g1_motion_diag_readonly.py',
    'scripts/g1/g1_arm_readonly_capture.py','scripts/g1/analyze_teach_trajectory.py',
    'scripts/g1/package_g1_stage2.py','docs/deployment/g1-stage2-readonly.md',
    'tracks/quality-inspection/gdps_qi/centering/teaching_preview.py',
]
HISTORY_DOCS = ['docs/handover/GDPS_G1_CODEX_20261018_HANDOFF.md',
    'docs/deployment/2026-10-18-g1-rgbd-teach-sop.md',
    'docs/training-logs/quality-inspection/2026-10-17-motion-field-baseline.md']


def build(output_dir):
    status = subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain','--untracked-files=no'],text=True)
    # The unrelated, user-deleted checklist is deliberately outside both bundles.
    if any(not line.endswith(' tomorrow_field_checklist.md') for line in status.splitlines()):
        raise RuntimeError('commit reviewed source before packaging')
    commit = subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    index = json.loads((ROOT/HISTORY/'index.json').read_text(encoding='utf-8'))
    archive = HISTORY_DOCS + [HISTORY+p for p in ('index.json','README.md','operator-code-verbatim.txt')]
    archive += [HISTORY+p for row in index['records'] for p in row['code_files']]
    out = Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    reports = []
    for name, whitelist in [('g1-stage2-readonly',READONLY),('g1-20261017-history-NONRUNNABLE',archive)]:
        files = {}
        for relative in sorted(set(whitelist)):
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts or '.env' in path.parts:
                raise ValueError('unsafe archive path')
            if name.endswith('NONRUNNABLE') and path.suffix not in ('.txt','.md','.json'):
                raise ValueError('executable history prohibited')
            if path.name in ('adapter.py','loco_backend.py','mock_backend.py'):
                raise ValueError('motion backend prohibited in readonly bundle')
            subprocess.check_call(['git','-C',str(ROOT),'ls-files','--error-unmatch','--',relative],
                                  stdout=subprocess.DEVNULL)
            data = (ROOT/path).read_bytes()
            # Preserve verbatim historical TXT bytes and checksum exactly.
            if path.suffix in ('.py','.sh','.ps1','.md','.json'):
                data = data.decode('utf-8-sig').replace('\r\n','\n').encode('utf-8')
            files[relative] = data
        files['MANIFEST.sha256'] = ''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n'
                                          for k,v in sorted(files.items())).encode()
        files['BUNDLE.json'] = json.dumps(dict(source_commit=commit,live_motion=False,
            execute_allowed=False,field_verified=False,kind=name,files=len(files)-1),indent=2).encode()
        destination = out/(name+'-'+commit[:12]+'.zip')
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
            for relative,data in sorted(files.items()):
                item = zipfile.ZipInfo(relative,(2026,10,17,0,0,0))
                item.compress_type=zipfile.ZIP_DEFLATED
                item.external_attr=(0o100644<<16)
                z.writestr(item,data)
        digest=hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix('.zip.sha256').write_text(digest+'  '+destination.name+'\n',encoding='utf-8')
        reports.append(dict(path=str(destination.resolve()),sha256=digest,files=len(files),source_commit=commit))
    print(json.dumps(reports,indent=2))
    return reports


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-dir',default='dist/g1-stage2-delivery')
    build(p.parse_args().out_dir)
