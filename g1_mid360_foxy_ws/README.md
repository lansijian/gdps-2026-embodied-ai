# G1 MID-360 / ROS 2 Foxy dry-run workspace

Target: Ubuntu 20.04 ARM64, Python 3.8, ROS 2 Foxy, CycloneDDS. LIVE is DISABLED in code: no Unitree SDK import, Unitree DDS motion writer, FSM or motion service is installed. /g1_nav/cmd_vel_safe is a preview topic, never a hardware command.

Read docs/DEPLOY_FOXY_ARM64.md before use. Unknown calibration/timing/footprint/environment defaults block downstream. This is a navigation engineering candidate, not a hardware safety certification. Real robot validation is pending.

| Package | Responsibility |
|---|---|
| g1_nav_bringup | Five integrated launch entry points; sensor preflight process gates downstream |
| g1_nav_perception | Raw timestamp/QoS audit, preserve-only normalized streams, calibrated cloud filtering, scan/TF/data health and diagnostics |
| g1_nav_tf | Measured dog_odom to dynamic TF and verified quaternion sensor TF |
| g1_nav_tf_authority | Foxy rclcpp duplicate GID/parent/cycle audit |
| g1_nav_bridge | Shared exclusive motion lock, finite/bounds checks, acceleration/timeout gate, SDK-free preview |
| g1_nav_config | Foxy Navfn/DWB, SLAM, AMCL, site template, BT, RViz |
| g1_ros2_bridge | Reviewed upstream 29-joint metadata only; all unsafe launch/DDS/motion paths excluded |

Data: factory cloud -> timestamp/frame gate -> cloud_timed -> official pointcloud_to_laserscan(target_frame=robot_center) -> /scan. Separately calibrated XYZ -> height filter -> cloud_obstacles -> Nav2 ObstacleLayer. dog_odom -> stamp/pose gate -> /g1_nav/odom -> TF odom->robot_center. The single map->odom owner is SLAM in mapping or AMCL in localization/dry_run. No static map->odom exists.

The pipeline keeps an active scan subscriber, emits /g1_nav/health and /diagnostics at 10 Hz, including frequency/offset P95, ordering/jumps, finite scan ratio, TF authority and cloud retention. The independent dry bridge's 20 Hz timer fails to zero on health/command timeout. There is no SDK worker that could block the timer. This does not implement the independent physical emergency stop needed for LIVE.

Local tests: python -m pytest tests/test_contracts.py tests/test_scripts.py -q. Foxy integration: isolated ROS_DOMAIN_ID=87 G1_NAV_TEST_ONLY=1 python3 tests/ros_integration.py after building/sourcing; SYNTHETIC_TEST only. Never run fixtures in a robot domain.
