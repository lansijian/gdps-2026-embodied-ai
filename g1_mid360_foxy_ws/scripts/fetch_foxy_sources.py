"""Explicit source fallback; fetch only missing packages at reviewed immutable SHAs."""
import argparse
import json
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument('--fetch', action='store_true'); args = p.parse_args()
root = Path(__file__).resolve().parents[1]
lock = json.loads((root/'third_party.lock').read_text())
for name, pkg in (('navigation2', 'nav2_bringup'), ('slam_toolbox', 'slam_toolbox'), ('pointcloud_to_laserscan', 'pointcloud_to_laserscan')):
    if subprocess.run(['ros2', 'pkg', 'prefix', pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print('Already installed:', pkg); continue
    source = lock['sources'][name]; target = root/'external_sources'/name
    print('Missing:', pkg, 'source:', source)
    if not args.fetch:
        continue
    if target.exists():
        sha = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        if sha != source['version']:
            raise SystemExit('Existing source SHA mismatch; refusing overwrite')
    else:
        target.mkdir(parents=True)
        subprocess.run(['git', 'init', str(target)], check=True)
        subprocess.run(['git', '-C', str(target), 'remote', 'add', 'origin', source['url']], check=True)
        subprocess.run(['git', '-C', str(target), 'fetch', '--depth', '1', 'origin', source['version']], check=True)
        subprocess.run(['git', '-C', str(target), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    print('Review rosdep plan: rosdep install --simulate --from-paths', target, '--ignore-src --rosdistro foxy')
print('Build explicit paths/packages only; never recompile installed Nav2 core without reviewing duplicate package list.')
