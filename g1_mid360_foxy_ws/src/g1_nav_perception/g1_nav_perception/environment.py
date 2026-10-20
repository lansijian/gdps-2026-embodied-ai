"""Read-only checks before ROS initialization; no SDK imports or clock changes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def python_errors(executable, version, environ):
    reasons = []
    if tuple(version[:2]) != (3, 8) or Path(executable).resolve() != Path('/usr/bin/python3').resolve():
        reasons.append('NATIVE_PYTHON_REQUIRED: use Ubuntu /usr/bin/python3 (3.8)')
    if environ.get('CONDA_PREFIX') or environ.get('CONDA_DEFAULT_ENV'):
        reasons.append('CONDA_ACTIVE: conda deactivate in both ROS terminals before starting')
    if environ.get('PYTHONHOME'):
        reasons.append('PYTHONHOME_CONTAMINATION: unset PYTHONHOME in this ROS shell')
    if re.search(r'python3\.(?:9|1[0-9])(?:/|$)', environ.get('PYTHONPATH', '')):
        reasons.append('PYTHONPATH_VERSION_MISMATCH: another Python ABI is present')
    for name in ('AMENT_PREFIX_PATH', 'CMAKE_PREFIX_PATH', 'LD_LIBRARY_PATH', 'PYTHONPATH'):
        if re.search(r'/opt/ros/(?!foxy(?:/|:|$))[^/:]+', environ.get(name, '')):
            reasons.append('ROS_OVERLAY_MISMATCH: '+name+' contains another ROS distribution')
    return reasons


def preload_errors(rmw, preload):
    if rmw == 'rmw_fastrtps_cpp' and ('cyclone' in preload.lower() or 'libddsc' in preload.lower()):
        return ['RMW_PRELOAD_MISMATCH: remove CycloneDDS LD_PRELOAD from this FastDDS diagnostic shell']
    if rmw == 'rmw_cyclonedds_cpp' and ('fastrtps' in preload.lower() or 'fastdds' in preload.lower()):
        return ['RMW_PRELOAD_MISMATCH: FastDDS LD_PRELOAD present in CycloneDDS shell']
    return []


def dds_errors(library_paths, environ):
    # Stage 3 F5: ~/cyclonedds_ws is the verified active overlay. Custom DDS paths
    # are recorded for provenance, not rejected just because they are custom.
    warnings = ['DDS_LIBRARY_PROVENANCE:'+str(Path(p).resolve()) for p in library_paths
                if 'cyclonedds_ws' in str(p)]
    return [], warnings


def collect(phase):
    report = {'phase': phase, 'executable': sys.executable, 'version': sys.version,
              'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
              'environment': {k: os.environ.get(k) for k in (
                  'CONDA_PREFIX','CONDA_DEFAULT_ENV','PYTHONHOME','PYTHONPATH','LD_LIBRARY_PATH','AMENT_PREFIX_PATH','CMAKE_PREFIX_PATH',
                  'LD_PRELOAD','CYCLONEDDS_HOME','RMW_IMPLEMENTATION','ROS_DISTRO','ROS_DOMAIN_ID',
                  'G1_NAV_ALLOW_EXTERNAL_DDS')}, 'errors': [], 'warnings': []}
    report['errors'] = python_errors(sys.executable, sys.version_info, os.environ)
    if not report['errors'] and phase == 'rmw':
        rmw = os.environ.get('RMW_IMPLEMENTATION', 'rmw_cyclonedds_cpp')
        report['errors'].extend(preload_errors(rmw, os.environ.get('LD_PRELOAD', '')))
        if rmw not in ('rmw_cyclonedds_cpp','rmw_fastrtps_cpp'):
            report['errors'].append('RMW_UNSUPPORTED: '+rmw)
        else:
            try:
                from ament_index_python.packages import get_package_prefix
                library = Path(get_package_prefix(rmw))/'lib'/('lib'+rmw+'.so')
                if not library.is_file():
                    raise OSError('missing '+str(library))
                linked = subprocess.run(['ldd',str(library)],text=True,stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,timeout=10)
                report.update(rmw_library=str(library.resolve()),ldd=linked.stdout)
                paths = re.findall(r'=>\s+(/\S+)',linked.stdout)
                report['resolved_libraries'] = {p: str(Path(p).resolve()) for p in paths}
                if linked.returncode or 'not found' in linked.stdout:
                    report['errors'].append('RMW_LINK_DEPENDENCY_MISSING')
                errors, warnings = dds_errors(paths+os.environ.get('LD_PRELOAD', '').split(), os.environ)
                report['errors'].extend(errors);report['warnings'].extend(warnings)
            except Exception as exc:
                report['errors'].append('RMW_LIBRARY_AUDIT_FAILED: '+str(exc))
    return report


def enforce(phase='rmw'):
    from .core import Blocked
    report = collect(phase)
    if report['errors']:
        raise Blocked('; '.join(report['errors']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('python', 'rmw'), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = collect(args.phase)
    path = Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    return 2 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
