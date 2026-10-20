"""Stage 3 contracts, synthetic values only; no real SDK/robot is imported."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import pytest
import yaml
from test_field_fixes import pipeline, launching, after_preflight, verified, defaults, install_modules
from g1_nav_perception.core import OffsetCalibrator, Blocked, validate_site, site_warnings, ReceiptClock


@pytest.mark.parametrize('bias', [69.8, 4883., -123.4])
def test_offset_uses_ten_frame_median_withholds_all_ten_then_preserves_deltas(bias):
    clock=OffsetCalibrator(10.)
    for i in range(10):
        assert clock.observe(10000+i*.1-bias,10000+i*.1,10+i*.1) is None
    assert clock.offset==pytest.approx(bias)
    assert clock.observe(10001.1-bias,10001.1,11.1)==pytest.approx(10001.1)
    assert clock.observe(10001.2-bias,10001.2,11.2)==pytest.approx(10001.2)


def test_offset_outliers_do_not_change_initial_median_and_rolling_jitter_visible():
    clock=OffsetCalibrator(0.)
    for i in range(10):clock.observe(100+i*.1,110+i*.1+(1 if i==0 else 0),i*.1)
    assert clock.offset==pytest.approx(10.)
    for i in range(10,41):clock.observe(100+i*.1,110+i*.1+(.1 if i==40 else 0),i*.1)
    assert clock.jitter>.05 and clock.offset==pytest.approx(10.)


def test_offset_no_frames_expires_and_late_tenth_frame_fails():
    clock=OffsetCalibrator(0.)
    assert clock.expired(30.)
    for i in range(9):clock.observe(100+i,110+i,i)
    with pytest.raises(Blocked,match='OFFSET_CALIBRATION_TIMEOUT'):clock.observe(130,140,30.)


def test_stage3_unknown_calibration_warns_but_unsafe_speed_blocks():
    site=defaults();validate_site(site)
    assert site_warnings(site)
    site['limits']['vx']=.2
    with pytest.raises(Blocked,match='unsafe command limits'):validate_site(site)


def test_pipeline_offset_corrects_before_time_health_and_never_mutates_raw(pipeline,monkeypatch):
    mod,node=pipeline;node.site['timing']['strategy']='offset'
    node.offsets['cloud']=OffsetCalibrator(0.)
    for i in range(10):
        monkeypatch.setattr(mod,'time',NS(time=lambda i=i:1000.+i*.1,monotonic=lambda i=i:1.+i*.1))
        raw=NS(header=NS(stamp=NS(sec=900,nanosec=i*100000000)))
        assert node.prepare('cloud',raw) is None
    monkeypatch.setattr(mod,'time',NS(time=lambda:1001.1,monotonic=lambda:2.1))
    raw=NS(header=NS(stamp=NS(sec=901,nanosec=100000000)))
    out=node.prepare('cloud',raw)
    assert out.header.stamp.sec==1001 and raw.header.stamp.sec==901
    assert node.raw_streams['cloud'].reason=='STALE_STAMP'


@pytest.mark.parametrize('keep_z,expected', [(False,0.),(True,.735)])
def test_tf_direct_odom_projection_quaternion_and_100hz_bound(pipeline,monkeypatch,keep_z,expected):
    mod,node=pipeline
    def transform():return NS(header=NS(stamp=NS(sec=0,nanosec=0)),transform=NS(translation=NS(x=0.,y=0.,z=0.),rotation=None))
    install_modules(monkeypatch,{'geometry_msgs.msg':{'TransformStamped':transform},'tf2_ros':{'StaticTransformBroadcaster':NS,'TransformBroadcaster':NS}})
    monkeypatch.setitem(sys.modules,'g1_nav_perception.pipeline',mod)
    monkeypatch.delitem(sys.modules,'g1_nav_tf.adapter',raising=False)
    adapter=importlib.import_module('g1_nav_tf.adapter')
    obj=adapter.Adapter.__new__(adapter.Adapter)
    obj.strategy='preserve';obj.last_publish=0.;sent=[]
    obj.dynamic=NS(sendTransform=lambda t:sent.append(t))
    obj.get_parameter=lambda _:NS(value=keep_z)
    monkeypatch.setattr(adapter,'time',NS(time=lambda:1000.1,monotonic=lambda:10.))
    message=NS(header=NS(frame_id='odom',stamp=NS(sec=1000,nanosec=0)),child_frame_id='robot_center',
               pose=NS(pose=NS(position=NS(x=1.,y=2.,z=.735),orientation=NS(x=0.,y=0.,z=0.,w=1.))))
    obj.odom(message);obj.odom(message)
    assert len(sent)==1 and sent[0].child_frame_id=='robot_center'
    assert sent[0].transform.translation.z==expected and message.pose.pose.position.z==.735
    assert sent[0].transform.rotation.w==1.
    sys.modules.pop('g1_nav_tf.adapter',None)


@pytest.mark.parametrize('argv,expected', [
    (['/opt/ros/foxy/lib/nav2_planner/planner_server'],True),
    (['/usr/bin/python3','/old/install/g1_nav_perception/lib/g1_nav_perception/pipeline'],True),
    (['ros2','launch','nav2_bringup','navigation_launch.py'],True),
    (['unitree_driver','_CREATED_BY_BARE_DDS_APP_'],False),
    (['/usr/bin/python3','factory_livox_driver.py'],False),
    (['/usr/bin/python3','tests/ros_fixture.py'],False)])
def test_cleanup_matches_legacy_navigation_not_factory_or_fixtures(pipeline,monkeypatch,argv,expected):
    monkeypatch.delitem(sys.modules,'g1_nav_bringup.preflight',raising=False)
    module=importlib.import_module('g1_nav_bringup.preflight')
    assert module.legacy_command(argv) is expected
    sys.modules.pop('g1_nav_bringup.preflight',None)


def test_watchdog_kills_only_overbudget_descendant_and_reports_topics(pipeline,monkeypatch,tmp_path):
    monkeypatch.delitem(sys.modules,'g1_nav_bringup.watchdog',raising=False)
    module=importlib.import_module('g1_nav_bringup.watchdog')
    module_node=module.Watchdog.__new__(module.Watchdog)
    module_node.root=123;module_node.errors=[];module_node.log=tmp_path/'resource.jsonl';module_node.health=None
    published=[];killed=[]
    module_node.pub=NS(publish=lambda m:published.append(json.loads(m.data)))
    module_node.get_topic_names_and_types=lambda:[('/plan',['nav_msgs/msg/Path'])]
    module_node.get_publishers_info_by_topic=lambda _: [NS(node_name='planner_server')]
    monkeypatch.setattr(module,'processes',lambda root:[{'pid':7654,'name':'planner_server','rss_kib':4194305,'command':'planner_server'}])
    monkeypatch.setattr(module.os,'kill',lambda pid,sig:killed.append(pid))
    module_node.tick()
    assert killed==[7654] and published[-1]['errors']==['RSS_ERROR_PID_7654']
    assert published[-1]['processes'][0]['published_topics']=={'/plan':['planner_server']}
    sys.modules.pop('g1_nav_bringup.watchdog',None)


def test_real_backend_rejects_missing_permissions_before_any_import(monkeypatch):
    from g1_nav_bridge.live_backend import LocoBackend
    with pytest.raises(ValueError):LocoBackend('',-1)


def test_real_backend_only_short_velocity_lease_no_fsm(monkeypatch):
    from g1_nav_bridge import live_backend
    calls=[]
    client=NS(SetTimeout=lambda x:calls.append(('timeout',x)),Init=lambda:calls.append(('init',)),
              SetVelocity=lambda *v:(calls.append(('velocity',v)) or 0))
    def load(name):
        if name.endswith('channel'):return NS(ChannelFactoryInitialize=lambda *v:calls.append(('channel',v)))
        return NS(LocoClient=lambda:client)
    monkeypatch.setattr(live_backend.importlib,'import_module',load)
    backend=live_backend.LocoBackend('EXPLICIT_TEST_INTERFACE',0)
    backend.send((.05,0.,.1))
    assert calls[-1]==('velocity',(.05,0.,.1,.1))
    with pytest.raises(ValueError):backend.send((1.,0.,0.))
    assert not any('fsm' in str(call).lower() for call in calls)


def test_stage3_default_xml_and_rviz_have_no_cloud_fanout():
    root=Path(__file__).resolve().parents[1]
    xml=(root/'src/g1_nav_config/config/cyclonedds.xml').read_text()
    assert '<WhcHigh>2MB</WhcHigh>' in xml and '<MinimumSocketReceiveBufferSize>30MB' in xml
    nav=yaml.safe_load((root/'src/g1_nav_config/config/nav2.yaml').read_text())
    assert nav['controller_server']['ros__parameters']['controller_frequency']>=20
    for cm in ('local_costmap','global_costmap'):
        layer=nav[cm][cm]['ros__parameters']['obstacle_layer']
        assert layer['observation_sources']=='scan' and layer['scan']['marking'] and layer['scan']['clearing']
    for p in (root/'src/g1_nav_config/rviz').glob('*.rviz'):
        assert 'PointCloud2' not in p.read_text()


def test_nav2_only_has_no_perception_slam_bridge_and_check_only_never_starts_them(launching,tmp_path):
    image=tmp_path/'map.pgm';image.write_bytes(b'P5\n20 20\n255\n'+bytes(400))
    mapping=tmp_path/'map.yaml';mapping.write_text(yaml.safe_dump({'image':str(image),'resolution':.05,'origin':[0.,0.,0.]}))
    actions=after_preflight(launching.configure({'mode':'dry_run','site':'','map':str(mapping),'nav2_only':'true'}))
    names={a.kwargs.get('executable') for a in actions}
    assert 'planner_server' in names and 'pipeline' not in names and 'dry_bridge' not in names
    actions=after_preflight(launching.configure({'mode':'sensor_check','site':'','map':'','check_only':'true'}))
    assert not any('executable' in a.kwargs for a in actions)


@pytest.mark.parametrize('cap,changed', [(1048576,True),(67108864,False)])
def test_dds_kernel_buffer_cap_is_explicit_and_template_unchanged(tmp_path,cap,changed):
    from g1_nav_perception.dds_profile import prepare
    source=Path(__file__).resolve().parents[1]/'src/g1_nav_config/config/cyclonedds.xml'
    before=source.read_bytes();output=tmp_path/'effective.xml'
    report=prepare(source,cap=cap,output=output)
    assert source.read_bytes()==before
    assert bool(report['warnings']) is changed
    assert report['applied_receive_minimum_bytes']==min(cap,30*1024*1024)
    if changed:
        assert '<WhcHigh>2MB</WhcHigh>' in output.read_text()
        assert output.with_suffix('.json').is_file()


def test_failed_legacy_cleanup_prevents_any_new_node_construction(launching,monkeypatch):
    monkeypatch.setattr(launching,'run_preflight',lambda *args:2)
    with pytest.raises(Blocked,match='LEGACY_PREFLIGHT_FAILED'):
        launching.configure({'mode':'sensor_check','site':'','map':''})


@pytest.fixture
def bridge_module(pipeline,monkeypatch):
    install_modules(monkeypatch,{'geometry_msgs.msg':{'Twist':NS,'TwistStamped':NS}})
    monkeypatch.delitem(sys.modules,'g1_nav_bridge.bridge',raising=False)
    module=importlib.import_module('g1_nav_bridge.bridge')
    yield module
    sys.modules.pop('g1_nav_bridge.bridge',None)


def test_sdk_worker_never_executes_nonzero_after_delayed_initialization(bridge_module,monkeypatch):
    module=bridge_module;node=module.Bridge.__new__(module.Bridge);sent=[]
    node.backend=NS(send=lambda velocity:sent.append(velocity));node.sdk_error='';node.permit_rpc=True
    monkeypatch.setattr(module,'time',NS(monotonic=lambda:20.))
    node.rpc((.1,0.,.1),deadline=10.)
    assert sent==[(0.,0.,0.)]


def test_dry_bridge_cleanup_does_not_shutdown_reserved_ros_executor(bridge_module,monkeypatch):
    module=bridge_module;node=module.Bridge.__new__(module.Bridge);released=[]
    node.sdk_pool=None;node.permit_rpc=True
    def forbidden(*args,**kwargs):raise AssertionError('must not call ROS executor as a thread pool')
    node.executor=NS(shutdown=forbidden)
    node.lock=NS(release=lambda:released.append(True))
    monkeypatch.setattr(module.Node,'destroy_node',lambda self:None,raising=False)
    node.destroy_node()
    assert released==[True] and node.permit_rpc is False


def test_stamped_bridge_rejects_other_frame_and_old_commands(bridge_module,monkeypatch):
    module=bridge_module;node=module.Bridge.__new__(module.Bridge);node.gate=NS(last_cmd='old')
    monkeypatch.setattr(module,'time',NS(time=lambda:1000.,monotonic=lambda:10.))
    node.command(NS(header=NS(frame_id='map',stamp=NS(sec=1000,nanosec=0))))
    assert node.gate.last_cmd is None

    node.gate.last_cmd='old'
    node.command(NS(header=NS(frame_id='robot_center',stamp=NS(sec=999,nanosec=0))))
    assert node.gate.last_cmd is None


def test_motion_lock_is_held_until_pending_sdk_call_finishes(bridge_module,monkeypatch):
    module=bridge_module;node=module.Bridge.__new__(module.Bridge);released=[];callbacks=[]
    node.sdk_pool=NS(shutdown=lambda **kw:None);node.permit_rpc=True
    node.future=NS(done=lambda:False,add_done_callback=lambda cb:callbacks.append(cb))
    node.lock=NS(release=lambda:released.append(True))
    monkeypatch.setattr(module.Node,'destroy_node',lambda self:None,raising=False)
    node.destroy_node()
    assert not released
    callbacks[0](None)
    assert released==[True]


def test_formal_site_and_top_level_time_strategy_are_used(launching):
    root=Path(__file__).resolve().parents[1]
    site=launching.read_site(root/'config/site.g1_default.yaml')
    assert site['time_strategy']==site['timing']['strategy']=='offset'
    assert (root/'config/site.g1_default.yaml').read_bytes()==(root/'src/g1_nav_config/config/site.g1_default.yaml').read_bytes()
    assert site['calibration']['quaternion_xyzw']==[0.,1.,0.,0.]
    assert site['calibration']['verified'] is False
