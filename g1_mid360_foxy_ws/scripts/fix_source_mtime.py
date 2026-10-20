"""Normalize only future mtimes of this workspace's build inputs, not system time."""
import argparse
import json
from pathlib import Path
import os
import time


def fix_future(root, now, apply=False):
    root = Path(root).resolve()
    changed = []
    for name in ('src', 'scripts'):
        for path in (root/name).rglob('*'):
            if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
                continue
            stat = path.stat()
            if stat.st_mtime > now+2:
                changed.append({'file':str(path.relative_to(root)),'old_mtime':stat.st_mtime,'new_mtime':now})
                if apply:
                    os.utime(path,(stat.st_atime,now))
    return {'future_count':len(changed),'applied':apply,'files':changed,'system_clock_modified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    report=fix_future(Path(__file__).resolve().parents[1],time.time(),args.apply)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
