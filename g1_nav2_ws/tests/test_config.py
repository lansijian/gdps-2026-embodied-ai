"""Config and launch-wiring checks: pure text/YAML parsing, no ROS runtime required."""
import os
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(relative):
    with open(os.path.join(ROOT, relative), encoding='utf-8') as stream:
        return stream.read()


class Nav2Params(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params = yaml.safe_load(read('src/g1_nav_bringup/config/nav2_params.yaml'))

    def test_global_costmap_has_no_obstacle_layer(self):
        ros_params = self.params['global_costmap']['global_costmap']['ros__parameters']
        self.assertEqual(ros_params['plugins'], ['static_layer', 'inflation_layer'])
        self.assertNotIn('obstacle_layer', ros_params)
        self.assertNotIn('voxel_layer', ros_params)

    def test_local_costmap_marks_and_clears_scan(self):
        ros_params = self.params['local_costmap']['local_costmap']['ros__parameters']
        self.assertIn('voxel_layer', ros_params['plugins'])
        self.assertIn('inflation_layer', ros_params['plugins'])
        voxel = ros_params['voxel_layer']
        self.assertEqual(voxel['observation_sources'], 'scan')
        scan = voxel['scan']
        self.assertEqual(scan['data_type'], 'LaserScan')
        self.assertEqual(scan['topic'], '/scan')
        self.assertTrue(scan['marking'])
        self.assertTrue(scan['clearing'])

    def test_controller_commands_no_lateral_motion(self):
        follow_path = self.params['controller_server']['ros__parameters']['FollowPath']
        self.assertEqual(follow_path['max_vel_y'], 0.0)
        self.assertEqual(follow_path['acc_lim_y'], 0.0)


class LaunchForwarding(unittest.TestCase):
    def test_nav_bringup_forwards_to_mapping(self):
        text = read('src/g1_nav_bringup/launch/nav_bringup.launch.py')
        self.assertIn('mapping.launch.py', text)
        self.assertIn('launch_arguments=', text)
        for key in ('odom_topic', 'use_native_odom', 'lidar_qx', 'scan_min_height'):
            self.assertIn(key, text)

    def test_mapping_forwards_to_sensing(self):
        text = read('src/g1_nav_bringup/launch/mapping.launch.py')
        self.assertIn('sensing.launch.py', text)
        self.assertIn('launch_arguments=', text)
        for key in ('odom_topic', 'use_native_odom', 'lidar_qx', 'scan_min_height'):
            self.assertIn(key, text)

    def test_sensing_rewrites_scan_window_and_publishes_static_tf(self):
        text = read('src/g1_nav_bringup/launch/sensing.launch.py')
        for key in ('scan_min_height', 'scan_max_height', 'min_height', 'max_height',
                    'static_transform_publisher', 'lidar_qx'):
            self.assertIn(key, text)

    def test_odom_bridge_is_console_script_not_execute_process(self):
        setup_py = read('src/g1_nav_bringup/setup.py')
        self.assertIn('odom_bridge = g1_nav_bringup.odom_bridge:main', setup_py)
        for launch in ('mapping.launch.py', 'nav_bringup.launch.py'):
            text = read('src/g1_nav_bringup/launch/' + launch)
            self.assertNotIn('ExecuteProcess', text)
            self.assertIn("executable='odom_bridge'", text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
