"""Review exact APT candidates first. No sources, indexes or services are changed."""
import json
import re
import subprocess
import sys
from pathlib import Path

packages = ['python3-colcon-common-extensions', 'python3-yaml', 'python3-pytest',
            'ros-foxy-rmw-cyclonedds-cpp', 'ros-foxy-nav2-bringup', 'ros-foxy-slam-toolbox',
            'ros-foxy-pointcloud-to-laserscan', 'ros-foxy-diagnostic-msgs', 'ros-foxy-tf2-ros',
            'ros-foxy-tf2-msgs', 'ros-foxy-nav2-msgs', 'ros-foxy-ros2bag', 'ros-foxy-rviz2']
mode, filename = sys.argv[1:]; path = Path(filename)

def call(*args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

if mode == '--plan':
    plan = []; unavailable = []
    for name in packages:
        installed = call('dpkg-query', '-W', '-f=${Status} ${Version}', name)
        if installed.returncode == 0 and installed.stdout.startswith('install ok installed '):
            plan.append({'package': name, 'installed': installed.stdout.split()[-1], 'install': None})
            continue
        policy = call('apt-cache', 'policy', name).stdout
        m = re.search(r'Candidate:\s*(\S+)', policy)
        candidate = m.group(1) if m else '(none)'
        if candidate == '(none)':
            unavailable.append(name)
        plan.append({'package': name, 'installed': None, 'install': candidate})
    path.write_text(json.dumps({'plan': plan, 'unavailable': unavailable}, indent=2))
    print(path.read_text())
    print('Review log and source origin; --install consumes this exact version plan. Missing candidates need audited Foxy source fallback.')
    raise SystemExit(2 if unavailable else 0)
if not path.is_file():
    raise SystemExit('Run --plan and review first')
plan = json.loads(path.read_text())
if plan['unavailable']:
    raise SystemExit('APT_CANDIDATE_MISSING; no installation attempted')
specs = [p['package']+'='+p['install'] for p in plan['plan'] if p['install']]
if specs:
    subprocess.run(['sudo', 'apt-get', '--simulate', 'install', '--no-install-recommends']+specs, check=True)
    subprocess.run(['sudo', 'apt-get', 'install', '--no-install-recommends', '-y']+specs, check=True)
subprocess.run(['dpkg-query', '-W']+packages, check=True)
