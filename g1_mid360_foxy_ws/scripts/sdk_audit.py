"""Read installed SDK source/signatures without importing it or creating DDS."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument('--output', required=True); args = p.parse_args()
spec = importlib.util.find_spec('unitree_sdk2py')
report = {'live': 'DISABLED', 'sdk_imported': False, 'fsm_read': 'NOT_PERFORMED_NO_ROBOT_RPC'}
if spec is None:
    report['status'] = 'SDK_NOT_INSTALLED'
else:
    root = Path(list(spec.submodule_search_locations)[0])
    path = root/'g1/loco/g1_loco_client.py'
    data = path.read_bytes(); tree = ast.parse(data)
    report.update(status='SOURCE_AUDITED_ONLY', path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                  signatures={n.name: [a.arg for a in n.args.args] for n in ast.walk(tree)
                              if isinstance(n, ast.FunctionDef) and n.name in
                              ('SetVelocity', 'Move', 'StopMove', 'GetFsmId', 'SetFsmId')})
out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
raise SystemExit(0 if spec else 2)
