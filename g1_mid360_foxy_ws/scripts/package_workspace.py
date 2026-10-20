"""Portable source archive with a manifest; exclude robot data and local calibration."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

p = argparse.ArgumentParser(); p.add_argument('--source', required=True); p.add_argument('--output', required=True); args = p.parse_args()
root = Path(args.source).resolve(); output = Path(args.output).resolve()
files = []
for path in root.rglob('*'):
    rel = path.relative_to(root)
    if any(part in {'external', 'external_sources', 'logs', 'build', 'install', 'log', '__pycache__', '.pytest_cache', '.git'} for part in rel.parts):
        continue
    if len(rel.parts) > 1 and rel.parts[0] not in {'src', 'scripts', 'docs', 'tests', 'licenses'}:
        continue
    if (path.is_file() and not path.is_symlink() and path.name != 'site.yaml' and
            not path.name.startswith('.env') and path != output and
            path.suffix not in ('.zip', '.gz', '.pyc', '.bag', '.db3', '.mcap', '.pcd', '.log')):
        files.append(path)
output.parent.mkdir(parents=True, exist_ok=True)
manifest = {str(f.relative_to(root)).replace('\\', '/'): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
if output.suffix == '.zip':
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for f in sorted(files):
            archive.write(f, str(f.relative_to(root)).replace('\\', '/'))
        archive.writestr('SOURCE_MANIFEST.json', json.dumps(manifest, indent=2))
else:
    with tarfile.open(output, 'w:gz') as archive:
        for f in sorted(files):
            data = f.read_bytes(); info = tarfile.TarInfo(str(f.relative_to(root)).replace('\\', '/'))
            info.size = len(data); info.mode = 0o755 if f.suffix == '.sh' else 0o644
            archive.addfile(info, io.BytesIO(data))
        data = json.dumps(manifest, indent=2).encode(); info = tarfile.TarInfo('SOURCE_MANIFEST.json'); info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
print(json.dumps({'archive': str(output), 'files': len(files), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))
