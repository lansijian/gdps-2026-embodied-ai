import ast
import copy
import math
from pathlib import Path
import struct
from types import SimpleNamespace as NS
import xml.etree.ElementTree as ET
import pytest
import yaml
from g1_nav_perception.core import (Blocked, _strict_site as validate_site, Stream, rotate, points_xyz, DryGate)
from g1_nav_bridge.motion_lock import MotionLock, MotionLockError
from g1_ros2_bridge.joint_names import JOINT_NAMES
from g1_nav_perception.cloud import crop

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def site():
    s = yaml.safe_load((ROOT/'src/g1_nav_config/config/site.example.yaml').read_text(encoding='utf-8'))
    for key in ('calibration', 'timing', 'filter'):
        s[key].update(verified=True, evidence_id='SYNTHETIC_TEST_ONLY')
    s['data_source'] = 'SYNTHETIC_TEST'
    s['calibration'].update(translation_xyz=[0., 0., 0.], quaternion_xyzw=[0., 0., 0., 1.])
    s['filter'].update(ground_z=0., ground_margin=.05, min_height=.1, max_height=1.5, scan_time=.1)
    s['robot'].update(footprint_verified=True, safe_environment_confirmed=True, blind_spots_reviewed=True,
                      footprint=[[-.25, -.2], [.25, -.2], [.25, .2], [-.25, .2]])
    return s


def test_example_blocks():
    s = yaml.safe_load((ROOT/'src/g1_nav_config/config/site.example.yaml').read_text(encoding='utf-8'))
    with pytest.raises(Blocked, match='BLOCKED_NEEDS_CALIBRATION'):
        validate_site(s)


def test_synthetic_configuration(site):
    validate_site(site)


def test_ground_below_body_origin_and_low_obstacle_retained(site):
    site['filter'].update(ground_z=-.8, ground_margin=.03, min_height=-.75, max_height=1.)
    validate_site(site)
    f=site['filter']
    assert not f['min_height'] <= -.8 <= f['max_height']
    assert f['min_height'] <= -.7 <= f['max_height']


@pytest.mark.parametrize('section', ['calibration', 'timing', 'filter'])
def test_no_unverified_or_missing_evidence(site, section):
    site[section]['evidence_id'] = ''
    with pytest.raises(Blocked):
        validate_site(site)


@pytest.mark.parametrize('strategy', ['receive_time', 'fixed_offset', '4883', 'auto'])
def test_no_unproven_clock_repairs(site, strategy):
    site['timing']['strategy'] = strategy
    with pytest.raises(Blocked):
        validate_site(site)


@pytest.mark.parametrize('field', ['footprint_verified', 'safe_environment_confirmed', 'blind_spots_reviewed'])
def test_stairs_and_environment_must_be_reviewed(site, field):
    site['robot'][field] = False
    with pytest.raises(Blocked, match='BLOCKED_ENVIRONMENT'):
        validate_site(site)


@pytest.mark.parametrize('q,p,want', [([1.,0.,0.,0.],[0.,0.,1.],[0.,0.,-1.]),
    ([0.,1.,0.,0.],[1.,0.,0.],[-1.,0.,0.]),([0.,0.,1.,0.],[0.,1.,0.],[0.,-1.,0.]),
    ([0.,0.,0.,1.],[1.,2.,3.],[1.,2.,3.])])
def test_quaternion_axes_and_floor_normal(q, p, want):
    assert rotate(q, p) == pytest.approx(want)


def test_inverted_floor_is_transformed_before_height_crop(site):
    q=[1.,0.,0.,0.]; translation=[0.,0.,.6]
    floor=rotate(q,[0.,0.,.6]); obstacle=rotate(q,[1.,0.,.3])
    assert floor[2]+translation[2] == pytest.approx(0)
    assert obstacle[2]+translation[2] == pytest.approx(.3)
    assert not .1 <= floor[2]+translation[2] <= 1.5
    assert .1 <= obstacle[2]+translation[2] <= 1.5


@pytest.mark.parametrize('stamp,now,reason', [(0.,1.,'INVALID_STAMP'),(101.,100.,'FUTURE_STAMP'),(1.,100.,'STALE_STAMP')])
def test_bad_timestamps(stamp, now, reason):
    s=Stream(); assert not s.observe(stamp,now,1.); assert s.reason==reason


def test_clock_jump_order_timeout_and_recovery():
    s=Stream(); assert s.observe(100.,100.01,1.)
    assert not s.observe(100.,100.02,1.1); assert s.reason=='OUT_OF_ORDER'
    assert not s.observe(101.,101.01,1.2); assert s.reason=='CLOCK_JUMP'
    assert s.observe(101.1,101.11,1.3)
    assert not s.healthy(2.)
    assert not s.healthy(.1)
    assert s.report()['invalid']==2


def test_stream_window_is_bounded_and_reports_measured_frequency():
    s=Stream()
    for i in range(32000):
        assert s.observe(100+i*.001,100.01+i*.001,1+i*.001)
    report=s.report()
    assert len(s.samples)<=30001
    assert report['hz']==pytest.approx(1000.,rel=.001)
    assert report['offset_p95_s']==pytest.approx(.01)


@pytest.mark.parametrize('big,datatype', [(False,7),(True,7),(False,8),(True,8)])
def test_organized_cloud_padding_and_endian(big, datatype):
    fmt=('>' if big else '<')+('fff' if datatype==7 else 'ddd')
    size=struct.calcsize(fmt)
    msg=NS(fields=[NS(name=n, offset=i*(size//3), datatype=datatype,count=1) for i,n in enumerate('xyz')],
        data=struct.pack(fmt,1,2,3)+b'PAD!'+struct.pack(fmt,4,5,6)+b'PAD!',
        height=2,width=1,point_step=size,row_step=size+4,is_bigendian=big)
    assert list(points_xyz(msg))==[[1.,2.,3.],[4.,5.,6.]]
    data,width,stats=crop(msg,[0.,0.,.6],[1.,0.,0.,0.],-6.,4.)
    expected=[]
    for point in points_xyz(msg):
        v=rotate([1.,0.,0.,0.],point)
        expected.extend((v[0],v[1],v[2]+.6))
    assert struct.unpack('<ffffff',data)==pytest.approx(expected)
    assert width==stats['retained']==2 and stats['finite_points']==2
    msg.data=b''
    with pytest.raises(Blocked):list(points_xyz(msg))


class TripwireSDK:
    def __init__(self):self.writes=0
    def __getattr__(self,name):
        def fail(*args,**kwargs):
            self.writes+=1;raise AssertionError('SDK touched: '+name)
        return fail


@pytest.mark.parametrize('command', [(1.,0,0,0,0,0),(0,.1,0,0,0,0),(0,0,.1,0,0,0),
    (0,0,0,.1,0,0),(.1,0,0,0,0,float('nan')),(float('inf'),0,0,0,0,0)])
def test_invalid_commands_zero_and_no_sdk(site, command):
    sdk=TripwireSDK();g=DryGate(site['limits'],sdk);g.command(command,1.)
    assert g.tick(1.01,True)==(0.,0.,0.);assert sdk.writes==0


@pytest.mark.parametrize('fault', ['scan_loss','odom_loss','tf_loss','heartbeat_loss','dynamic_obstacle','wrong_tf','stale_time','qos_incompatible','negative_obstacle_unreviewed'])
def test_fault_zero_preview_and_never_write_sdk(site,fault):
    sdk=TripwireSDK();g=DryGate(site['limits'],sdk)
    for i in range(10):
        now=1+i*.05;g.command((.1,0,0,0,0,.1),now);g.tick(now,True)
    assert g.previous[0] > 0
    assert g.tick(1.51,False,fault)==(0.,0.,0.)
    assert g.reason==fault;assert sdk.writes==0


def test_timeout_frame_rate_acceleration_and_restart(site):
    g=DryGate(site['limits']);g.command((.1,0,0,0,0,.15),1.)
    assert g.tick(1.,True)==(0.,0.,0.)
    assert g.tick(1.1,True)==pytest.approx((.005,0,.01))
    assert g.tick(2.,True)==(0.,0.,0.)
    g.command((.1,0,0,0,0,0),2.,'map');assert g.tick(2.01,True)==(0.,0.,0.)
    assert DryGate(site['limits']).tick(2.,True)==(0.,0.,0.)


@pytest.mark.parametrize('live,dry', [(True,True),(False,False),(True,False)])
def test_live_cannot_be_enabled(site,live,dry):
    with pytest.raises(Blocked,match='LIVE_DISABLED'):DryGate(site['limits'],TripwireSDK(),live,dry)


def test_same_motion_lock(tmp_path):
    first=MotionLock.acquire('one',tmp_path/'lock')
    try:
        with pytest.raises(MotionLockError):MotionLock.acquire('two',tmp_path/'lock')
    finally:first.release()
    second=MotionLock.acquire('two',tmp_path/'lock');second.release()


def test_python38_syntax_and_package_discovery():
    packages=list((ROOT/'src').glob('*/package.xml'))
    assert len(packages)==7
    for p in packages:
        name=ET.parse(p).findtext('name'); assert name==p.parent.name
    for p in list((ROOT/'src').rglob('*.py'))+list((ROOT/'scripts').glob('*.py')):
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p),feature_version=(3,8))
    for p in (ROOT/'src').rglob('*.yaml'):yaml.safe_load(p.read_text(encoding='utf-8'))
    for p in (ROOT/'src').rglob('*.xml'):ET.parse(p)
    assert len(set(JOINT_NAMES))==29


def test_no_sdk_write_code_installed():
    for p in (ROOT/'src').rglob('*.py'):
        text=p.read_text(encoding='utf-8')
        assert 'from unitree_sdk2py' not in text and '.SetFsmId(' not in text and '.StopMove(' not in text


def test_one_map_tf_owner_and_mature_plugins():
    nav=yaml.safe_load((ROOT/'src/g1_nav_config/config/nav2.yaml').read_text(encoding='utf-8'))
    assert nav['controller_server']['ros__parameters']['FollowPath']['plugin']=='dwb_core::DWBLocalPlanner'
    assert nav['planner_server']['ros__parameters']['GridBased']['plugin']=='nav2_navfn_planner/NavfnPlanner'
    assert 'Spin' not in (ROOT/'src/g1_nav_config/behavior_trees/navigate.xml').read_text(encoding='utf-8')
    assert len(list((ROOT/'src/g1_nav_bringup/launch').glob('*.launch.py')))==6
