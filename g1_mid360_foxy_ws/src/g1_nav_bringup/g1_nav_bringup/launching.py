"""Foxy launch API only. A real process exit gate controls downstream startup."""
import json
import os
from pathlib import Path
import tempfile
import yaml
from ament_index_python.packages import get_package_share_directory, get_package_prefix
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, EmitEvent, LogInfo, SetEnvironmentVariable
from launch.event_handlers import OnProcessExit, OnShutdown
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from g1_nav_perception.core import validate_site, Blocked, finite, quaternion
from g1_nav_perception.settings import read_site
from g1_nav_perception.resources import validate_map, validate_nav
from g1_nav_perception.environment import enforce as enforce_environment


def share(name, *parts):
    return str(Path(get_package_share_directory(name)).joinpath(*parts))


def process_environment(rmw):
    # Foxy rclcpp nodes with shared_ptr cycles can retain DDS receive threads
    # through process finalization. Pin the installed RMW in these processes so
    # rmw_implementation's dlclose cannot unmap it under running DDS threads.
    # No ROS/SDK files, DDS factory methods, or global environment are changed.
    library = Path(get_package_prefix(rmw))/'lib'/('lib'+rmw+'.so')
    if not library.is_file():
        raise Blocked('Installed RMW library missing: '+str(library))
    if rmw == 'rmw_fastrtps_cpp':
        return {'RMW_IMPLEMENTATION': rmw}
    preload = str(library)
    if os.environ.get('LD_PRELOAD'):
        preload += ' '+os.environ['LD_PRELOAD']
    return {'RMW_IMPLEMENTATION': rmw, 'LD_PRELOAD': preload}


def check_map(path, data_source='REAL_SENSOR'):
    p = Path(path)
    if not path or not p.is_file():
        raise Blocked('MAP_MISSING: provide a real saved occupancy map YAML')
    m = yaml.safe_load(p.read_text())
    if not isinstance(m, dict) or not isinstance(m.get('image'), str):
        raise Blocked('MAP_INVALID: YAML must contain an image path')
    if m.get('gdps_data_source', 'REAL_SENSOR') != 'REAL_SENSOR' and (
            data_source == 'REAL_SENSOR' or os.environ.get('G1_NAV_TEST_ONLY') != '1'):
        raise Blocked('SYNTHETIC_MAP_FORBIDDEN_FOR_REAL_SENSOR')
    image = Path(m['image'])
    if not image.is_absolute():
        image = p.parent/image
    if not image.is_file() or image.stat().st_size < 10:
        raise Blocked('MAP_INVALID: image/resolution/origin')
    validate_map(m, image)
    return str(p.resolve())


def truth(value):
    return str(value).lower() in ('true', '1', 'yes')


def configure(context):
    value = lambda name: LaunchConfiguration(name).perform(context)
    mode, rmw = value('mode'), value('rmw')
    if mode not in ('sensor_check', 'mapping', 'localization', 'dry_run', 'navigation'):
        raise Blocked('MODE_INVALID')
    if rmw not in ('rmw_cyclonedds_cpp', 'rmw_fastrtps_cpp'):
        raise Blocked('RMW_UNSUPPORTED')
    site_path = value('site')
    notices = []
    if not site_path or not Path(site_path).is_file():
        site_path = share('g1_nav_config', 'config', 'site.example.yaml')
        notices.append(LogInfo(msg='WARN formal site missing; example fallback remains unverified'))
    site = read_site(site_path)
    strategy = value('time_strategy')
    site['timing']['strategy'] = strategy
    validate_site(site)
    if site['data_source'] != 'REAL_SENSOR' and os.environ.get('G1_NAV_TEST_ONLY') != '1':
        raise Blocked('non-real data requires isolated G1_NAV_TEST_ONLY=1')
    report = enforce_environment()
    dds = value('dds_config')
    if rmw == 'rmw_cyclonedds_cpp' and not Path(dds).is_file():
        raise Blocked('DDS_CONFIG_MISSING: '+dds)
    nav_only, check_only = truth(value('nav2_only')), truth(value('check_only'))
    allow_live = mode == 'navigation' and truth(value('allow_live'))
    if nav_only and allow_live:
        raise Blocked('LIVE_BLOCKED_IN_NAV2_ONLY_DIAGNOSTIC')
    params = [{'use_sim_time': False, 'site': str(Path(site_path).resolve()), 'time_strategy': strategy}]
    actions = notices+[LogInfo(msg='revision=stage3 mode='+mode+' site='+site_path+' strategy='+strategy+' RMW='+rmw),
                        LogInfo(msg='ROS_ENVIRONMENT '+json.dumps(report))]
    if rmw == 'rmw_cyclonedds_cpp':
        actions.append(SetEnvironmentVariable('CYCLONEDDS_URI', 'file://'+str(Path(dds).resolve())))
    preflight_args = ['--check-only']
    if truth(value('keep_legacy')):preflight_args.append('--keep-legacy')
    preflight = Node(package='g1_nav_bringup', executable='legacy_preflight', output='screen', arguments=preflight_args)

    def start_stack(event, ctx):
        if event.returncode != 0:
            return [LogInfo(msg='LEGACY_PREFLIGHT_FAILED; no new stack started'), EmitEvent(event=Shutdown(reason='PREFLIGHT_FAILED'))]
        if check_only:
            return [LogInfo(msg='CHECK_ONLY_COMPLETE'), EmitEvent(event=Shutdown(reason='CHECK_ONLY_COMPLETE'))]
        return configured_stack(mode, site, params, strategy, rmw, nav_only, allow_live, value, ctx)
    actions.extend([RegisterEventHandler(OnProcessExit(target_action=preflight, on_exit=start_stack)), preflight])
    return actions


def configured_stack(mode, site, params, strategy, rmw, nav_only, allow_live, value, context):
    nodes = []
    critical = []
    def add(pkg, exe, **kwargs):
        node = Node(package=pkg, executable=exe, output='screen', **kwargs)
        nodes.append(node);critical.append(node)
        return node
    add('g1_nav_bringup', 'resource_watchdog', parameters=[{'standalone_health': nav_only, 'use_sim_time': False}])
    if not nav_only:
        add('g1_nav_perception', 'pipeline', parameters=params)
        add('g1_nav_tf_authority', 'tf_authority', parameters=[{'use_sim_time': False}])
        add('g1_nav_tf', 'tf_adapter', parameters=params+[{'keep_z': truth(value('keep_z'))}])
        f = site['filter']
        # Missing values never become fabricated extrinsics: only a bounded raw scan preview is possible.
        c = site['calibration']
        valid = isinstance(c.get('translation_xyz'), list) and finite(c['translation_xyz'])
        try:quaternion(c['quaternion_xyzw'])
        except (Blocked, TypeError):valid = False
        heights = [f.get('min_height'), f.get('max_height')]
        usable = valid and finite(heights) and heights[0] < heights[1]
        add('pointcloud_to_laserscan', 'pointcloud_to_laserscan_node', name='g1_nav_cloud_to_scan',
            remappings=[('cloud_in', '/g1_nav/cloud_timed'), ('scan', '/scan')],
            parameters=[{'use_sim_time': False, 'target_frame': 'robot_center' if usable else 'livox_frame',
                'transform_tolerance': .1, 'min_height': float(heights[0]) if usable else -3.,
                'max_height': float(heights[1]) if usable else 3., 'scan_time': float(f.get('scan_time') or .1),
                'range_min': float(f.get('range_min') or .15), 'range_max': min(20.,float(f.get('range_max') or 8.)),
                'angle_min': -3.141592653589793, 'angle_max': 3.141592653589793,
                'angle_increment': max(.003,float(f.get('angle_increment') or .008726646)), 'use_inf': True}])
    if mode == 'sensor_check':
        return with_failure_handlers(nodes, critical)
    downstream = []
    if mode == 'mapping':
        downstream.append(Node(package='slam_toolbox', executable='async_slam_toolbox_node', name='slam_toolbox',
            additional_env=process_environment(rmw), output='screen', parameters=[share('g1_nav_config','config','slam.yaml'),
                {'use_sim_time':False,'max_laser_range':float(site['filter']['range_max'])}]))
    else:
        map_path = check_map(value('map'), site['data_source'])
        nav = yaml.safe_load(Path(share('g1_nav_config','config','nav2.yaml')).read_text())
        validate_nav(nav)
        for cm in ('local_costmap','global_costmap'):
            config = nav[cm][cm]['ros__parameters']
            if site['robot'].get('footprint'):
                config['footprint'] = json.dumps(site['robot']['footprint'])
            else:
                config['robot_radius'] = float(site['robot'].get('provisional_radius', .4))
                nodes.append(LogInfo(msg='WARN provisional robot_radius; true footprint not certified; live health inhibited'))
            # Crop/scan already uses body coordinates; the layer's bounds run in map/odom.
            config['obstacle_layer']['max_obstacle_height'] = 10.
            config['obstacle_layer']['scan']['min_obstacle_height'] = -10.
            config['obstacle_layer']['scan']['max_obstacle_height'] = 10.
        nav['bt_navigator']['ros__parameters']['default_bt_xml_filename'] = share('g1_nav_config','behavior_trees','navigate.xml')
        nav['map_server']['ros__parameters']['yaml_filename'] = map_path
        fd, generated = tempfile.mkstemp(prefix='g1_nav_stage3_',suffix='.yaml')
        with os.fdopen(fd,'w') as stream:yaml.safe_dump(nav,stream)
        def cleanup(event,ctx):
            Path(generated).unlink(missing_ok=True);return []
        nodes.append(RegisterEventHandler(OnShutdown(on_shutdown=cleanup)))
        lifecycle = ['map_server','amcl']
        specs = [('nav2_map_server','map_server'),('nav2_amcl','amcl')]
        if mode in ('dry_run','navigation'):
            specs += [('nav2_controller','controller_server'),('nav2_planner','planner_server'),
                      ('nav2_recoveries','recoveries_server'),('nav2_bt_navigator','bt_navigator'),
                      ('nav2_waypoint_follower','waypoint_follower')]
            lifecycle += [exe for _,exe in specs[2:]]
        for pkg,exe in specs:
            remaps = [('odom','/g1_nav/odom')]
            if exe == 'controller_server':remaps.append(('cmd_vel','/g1_nav/cmd_vel_nav2'))
            if exe == 'recoveries_server':remaps.append(('cmd_vel','/g1_nav/recovery_cmd_vel_disabled'))
            downstream.append(Node(package=pkg, executable=exe, name=exe, output='screen',parameters=[generated],
                                   remappings=remaps, additional_env=process_environment(rmw)))
        downstream.append(Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
            name='lifecycle_manager_navigation', output='screen', parameters=[{'use_sim_time':False,'autostart':True,'node_names':lifecycle}]))
        if mode in ('dry_run','navigation') and not nav_only:
            add('g1_nav_bridge','velocity_smoother',parameters=params)
            add('g1_nav_bridge','dry_bridge',parameters=params+[{'allow_live':allow_live,'dry_run':not allow_live,
                'legacy':truth(value('legacy')),'sdk_interface':value('sdk_interface'),'sdk_domain':int(value('sdk_domain'))}])
            downstream.append(Node(package='g1_nav_bringup',executable='goal_adapter',output='screen'))
            if value('waypoints_file'):
                downstream.append(Node(package='g1_nav_bringup',executable='waypoint_client',output='screen',
                    parameters=[{'waypoints_file':value('waypoints_file'),'loop':truth(value('loop'))}]))
    critical += downstream
    if nav_only:
        nodes += downstream
    else:
        gate = Node(package='g1_nav_perception',executable='runtime_preflight',output='screen',
            parameters=[{'duration_s':30.,'timeout_s':60.,'basic_only':mode=='mapping',
                         'minimum_cloud_hz':float(site['diagnostics']['minimum_cloud_hz']),
                         'minimum_odom_hz':float(site['diagnostics']['minimum_odom_hz'])}])
        def admitted(event,ctx):
            if event.returncode != 0:
                return [LogInfo(msg='SENSOR_GATE_FAILED'),EmitEvent(event=Shutdown(reason='SENSOR_GATE_FAILED'))]
            return downstream
        nodes.extend([RegisterEventHandler(OnProcessExit(target_action=gate,on_exit=admitted)),gate])
    return with_failure_handlers(nodes,critical)


def with_failure_handlers(actions,critical):
    def failed(event,context):
        if not context.is_shutdown:
            return [LogInfo(msg='COMPONENT_EXIT code='+str(event.returncode)),EmitEvent(event=Shutdown(reason='COMPONENT_EXIT'))]
        return []
    return [RegisterEventHandler(OnProcessExit(target_action=node,on_exit=failed)) for node in critical]+actions


def description(default_mode='dry_run'):
    defaults = {'mode':default_mode,'rmw':os.environ.get('G1_NAV_RMW',os.environ.get('RMW_IMPLEMENTATION','rmw_cyclonedds_cpp')),
        'site':os.environ.get('G1_NAV_SITE',share('g1_nav_config','config','site.g1_default.yaml')),
        'dds_config':os.environ.get('G1_NAV_DDS_CONFIG',share('g1_nav_config','config','cyclonedds.xml')),
        'time_strategy':'offset','map':'','keep_legacy':'false','check_only':'false','nav2_only':'false',
        'keep_z':'false','allow_live':'false','legacy':'false','sdk_interface':'','sdk_domain':'-1',
        'waypoints_file':'','loop':'false'}
    return LaunchDescription([DeclareLaunchArgument(key,default_value=value) for key,value in defaults.items()]+
        [SetEnvironmentVariable('RMW_IMPLEMENTATION',LaunchConfiguration('rmw')),OpaqueFunction(function=configure)])
