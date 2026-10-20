"""Linux launch supervisor. Only signal our own new process group, never factory nodes.

Sum RSS includes shared pages repeatedly; a conservative stop budget, not OOM proof.
Read-only resource evidence distinguishes cgroup/ulimit from host free RAM.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError) as exc:
        return 'UNAVAILABLE: '+str(exc)


def cgroup_files():
    found = {}
    for row in read('/proc/self/cgroup').splitlines():
        parts = row.split(':', 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, relative = parts
        if hierarchy == '0' and not controllers:
            root = Path('/sys/fs/cgroup')
            names = ('memory.max', 'memory.current', 'memory.events', 'memory.swap.max', 'pids.max')
        elif 'memory' in controllers.split(','):
            root = Path('/sys/fs/cgroup/memory')
            names = ('memory.limit_in_bytes', 'memory.usage_in_bytes', 'memory.failcnt', 'memory.oom_control')
        else:
            continue
        target = (root/relative.lstrip('/')).resolve()
        if root.resolve() != target and root.resolve() not in target.parents:
            continue
        for name in names:
            found[str(target/name)] = read(target/name)
    return found


def group_rss(group):
    nodes = []
    for path in Path('/proc').glob('[0-9]*/status'):
        try:
            pid = int(path.parent.name)
            if os.getpgid(pid) != group:
                continue
            fields = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
            rss = int(fields.get('VmRSS', '0 kB').split()[0])
            nodes.append({'pid': pid, 'name': fields.get('Name', '').strip(), 'rss_kib': rss})
        except (OSError, ValueError, ProcessLookupError):
            continue
    return nodes


def signal_group(group, signum):
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-rss-mib', type=int, default=4096)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not 256 <= args.max_rss_mib <= 4096:
        parser.error('command required; summed RSS stop budget must be within [256,4096] MiB')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    process = None
    interrupted = False
    def stop(signum, frame):
        nonlocal interrupted
        interrupted = True
        if process is not None and process.poll() is None:
            signal_group(process.pid, signal.SIGINT)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with output.open('w') as stream:
        def emit(value):
            stream.write(json.dumps({'wall_time': time.time(), **value})+'\n')
            stream.flush()
        emit({'event': 'environment', 'uname': list(os.uname()),
              'meminfo': read('/proc/meminfo'), 'limits': read('/proc/self/limits'),
              'rlimit_as': resource.getrlimit(resource.RLIMIT_AS), 'cgroup': cgroup_files(),
              'RMW_IMPLEMENTATION': os.environ.get('RMW_IMPLEMENTATION'),
              'ROS_DISTRO': os.environ.get('ROS_DISTRO'), 'ROS_DOMAIN_ID': os.environ.get('ROS_DOMAIN_ID', 'default'),
              'CYCLONEDDS_URI': os.environ.get('CYCLONEDDS_URI', 'default'),
              'budget_sum_rss_mib': args.max_rss_mib})
        process = subprocess.Popen(command, start_new_session=True)
        over = 0
        reason = 'NORMAL_EXIT'
        while process.poll() is None and not interrupted:
            nodes = group_rss(process.pid)
            total = sum(n['rss_kib'] for n in nodes)
            emit({'event': 'sample', 'nodes': nodes, 'sum_rss_kib': total, 'cgroup': cgroup_files()})
            over = over+1 if total > args.max_rss_mib*1024 else 0
            if over >= 3:
                reason = 'OWN_STACK_RSS_BUDGET_EXCEEDED'
                print(reason+': shutting down this launch group; inspect '+str(output), flush=True)
                signal_group(process.pid, signal.SIGINT)
                break
            time.sleep(1)
        if interrupted:
            reason = 'USER_SIGNAL'
        try:
            code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            signal_group(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                signal_group(process.pid, signal.SIGKILL)
                code = process.wait(timeout=5)
        try:
            kernel = subprocess.run(['dmesg', '--ctime'], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            kernel = argparse.Namespace(returncode=-1, stdout='UNAVAILABLE: '+str(exc))
        emit({'event': 'exit', 'reason': reason, 'returncode': code,
              'cgroup': cgroup_files(), 'dmesg_returncode': kernel.returncode,
              'kernel_tail': kernel.stdout.splitlines()[-200:]})
    return 2 if reason == 'OWN_STACK_RSS_BUDGET_EXCEEDED' else (code if code >= 0 else 128-code)


if __name__ == '__main__':
    raise SystemExit(main())
