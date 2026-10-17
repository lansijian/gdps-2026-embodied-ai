"""Exercise the real shell script with isolated SYNTHETIC_TEST ROS commands; no ROS/G1 calls."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
BASH=shutil.which('bash') or str(Path('C:/Users/UserX/Git/bin/bash.exe'))


def bash_path(path):
    value=Path(path).resolve().as_posix()
    return '/'+value[0].lower()+value[2:] if len(value)>1 and value[1]==':' else value


def run_recorder(tmp_path, execute=True, interrupt=False, failure=False):
    if not Path(BASH).is_file(): pytest.skip('Bash unavailable for isolated recording harness')
    fake=tmp_path/'fake_recorder.sh'
    fake.write_text('''#!/usr/bin/env bash
set -eu
mkdir -p "$OUT"
printf '%s\\n' "$@" > "$(dirname "$OUT")/recorder-args.txt"
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[$i]}" == --qos-profile-overrides-path ]]; then
    qos="${args[$((i+1))]}"
    if command -v cygpath >/dev/null; then qos="$(cygpath -w "$qos")"; fi
    printf '%s\\n' "$qos" > "$(dirname "$OUT")/qos-path.txt"
  fi
done
trap 'printf "SYNTHETIC_TEST: true\\n" > "$OUT/metadata.yaml"; exit 0' INT TERM
[[ "${TEST_FAILURE_ARG:-}" != --test-failure ]] || exit 7
while :; do sleep 0.05; done
''',encoding='utf-8')
    wrapper=tmp_path/'wrapper.sh'
    wrapper.write_text('''#!/usr/bin/env bash
set -eu
# Only the setup call is stubbed; the production script and its traps run unmodified.
source() { :; }
ros2() {
  case "$1 $2" in
    'topic list') printf '/rgb\\n/utlidar/cloud_livox_mid360\\n/dog_odom\\n/tf\\n/tf_static\\n';;
    'topic type') case "$3" in
      /rgb) echo sensor_msgs/msg/Image;;
      /utlidar/cloud_livox_mid360) echo sensor_msgs/msg/PointCloud2;;
      /dog_odom) echo nav_msgs/msg/Odometry;;
      /tf|/tf_static) echo tf2_msgs/msg/TFMessage;;
      *) return 2;; esac;;
    'bag record') exec env --default-signal=INT bash "$TEST_RECORDER" "$@";;
    'bag info') echo 'SYNTHETIC_TEST bag info';;
    *) return 2;;
  esac
}
export -f source ros2
if [[ "${TEST_INTERRUPT:-0}" == 1 ]]; then
  target=$$
  (sleep 0.7; kill -TERM "$target") &
fi
exec bash "$TEST_SCRIPT" "$@"
''',encoding='utf-8')
    env={**os.environ,'TEST_PYTHON':bash_path(sys.executable),'TEST_RECORDER':bash_path(fake),
        'TEST_SCRIPT':bash_path(ROOT/'scripts/g1/record_field_bag.sh'),
        'OUT':bash_path(tmp_path/'bag'),'RGB_TOPIC':'/rgb','DURATION':'1','MIN_FREE_KB':'1',
        'TEST_INTERRUPT':'1' if interrupt else '0','TEST_FAILURE_ARG':'--test-failure' if failure else ''}
    args=[BASH,bash_path(wrapper)]+(['--execute-reviewed'] if execute else [])
    return subprocess.run(args,env=env,capture_output=True,text=True,encoding="utf-8",timeout=25)


def test_record_existing_topics_without_scan_and_cleanup(tmp_path):
    r=run_recorder(tmp_path)
    assert r.returncode==0,(r.stdout,r.stderr)
    assert 'Missing (not selected): /scan' in r.stdout
    args=(tmp_path/'recorder-args.txt').read_text(encoding='utf-8').splitlines()
    assert '/scan' not in args
    assert '/utlidar/cloud_livox_mid360' in args and '/dog_odom' in args
    assert '--qos-profile-overrides-path' in args and '-o' in args
    assert (tmp_path/'bag/metadata.yaml').exists()
    qos=(tmp_path/'qos-path.txt').read_text(encoding='utf-8').strip()
    assert not Path(qos).exists()


def test_record_preview_starts_no_recorder(tmp_path):
    r=run_recorder(tmp_path,execute=False)
    assert r.returncode==0,(r.stdout,r.stderr)
    assert not (tmp_path/'recorder-args.txt').exists()


def test_record_termination_flushes_and_does_not_claim_success(tmp_path):
    r=run_recorder(tmp_path,interrupt=True)
    assert r.returncode==143,(r.stdout,r.stderr)
    assert 'Recorded bag:' not in r.stdout
    assert (tmp_path/'bag/metadata.yaml').is_file()
    args=(tmp_path/'recorder-args.txt').read_text(encoding='utf-8').splitlines()
    assert not Path((tmp_path/'qos-path.txt').read_text(encoding='utf-8').strip()).exists()


def test_recorder_error_is_not_reported_as_success(tmp_path):
    r=run_recorder(tmp_path,failure=True)
    assert r.returncode!=0
    assert 'Recorded bag:' not in r.stdout
