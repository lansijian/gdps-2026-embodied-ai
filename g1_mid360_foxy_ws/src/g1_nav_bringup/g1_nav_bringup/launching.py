"""Foxy launch API only. A real process exit gate controls downstream startup."""
import json
import os
from pathlib import Path
import tempfile
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, EmitEvent, LogInfo
from launch.event_handlers import OnProcessExit, OnShutdown
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from g1_nav_perception.core import validate_site, Blocked


def share(name, *parts):
    return str(Path(get_package_share_directory(name)).joinpath(*parts))


def check_map(path):
    p = Path(path)
    if not path or not p.is_file():
        raise Blocked('MAP_MISSING: provide a real saved occupancy map YAML')
    m = yaml.safe_load(p.read_text())
    image = Path(m['image'])
    if not image.is_absolute():
        image = p.parent/image
    if not image.is_file() or image.stat().st_size < 10 or m['resolution'] <= 0 or len(m['origin']) != 3:
        raise Blocked('MAP_INVALID: image/resolution/origin')
    return str(p.resolve())


def configure(context):
    mode = LaunchConfiguration('mode').perform(context)
    if mode not in ('sensor_check', 'mapping', 'localization', 'dry_run'):
        raise Blocked('LIVE_DISABLED: mode must be sensor_check|mapping|localization|dry_run')
    site_path = LaunchConfiguration('site').perform(context)
    if not site_path or not Path(site_path).is_file():
        raise Blocked('SITE_MISSING: copy site.example.yaml; unknown extrinsics remain BLOCKED')
    site = yaml.safe_load(Path(site_path).read_text())
    validate_site(site, full=mode != 'sensor_check')
    if mode != 'sensor_check' and site['data_source'] != 'REAL_SENSOR' and os.environ.get('G1_NAV_TEST_ONLY') != '1':
        raise Blocked('non-real data requires isolated G1_NAV_TEST_ONLY=1')
    map_path = check_map(LaunchConfiguration('map').perform(context)) if mode in ('localization', 'dry_run') else ''
    parameters = [{'use_sim_time': False, 'site': str(Path(site_path).resolve())}]
    actions = [Node(package='g1_nav_perception', executable='pipeline', output='screen', parameters=parameters),
               Node(package='g1_nav_tf_authority', executable='tf_authority', output='screen', parameters=[{'use_sim_time': False}])]
    valid = True
    try:
        validate_site(site)
    except (Blocked, TypeError, KeyError) as exc:
        valid = False
        actions.append(LogInfo(msg='Sensor audit only: '+str(exc)))
    if valid:
        actions.append(Node(package='g1_nav_tf', executable='tf_adapter', parameters=parameters, output='screen'))
        f = site['filter']
        actions.append(Node(package='pointcloud_to_laserscan', executable='pointcloud_to_laserscan_node',
            name='g1_nav_cloud_to_scan', output='screen',
            remappings=[('cloud_in', '/g1_nav/cloud_timed'), ('scan', '/scan')],
            parameters=[{'use_sim_time': False, 'target_frame': 'robot_center',
                'transform_tolerance': .1, 'min_height': float(f['min_height']), 'max_height': float(f['max_height']),
                'scan_time': float(f['scan_time']), 'range_min': float(f['range_min']), 'range_max': float(f['range_max']),
                'angle_min': -3.141592653589793, 'angle_max': 3.141592653589793,
                'angle_increment': float(f['angle_increment']), 'use_inf': True}]))
    if mode == 'sensor_check':
        return actions
    actions.append(Node(package='g1_nav_bridge', executable='dry_bridge', output='screen',
                        parameters=parameters+[{'allow_live': False, 'dry_run': True}]))
    gate = Node(package='g1_nav_perception', executable='runtime_preflight', output='screen',
                parameters=[{'use_sim_time': False, 'duration_s': 30., 'timeout_s': 60.,
                             'minimum_cloud_hz': float(site['diagnostics']['minimum_cloud_hz']),
                             'minimum_odom_hz': float(site['diagnostics']['minimum_odom_hz'])}])
    nav = yaml.safe_load(Path(share('g1_nav_config', 'config', 'nav2.yaml')).read_text())
    for cm in ('local_costmap', 'global_costmap'):
        nav[cm][cm]['ros__parameters']['footprint'] = json.dumps(site['robot']['footprint'])
        nav[cm][cm]['ros__parameters']['obstacle_layer']['cloud']['min_obstacle_height'] = float(site['filter']['min_height'])
        nav[cm][cm]['ros__parameters']['obstacle_layer']['cloud']['max_obstacle_height'] = float(site['filter']['max_height'])
    nav['bt_navigator']['ros__parameters']['default_bt_xml_filename'] = share('g1_nav_config', 'behavior_trees', 'navigate.xml')
    nav['map_server']['ros__parameters']['yaml_filename'] = map_path
    handle, generated = tempfile.mkstemp(prefix='g1_nav_', suffix='.yaml')
    with os.fdopen(handle, 'w') as out:
        yaml.safe_dump(nav, out)
    def cleanup(event, ctx):
        Path(generated).unlink(missing_ok=True)
        return []
    actions.append(RegisterEventHandler(OnShutdown(on_shutdown=cleanup)))
    downstream = []
    if mode == 'mapping':
        downstream.append(Node(package='slam_toolbox', executable='async_slam_toolbox_node',
            name='slam_toolbox', output='screen', parameters=[share('g1_nav_config', 'config', 'slam.yaml'), {'use_sim_time': False}]))
    else:
        for pkg, exe, name in (('nav2_map_server', 'map_server', 'map_server'), ('nav2_amcl', 'amcl', 'amcl')):
            downstream.append(Node(package=pkg, executable=exe, name=name, output='screen', parameters=[generated]))
        downstream.append(Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
            name='lifecycle_manager_localization', output='screen', parameters=[{'use_sim_time': False,
                'autostart': True, 'node_names': ['map_server', 'amcl']}]))
        if mode == 'dry_run':
            nodes = [('nav2_controller', 'controller_server'), ('nav2_planner', 'planner_server'),
                     ('nav2_recoveries', 'recoveries_server'), ('nav2_bt_navigator', 'bt_navigator')]
            for pkg, exe in nodes:
                remaps = [('odom', '/g1_nav/odom')]
                if exe == 'recoveries_server':
                    remaps.append(('cmd_vel', '/g1_nav/recovery_cmd_vel_disabled'))
                downstream.append(Node(package=pkg, executable=exe, name=exe, output='screen',
                                       parameters=[generated], remappings=remaps))
            downstream.append(Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
                name='lifecycle_manager_navigation', output='screen', parameters=[{'use_sim_time': False,
                    'autostart': True, 'node_names': [n for _, n in nodes]}]))
    def after_gate(event, ctx):
        if event.returncode != 0:
            return [LogInfo(msg='Sensor/TF/time gate failed; downstream inhibited'),
                    EmitEvent(event=Shutdown(reason='PREFLIGHT_FAILED'))]
        return downstream
    actions.extend([RegisterEventHandler(OnProcessExit(target_action=gate, on_exit=after_gate)), gate])
    return actions


def description(default_mode='dry_run'):
    return LaunchDescription([DeclareLaunchArgument('mode', default_value=default_mode),
        DeclareLaunchArgument('site', default_value=os.environ.get('G1_NAV_SITE', '')),
        DeclareLaunchArgument('map', default_value=''), OpaqueFunction(function=configure)])
