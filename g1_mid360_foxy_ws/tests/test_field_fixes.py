"""Portable regression tests. ROS API doubles test wiring, NOT DDS or hardware."""
import copy
import importlib
import json
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace as NS
import pytest
import yaml
from g1_nav_perception.core import Blocked, ReceiptClock, _strict_site as validate_site
from g1_nav_perception.settings import merge_site
from g1_nav_perception.resources import image_shape, validate_map, validate_nav, grid

ROOT = Path(__file__).resolve().parents[1]


def defaults():
    return yaml.safe_load((ROOT/'src/g1_nav_config/config/site.example.yaml').read_text())


def verified():
    s = defaults()
    for key in ('calibration', 'timing', 'filter'):
        s[key].update(verified=True, evidence_id='SYNTHETIC_TEST_ONLY')
    s['data_source'] = 'SYNTHETIC_TEST'
    s['calibration'].update(translation_xyz=[0., 0., 0.], quaternion_xyzw=[0., 0., 0., 1.])
    s['filter'].update(ground_z=-.8, ground_margin=.03, min_height=-.75, max_height=1., scan_time=.1)
    s['robot'].update(footprint_verified=True, safe_environment_confirmed=True, blind_spots_reviewed=True,
                      footprint=[[-.25, -.2], [.25, -.2], [.25, .2], [-.25, .2]])
    return s


@pytest.mark.parametrize('config', [{}, None, {'filter': {'min_height': -100}}, {'timing': {'verified': False}}])
def test_missing_fields_audit_only(config):
    s = merge_site(config, defaults())
    validate_site(s, full=False)
    assert s['live'] == {'allow_live': False, 'dry_run': True}
    assert s['data_source'] == 'REAL_SENSOR'
    with pytest.raises(Blocked, match='BLOCKED_NEEDS_CALIBRATION'):
        validate_site(s)


@pytest.mark.parametrize('config', [{'live': {'allow_live': True}}, {'live': {'dry_run': False}}, {'live': None}])
def test_default_merge_never_erases_unsafe_intent(config):
    with pytest.raises(Blocked):
        validate_site(merge_site(config, defaults()), full=False)


@pytest.mark.parametrize('value', [[], 'site', 12])
def test_bad_site_mapping_has_actionable_error(value):
    with pytest.raises(Blocked, match='SITE_INVALID'):
        merge_site(value, defaults())


def test_receive_time_is_explicit_and_does_not_verify_calibration():
    s = merge_site(yaml.safe_load((ROOT/'src/g1_nav_config/config/sensor_audit.yaml').read_text()), defaults())
    validate_site(s, full=False)
    assert s['timing']['strategy'] == 'receive_time'
    assert s['timing']['verified'] is False
    with pytest.raises(Blocked, match='CALIBRATION'):
        validate_site(s)
    s = verified()
    s['timing'].update(strategy='receive_time', receipt_time_acknowledged=True)
    validate_site(s)


@pytest.mark.parametrize('wall,mono', [(1001., 10.1), (999., 10.1), (1000.1, 9.)])
def test_receipt_clock_steps_latch_until_restart(wall, mono):
    clock = ReceiptClock(.2)
    assert clock.observe(1000., 10.)
    assert not clock.observe(wall, mono)
    assert not clock.observe(wall+.1, mono+.1)


def test_receipt_clock_normal_drift():
    clock = ReceiptClock(.2)
    for i in range(100):
        assert clock.observe(1000+i*.01, 10+i*.01)


def pgm(path, width=20, height=20):
    path.write_bytes(('P5\n# saved map\n%d %d\n255\n' % (width, height)).encode()+bytes(width*height))
    return path


def test_valid_map_and_bounded_costmap_geometry(tmp_path):
    image = pgm(tmp_path/'map.pgm')
    report = validate_map({'resolution': .05, 'origin': [0., 0., 0.]}, image)
    assert report['cells'] == 400
    nav = yaml.safe_load((ROOT/'src/g1_nav_config/config/nav2.yaml').read_text())
    assert validate_nav(nav) == {'local_costmap': 3600, 'global_costmap': 160000}


@pytest.mark.parametrize('resolution', [0, -.1, 1e-9, float('nan'), float('inf'), True, .5])
def test_unsafe_map_resolution_rejected_before_cpp(tmp_path, resolution):
    with pytest.raises(Blocked, match='RESOURCE_BOUND'):
        validate_map({'resolution': resolution, 'origin': [0., 0., 0.]}, pgm(tmp_path/'map.pgm'))


@pytest.mark.parametrize('width,height', [(50000,50000), (4097,1), (2048,2048), (0,20)])
def test_oversized_map_header_without_pixel_allocation(tmp_path, width, height):
    p = tmp_path/'bad.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',width,height)+bytes(9))
    with pytest.raises(Blocked, match='RESOURCE_BOUND'):
        image_shape(p)


@pytest.mark.parametrize('width,height,resolution', [(50000,50000,.05), (3,3,1e-10), (float('inf'),3,.05), (20,20,.02)])
def test_costmap_bounds(width, height, resolution):
    with pytest.raises(Blocked, match='RESOURCE_BOUND'):
        grid(width,height,resolution,250000,'local_costmap')


def install_modules(monkeypatch, values):
    for name, attrs in values.items():
        mod = ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def pipeline(monkeypatch):
    class Message(NS):
        FLOAT32 = 7
    class Publisher:
        def __init__(self, qos):
            self.qos, self.messages = qos, []
        def publish(self, msg):
            self.messages.append(copy.deepcopy(msg))
    class Node:
        def __init__(self, name):
            self.subs = {}
        def get_logger(self):
            return NS(info=lambda x: None, error=lambda x: None, warning=lambda x:None)
        def declare_parameter(self, name, value): pass
        def get_parameter(self, name):
            return NS(value='' if name=='time_strategy' else 'test-site')
        def create_subscription(self, cls, topic, callback, qos):
            self.subs[topic] = qos
        def create_publisher(self, cls, topic, qos):
            return Publisher(qos)
        def create_timer(self, *args):
            pass
    install_modules(monkeypatch, {
        'rclpy': {}, 'rclpy.node': {'Node': Node},
        'rclpy.qos': {'QoSProfile': Message, 'DurabilityPolicy': NS(TRANSIENT_LOCAL='transient'),
                     'ReliabilityPolicy': NS(BEST_EFFORT='best_effort', RELIABLE='reliable'), 'HistoryPolicy': NS(KEEP_LAST='keep_last')},
        'rclpy.time': {'Time': Message}, 'sensor_msgs.msg': {k:Message for k in ('PointCloud2','PointField','Imu','LaserScan')},
        'nav_msgs.msg': {'Odometry': Message}, 'std_msgs.msg': {'String': Message},
        'diagnostic_msgs.msg': {k:Message for k in ('DiagnosticArray','DiagnosticStatus','KeyValue')},
        'tf2_msgs.msg': {'TFMessage': Message}, 'tf2_ros': {'Buffer': Message, 'TransformListener': lambda *a:None}})
    name = 'g1_nav_perception.pipeline'
    monkeypatch.delitem(sys.modules, name, raising=False)
    mod = importlib.import_module(name)
    monkeypatch.setattr(mod, 'load_site', lambda _: merge_site({'timing': {'strategy':'receive_time', 'receipt_time_acknowledged': True}}, defaults()))
    monkeypatch.setattr(mod, 'time', NS(time=lambda:1000.25, monotonic=lambda:10.25))
    yield mod, mod.Pipeline()
    sys.modules.pop(name, None)


def cloud():
    return NS(header=NS(frame_id='livox_frame', stamp=NS(sec=5883, nanosec=0)),
              is_bigendian=False, height=1, width=1, point_step=12, row_step=12,
              fields=[NS(name=n, offset=i*4, count=1, datatype=7) for i,n in enumerate(('x','y','z'))],
              data=struct.pack('<fff', 1., 0., .5))


def test_callbacks_qos_and_receipt_stamp_without_raw_mutation(pipeline):
    mod, node = pipeline
    for topic in ('/utlidar/cloud_livox_mid360','/dog_odom','/utlidar/imu_livox_mid360','/scan'):
        assert node.subs[topic].reliability == 'best_effort'
        assert node.subs[topic].depth == 5
    assert node.cloud_pub.qos.reliability == 'best_effort'
    assert node.cloud_pub.qos.depth == 10
    assert node.subs['/tf_static'].durability == 'transient'
    raw = cloud()
    node.cloud(raw)
    result = node.cloud_pub.messages[-1]
    assert result.header.stamp.sec == 1000 and result.header.stamp.nanosec == 250000000
    assert raw.header.stamp.sec == 5883 and result.data == raw.data
    assert node.raw_streams['cloud'].reason == 'FUTURE_STAMP'
    assert node.streams['cloud'].reason == ''
    assert not node.obstacles.messages and not node.calibrated


@pytest.mark.parametrize('fault', ['wrong_frame','bigendian','float64','truncated','huge_width'])
def test_audit_never_forwards_malformed_cloud(pipeline, fault):
    mod, node = pipeline
    raw = cloud()
    if fault == 'wrong_frame': raw.header.frame_id = 'unknown'
    if fault == 'bigendian': raw.is_bigendian = True
    if fault == 'float64': raw.fields[0].datatype = 8
    if fault == 'truncated': raw.data = bytes(1)
    if fault == 'huge_width': raw.width = 10000000
    node.cloud(raw)
    assert not node.cloud_pub.messages
    assert node.frame_errors['cloud']


def test_host_clock_step_blocks_cloud_and_other_streams(pipeline, monkeypatch):
    mod, node = pipeline
    node.cloud(cloud())
    monkeypatch.setattr(mod, 'time', NS(time=lambda:1001.25, monotonic=lambda:10.3))
    node.cloud(cloud())
    assert len(node.cloud_pub.messages) == 1
    assert node.frame_errors['cloud'] == 'HOST_CLOCK_STEP_RESTART_REQUIRED'
    assert node.prepare('imu', cloud()) is None


def test_preserve_mode_never_replaces_invalid_stamp(pipeline):
    _, node = pipeline
    node.site['timing']['strategy'] = 'preserve'
    node.cloud(cloud())
    assert not node.cloud_pub.messages
    assert node.streams['cloud'].reason == 'FUTURE_STAMP'


@pytest.fixture
def launching(monkeypatch, tmp_path):
    class Action:
        def __init__(self, *args, **kwargs): self.args, self.kwargs = args, kwargs
    class Substitution:
        def __init__(self, name): self.name=name
        def perform(self, ctx):
            defaults={'rmw':'rmw_cyclonedds_cpp','site':str(ROOT/'src/g1_nav_config/config/site.example.yaml'), 'time_strategy':'offset','dds_config':str(ROOT/'src/g1_nav_config/config/cyclonedds.xml'), 'sdk_domain':'-1'}
            return ctx.get(self.name, defaults.get(self.name,''))
    prefix = tmp_path/'prefix'
    (prefix/'lib').mkdir(parents=True)
    (prefix/'lib/librmw_cyclonedds_cpp.so').write_bytes(b'test API double, not a real shared library')
    (prefix/'lib/librmw_fastrtps_cpp.so').write_bytes(b'test API double, not a real shared library')
    install_modules(monkeypatch, {
        'ament_index_python.packages': {'get_package_share_directory': lambda name:str(ROOT/'src'/name), 'get_package_prefix':lambda _:str(prefix)},
        'launch': {'LaunchDescription': Action},
        'launch.actions': {k:Action for k in ('DeclareLaunchArgument','OpaqueFunction','RegisterEventHandler','EmitEvent','LogInfo','SetEnvironmentVariable','RaiseError')},
        'launch.event_handlers': {'OnProcessExit':Action,'OnShutdown':Action},
        'launch.events': {'Shutdown':Action}, 'launch.substitutions': {'LaunchConfiguration':Substitution},
        'launch_ros.actions': {'Node':Action}})
    name = 'g1_nav_bringup.launching'
    monkeypatch.delitem(sys.modules,name,raising=False)
    mod=importlib.import_module(name)
    monkeypatch.setattr(mod, 'enforce_environment', lambda: {'test':'ROS API double; NOT native environment validation'})
    monkeypatch.setenv('G1_NAV_TEST_ONLY','1')
    monkeypatch.setenv('RMW_IMPLEMENTATION','rmw_cyclonedds_cpp')
    yield mod
    sys.modules.pop(name,None)


def test_explicit_fastdds_has_no_cyclone_preload_and_checks_library(launching):
    assert launching.process_environment('rmw_fastrtps_cpp')=={'RMW_IMPLEMENTATION':'rmw_fastrtps_cpp'}
    actions=launching.configure({'mode':'sensor_check','site':'','map':'','rmw':'rmw_fastrtps_cpp'})
    assert actions
    with pytest.raises(Blocked,match='RMW_UNSUPPORTED'):
        launching.configure({'mode':'sensor_check','site':'','map':'','rmw':'unknown'})


@pytest.mark.parametrize('env', [{'CONDA_PREFIX':'/opt/conda'}, {'CONDA_DEFAULT_ENV':'base'},
                               {'PYTHONHOME':'/opt/conda'}, {'PYTHONPATH':'/opt/other/lib/python3.12/site-packages'}])
def test_conda_python_contamination_blocks_before_ros(env):
    from g1_nav_perception.environment import python_errors
    assert python_errors('/usr/bin/python3',(3,8,10),env)


def test_system_python_accepts_38_and_rejects_312():
    from g1_nav_perception.environment import python_errors
    assert not python_errors('/usr/bin/python3',(3,8,10),{})
    assert python_errors('/usr/bin/python3',(3,12,0),{})


@pytest.mark.parametrize('name', ['AMENT_PREFIX_PATH','CMAKE_PREFIX_PATH','LD_LIBRARY_PATH','PYTHONPATH'])
def test_mixed_ros_distribution_overlay_is_blocked(name):
    from g1_nav_perception.environment import python_errors
    assert python_errors('/usr/bin/python3',(3,8,10),{name:'/opt/ros/foxy/lib:/opt/ros/humble/lib'})
    assert not python_errors('/usr/bin/python3',(3,8,10),{name:'/opt/ros/foxy/lib'})


def test_fastdds_diagnostic_rejects_leftover_cyclone_preload():
    from g1_nav_perception.environment import preload_errors
    assert preload_errors('rmw_fastrtps_cpp','/opt/ros/foxy/lib/librmw_cyclonedds_cpp.so')
    assert not preload_errors('rmw_fastrtps_cpp','')


def test_verified_cyclonedds_overlay_is_recorded_not_rejected():
    from g1_nav_perception.environment import dds_errors
    errors,warnings=dds_errors(['/home/unitree/cyclonedds_ws/install/lib/libddsc.so.0'],{})
    assert not errors and warnings


def test_future_file_mtime_repair_is_scoped_and_preserves_bytes(tmp_path):
    import os
    spec=importlib.util.spec_from_file_location('mtime_fix',ROOT/'scripts/fix_source_mtime.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    paths=[]
    for name in ('src/pkg/code.py','scripts/start.sh','logs/raw.json','config/site.yaml'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'untouched')
        os.utime(path,(5000.,5000.));paths.append(path)
    report=mod.fix_future(tmp_path,1000.)
    assert report['future_count']==2 and paths[0].stat().st_mtime==5000.
    assert mod.fix_future(tmp_path,1000.,apply=True)['future_count']==2
    assert paths[0].stat().st_mtime==1000. and paths[2].stat().st_mtime==5000.
    assert all(p.read_bytes()==b'untouched' for p in paths)


def test_zip_delivery_uses_safe_times_and_executable_shell_mode(tmp_path):
    import os
    import subprocess
    import zipfile
    source=tmp_path/'source';(source/'scripts').mkdir(parents=True)
    shell=source/'scripts/start.sh';shell.write_bytes(b'#!/bin/bash\ntrue\n')
    os.utime(shell,(4000000000.,4000000000.))
    output=tmp_path/'source.zip'
    subprocess.run([sys.executable,str(ROOT/'scripts/package_workspace.py'),'--source',str(source),'--output',str(output)],
                   check=True,capture_output=True)
    with zipfile.ZipFile(output) as z:
        assert all(i.date_time==(1980,1,1,0,0,0) for i in z.infolist())
        assert (z.getinfo('scripts/start.sh').external_attr>>16)&0o777==0o755


def after_preflight(actions):
    for a in actions:
        if a.args and 'on_exit' in getattr(a.args[0], 'kwargs', {}):
            cb=a.args[0].kwargs['on_exit']
            if cb.__name__=='start_stack':return cb(NS(returncode=0),NS(is_shutdown=False))
    raise AssertionError('preflight callback absent')


def test_no_argument_sensor_check_integrates_relay_scan_without_fake_tf(launching):
    actions=after_preflight(launching.configure({'mode':'sensor_check','site':'','map':''}))
    nodes=[a.kwargs for a in actions if 'executable' in a.kwargs]
    assert {n['executable'] for n in nodes} == {'pipeline','tf_authority','pointcloud_to_laserscan_node','tf_adapter','resource_watchdog'}
    scan=next(n for n in nodes if n['executable']=='pointcloud_to_laserscan_node')
    assert scan['parameters'][0]['target_frame']=='livox_frame'
    assert scan['remappings']==[('cloud_in','/g1_nav/cloud_timed'),('scan','/scan')]


def test_dryrun_downstream_uses_bounded_params_actual_frame_and_isolated_commands(launching,tmp_path):
    site=tmp_path/'site.yaml';site.write_text(yaml.safe_dump(verified()))
    image=pgm(tmp_path/'map.pgm')
    mapping=tmp_path/'map.yaml';mapping.write_text(yaml.safe_dump({'image':str(image),'resolution':.05,'origin':[0.,0.,0.],'gdps_data_source':'SYNTHETIC_TEST'}))
    actions=after_preflight(launching.configure({'mode':'dry_run','site':str(site),'map':str(mapping)}))
    downstream=[]
    for action in actions:
        if action.args and 'on_exit' in action.args[0].kwargs:
            callback=action.args[0].kwargs['on_exit']
            if callback.__name__=='admitted': downstream=callback(NS(returncode=0),NS(is_shutdown=False))
    nodes=[a.kwargs for a in downstream if 'executable' in a.kwargs]
    assert {'map_server','amcl','controller_server','planner_server','recoveries_server','bt_navigator'}.issubset({n['executable'] for n in nodes})
    controller=next(n for n in nodes if n['executable']=='controller_server')
    params=Path(controller['parameters'][0])
    try:
        nav=yaml.safe_load(params.read_text())
        assert validate_nav(nav)['local_costmap']==3600
        assert nav['amcl']['ros__parameters']['base_frame_id']=='robot_center'
        assert ('cmd_vel','/g1_nav/cmd_vel_nav2') in controller['remappings']
        assert 'base_footprint' not in params.read_text()
        for node in nodes:
            if node['executable'] not in ('lifecycle_manager','goal_adapter','waypoint_client'):
                assert node['additional_env']['RMW_IMPLEMENTATION']=='rmw_cyclonedds_cpp'
        assert 'LIVE' not in {n['executable'] for n in nodes}
    finally:
        params.unlink()


def test_unverified_site_no_longer_blocks_startup_preflight(launching):
    assert launching.configure({'mode':'dry_run','site':str(ROOT/'src/g1_nav_config/config/sensor_audit.yaml'),'map':''})


@pytest.mark.parametrize('over_budget', [True, False])
def test_resource_supervisor_only_signals_its_own_group(monkeypatch, tmp_path, over_budget):
    # Process API double: no ROS process, signal or kernel command is executed.
    install_modules(monkeypatch, {'resource': {'RLIMIT_AS':9, 'getrlimit':lambda _:(-1,-1)}})
    spec=importlib.util.spec_from_file_location('test_supervisor',ROOT/'scripts/supervise_stack.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    signals=[]
    class Process:
        pid=13579
        code=None
        calls=0
        def poll(self):
            self.calls+=1
            if not over_budget and self.calls>2:self.code=0
            return self.code
        def wait(self,timeout):return self.code
    process=Process()
    def signal_group(group,signum):
        signals.append((group,signum));process.code=0
    monkeypatch.setattr(mod,'signal_group',signal_group)
    monkeypatch.setattr(mod.signal,'signal',lambda *args:None)
    monkeypatch.setattr(mod.os,'uname',lambda:('Linux','test','fake','fake','aarch64'),raising=False)
    monkeypatch.setattr(mod.subprocess,'Popen',lambda *args,**kwargs:process)
    monkeypatch.setattr(mod.subprocess,'run',lambda *args,**kwargs:NS(returncode=1,stdout='dmesg denied'))
    monkeypatch.setattr(mod,'group_rss',lambda group:[{'pid':group,'name':'fake','rss_kib':262145 if over_budget else 100}])
    monkeypatch.setattr(mod.time,'sleep',lambda _:None)
    output=tmp_path/'resources.jsonl'
    monkeypatch.setattr(sys,'argv',['supervise_stack.py','--output',str(output),'--max-rss-mib','256','--','fake-ros2'])
    assert mod.main()==(2 if over_budget else 0)
    report=[json.loads(row) for row in output.read_text().splitlines()]
    assert report[-1]['reason']==('OWN_STACK_RSS_BUDGET_EXCEEDED' if over_budget else 'NORMAL_EXIT')
    assert signals==([(13579,mod.signal.SIGINT)] if over_budget else [])
