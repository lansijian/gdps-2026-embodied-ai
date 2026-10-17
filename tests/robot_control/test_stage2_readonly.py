"""Counterexamples and integration tests use SYNTHETIC_TEST only, never DDS."""
import ast
import copy
import dataclasses
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from shared.robot_control.g1.teach_trajectory import (
    InvalidTeachingData, load_teaching_session, parse_observation,
    smooth_observed_angles, summarize_session, validate_session,
)
from tests.robot_control.test_teach_trajectory import row

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('capture', ROOT/'scripts/g1/g1_arm_readonly_capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def message(tick=1):
    return NS(mode_machine=5, tick=tick, imu_state=NS(rpy=[0.,0.,0.]),
              motor_state=[NS(q=.01*j, dq=.02*j, tau_est=.03*j) for j in range(35)])


def samples():
    result = []
    for i in range(3):
        r = capture.observe(message(i+1), 100+i*.05, 10+i*.05)
        r['data_source'] = 'SYNTHETIC_TEST'
        result.append(parse_observation(r))
    return result


def test_capture_covers_all_17_joints_and_receipt_time():
    r = capture.observe(message(), 100., 10.)
    assert r['joints'] == list(range(15,29))
    for j in range(15,29):
        assert r['q'][j-15] == .01*j
        assert r['dq'][j-15] == .02*j
        assert r['tau_est'][j-15] == .03*j
    for j in (12,13,14):
        assert r['waist'][str(j)] == dict(q=.01*j, dq=.02*j, tau_est=.03*j)
    assert (r['timestamp_s'], r['received_monotonic_s'], r['tick']) == (100.,10.,1)
    assert r['motor_write_allowed'] is False


@pytest.mark.parametrize('joint,field', [(12,'q'),(14,'dq'),(15,'tau_est'),(28,'q')])
def test_capture_rejects_nonfinite_even_waist(joint,field):
    msg = message()
    setattr(msg.motor_state[joint],field,math.nan)
    with pytest.raises(InvalidTeachingData):
        capture.observe(msg, 100.,10.)


def test_duplicate_tick_stale_and_invalid_callback_cannot_reuse_sample():
    buffer = capture.ObservationBuffer()
    buffer.ingest(message(),100.,10.)
    assert buffer.take(10.1)['tick'] == 1
    buffer.ingest(message(),100.1,10.1)
    assert buffer.take(10.1) is None
    buffer.ingest(message(2),100.2,10.2)
    assert buffer.take(10.5) is None
    buffer.ingest(message(3),100.3,10.3)
    bad = message(4); bad.motor_state[12].q = math.nan
    buffer.ingest(bad,100.4,10.4)
    assert buffer.take(10.4) is None
    assert buffer.counts['nonadvancing_tick'] == 1
    assert buffer.counts['stale'] == 1
    assert buffer.counts['invalid'] == 1


@pytest.mark.parametrize('field,value', [('mode_machine',True),('mode_machine',5.1),
                                       ('timestamp_s',True),('q',[True]*14),('q',['0.1']*14)])
def test_parser_does_not_coerce_malformed_values(field,value):
    record = row(1.)
    record[field] = value
    with pytest.raises(InvalidTeachingData):
        parse_observation(record)


@pytest.mark.parametrize('change', ['reversed_wall','reversed_mono','clock_jump','gap','duplicate_tick',
                                    'arm_jump','waist_jump','initial_nan','source_change','missing_waist'])
def test_filter_refuses_bad_session_before_smoothing(change):
    s = samples()
    if change == 'reversed_wall': s[1] = dataclasses.replace(s[1],timestamp_s=99.)
    if change == 'reversed_mono': s[1] = dataclasses.replace(s[1],received_monotonic_s=9.)
    if change == 'clock_jump': s[1] = dataclasses.replace(s[1],timestamp_s=100.2)
    if change == 'gap': s[1] = dataclasses.replace(s[1],timestamp_s=101.)
    if change == 'duplicate_tick': s[1] = dataclasses.replace(s[1],tick=1)
    if change == 'arm_jump': s[1] = dataclasses.replace(s[1],q=(4.,)*14)
    if change == 'waist_jump': s[1] = dataclasses.replace(s[1],waist=((1.,0.,0.),)*3)
    if change == 'initial_nan': s[0] = dataclasses.replace(s[0],q=(math.nan,)*14)
    if change == 'source_change': s[1] = dataclasses.replace(s[1],data_source='REAL_SENSOR')
    if change == 'missing_waist': s[1] = dataclasses.replace(s[1],waist=())
    with pytest.raises(InvalidTeachingData):
        smooth_observed_angles(s)


def test_limits_only_checked_with_complete_explicit_profile():
    s = samples()
    assert summarize_session(s)['mechanical_limits'] == 'UNKNOWN'
    assert summarize_session(s)['full_telemetry'] is True
    limits = {j:(-1.,1.) for j in range(12,29)}
    assert summarize_session(s,joint_limits=limits)['mechanical_limits'] == 'CHECKED'
    limits[28] = (-.1,.1)
    with pytest.raises(InvalidTeachingData, match='joint_limit'):
        validate_session(s,joint_limits=limits)
    assert summarize_session(s)['replay_authorized'] is False


def test_filter_reduces_stationary_noise_and_preserves_raw():
    values = [.2 + (.02 if i%2 else -.02) for i in range(30)]
    s = [parse_observation(row(1+i*.05,q)) for i,q in enumerate(values)]
    raw = [x.q for x in s]
    estimate = smooth_observed_angles(s)
    raw_mse = sum((q-.2)**2 for q in values[10:])/20
    est_mse = sum((q[0]-.2)**2 for q in estimate[10:])/20
    assert est_mse < raw_mse*.25
    assert [x.q for x in s] == raw


def test_bad_json_reports_line(tmp_path):
    path=tmp_path/'bad.jsonl'; path.write_text('{}\nxxx')
    with pytest.raises(InvalidTeachingData,match='line 1'):
        load_teaching_session(path)


def test_preview_reuses_centering_and_provenance_gate_and_blocks_grasp():
    from gdps_qi.adapters.camera import CameraFrame, CameraInfo
    from gdps_qi.centering.target_centering_controller import TargetCenteringController
    from gdps_qi.centering.teaching_preview import TeachingPreview
    from gdps_qi.perception.detection_types import Detection
    from gdps_qi.transforms.transform_manager import TransformManager
    tf = TransformManager()
    tf.set_transform('robot_center','camera_color_optical_frame',np.eye(4),1.,'test',static=True)
    preview = TeachingPreview(TargetCenteringController(tf))
    det = Detection('target','same',.9,(0,0,10,10),(320.,240.))
    def frame(t):
        return CameraFrame(rgb=np.zeros((480,640,3),dtype=np.uint8),
                           depth_m=np.full((480,640),.8), stamp=t,
                           info=CameraInfo(640,480,500,500,320,240), intrinsics_trusted=True,
                           depth_scale_confirmed=True,depth_aligned_to_rgb=True,
                           rgb_stamp_sec=t,depth_stamp_sec=t,camera_info_stamp_sec=t)
    results = [preview.observe(frame(t),det,body_stable=True,workspace_ok=True,
                               uncertainty_ok=True, calibration_verified=True,tcp_verified=True,
                               depth_reliable=True,tf_fresh=True) for t in (1.,1.05,1.1)]
    assert results[-1]['stage'] == 'BODY_READY_BLOCKED'
    assert 'source_evidence_bundle_missing' in results[-1]['reasons']
    assert all(not r['motor_write_allowed'] and not r['grasp_ready'] for r in results)
    changed = copy.copy(det); changed.object_id = 'other'
    assert preview.observe(frame(1.15),changed)['stage'] == 'SAFE_HOLD'


def test_archive_integrity_and_no_executable_history():
    archive = ROOT/'docs/training-logs/quality-inspection/2026-10-17-source-archive'
    index = json.loads((archive/'index.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((archive/index['source']).read_bytes()).hexdigest() == index['source_sha256']
    assert len(index['records']) == 27
    assert not list(archive.rglob('*.py'))
    assert all(not r['execute_allowed'] and r['code_files'] for r in index['records'])


def test_readonly_entrypoints_have_no_motion_publishers_or_imports():
    forbidden = {'SetFsmId','SetVelocity','Damp','Lie2StandUp','SelectMode','ReleaseMode',
                 'ChannelPublisher','Write','HandCmd_','LowCmd_','ArmAction'}
    for relative in ('scripts/g1/g1_arm_readonly_capture.py','scripts/g1/g1_motion_diag_readonly.py',
                     'scripts/g1/analyze_teach_trajectory.py','shared/robot_control/g1/teach_trajectory.py',
                     'shared/robot_control/g1/loco_readonly.py'):
        tree=ast.parse((ROOT/relative).read_text(encoding='utf-8'))
        names={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        names.update(n.id for n in ast.walk(tree) if isinstance(n,ast.Name))
        assert not forbidden & names, relative


@pytest.mark.parametrize('response', [(True,'{"data":501}'),(0,'{"data":true}'),
                                    (0,'{"data":-1}'),(0,'{"data":501.5}'),(0,'bad-json')])
def test_rpc_malformed_or_negative_is_not_valid_state(response):
    from shared.robot_control.g1.loco_readonly import LocoReadOnlyClient
    client = LocoReadOnlyClient('offline-interface')
    client._client = NS(_Call=lambda *_: response)
    assert client.get_fsm_id() == (-15,None)


def test_rpc_zero_is_not_physical_completion_or_motion_authority():
    from shared.robot_control.g1.motion_evidence import MotionSnapshot
    snap = MotionSnapshot(monotonic_s=10.,fsm_id=802,command_rpc_code=0,
                          rpc_status={'fsm_id':dict(code=0,value=802,received_monotonic=10.)})
    report=snap.to_dict()
    assert report['state']=='QUERY_OK_NOT_AUTHORIZED'
    assert report['capabilities']['SDK_RPC_ACCEPTED'] is True
    assert report['execute_allowed'] is False
    assert report['capabilities']['PHYSICAL_ACTION_VERIFIED'] is False
    snap.monotonic_s=12.
    assert snap.to_dict()['state']=='UNKNOWN'


@pytest.mark.parametrize('failure',['bad_direction','wrong_object','authority_revoked','audit_failed'])
def test_active_mock_stops_when_renewal_rejected(tmp_path,monkeypatch,failure):
    from shared.robot_control.g1.adapter import G1MotionAdapter
    from shared.robot_control.g1.command import VelocityCommand
    from shared.robot_control.g1.mock_backend import MockLocoBackend
    backend=MockLocoBackend()
    adapter=G1MotionAdapter(backend, lock_path=str(tmp_path/'lock'),live_token='offline-only')
    monkeypatch.setenv('GDPS_G1_LIVE','1')
    assert adapter.connect()==0
    adapter.enable_live('offline-only','ENABLE LIVE MOTION')
    adapter.motion_authority_confirmed=True
    adapter.allowed_live_fsm_ids=(501,)
    assert adapter.send_velocity(VelocityCommand(vx=.04))==0
    before=backend.stop_count
    try:
        if failure=='bad_direction': code=adapter.move_once('invalid')
        if failure=='wrong_object': code=adapter.send_velocity(object())
        if failure=='authority_revoked':
            adapter.motion_authority_confirmed=False
            code=adapter.send_velocity(VelocityCommand(vx=.04))
        if failure=='audit_failed':
            adapter.event_log=NS(emit=lambda *a,**k: (_ for _ in ()).throw(OSError('offline test')))
            code=adapter.send_velocity(VelocityCommand(vx=.04))
        assert code != 0
        assert adapter.last_return_code == code
        assert backend.stop_count>before
        assert adapter.last_command.is_zero()
    finally:
        adapter.close()


def test_bounded_mock_exit_attempts_stop_after_exception(tmp_path,monkeypatch):
    from shared.robot_control.g1.adapter import G1MotionAdapter
    from shared.robot_control.g1.mock_backend import MockLocoBackend
    backend=MockLocoBackend()
    a=G1MotionAdapter(backend,lock_path=str(tmp_path/'lock'),live_token='offline-only')
    monkeypatch.setenv('GDPS_G1_LIVE','1')
    a.connect(); a.enable_live('offline-only','ENABLE LIVE MOTION')
    a.motion_authority_confirmed=True; a.allowed_live_fsm_ids=(501,)
    def interrupt(_): raise KeyboardInterrupt()
    monkeypatch.setattr('shared.robot_control.g1.adapter.time.sleep',interrupt)
    try:
        with pytest.raises(KeyboardInterrupt): a.move_once('forward')
        assert backend.stop_count>=1
    finally: a.close()


@pytest.mark.parametrize('init_error',[False,True])
def test_capture_cli_closes_subscriber_on_success_and_init_failure(tmp_path,monkeypatch,init_error):
    import types
    calls=[]
    class Subscriber:
        def __init__(self,topic,typ): calls.append(('subscribe',topic))
        def Init(self,cb,queue):
            if init_error: raise RuntimeError('synthetic init failure')
            cb(message())
        def Close(self): calls.append(('close',))
    channel=types.ModuleType('unitree_sdk2py.core.channel')
    channel.ChannelSubscriber=Subscriber
    channel.ChannelFactoryInitialize=lambda domain,iface: calls.append(('factory',domain,iface))
    def forbidden(*a,**k): raise AssertionError('write attempted')
    channel.ChannelPublisher=forbidden
    idl=types.ModuleType('unitree_sdk2py.idl.unitree_hg.msg.dds_'); idl.LowState_=object
    monkeypatch.setitem(sys.modules,'unitree_sdk2py.core.channel',channel)
    monkeypatch.setitem(sys.modules,'unitree_sdk2py.idl.unitree_hg.msg.dds_',idl)
    out=tmp_path/'observations.jsonl'
    code=capture.main(['--seconds','.03','--hz','50','--iface','SYNTHETIC_TEST','--out',str(out)])
    assert calls[-1]==('close',)
    result=json.loads(out.with_suffix('.jsonl.report.json').read_text(encoding='utf-8'))
    assert result['motor_write_allowed'] is False
    assert result['field_verified'] is False
    if init_error:
        assert code==1 and result['status']=='UNKNOWN' and result['error']
    else:
        assert code==0 and result['counts']['saved']==1
        assert parse_observation(json.loads(out.read_text(encoding='utf-8'))).tick==1
