# Dependency evidence

Windows development host has no rclpy, colcon, unitree_sdk2py, Docker or WSL distribution. The supplied G1 historical report says Nav2 core is installed, while nav2_bringup, SLAM Toolbox and cloud-to-scan were not found. These target facts must be remeasured with preflight.sh; they are not current robot verification.

Actual native ARM64 Ubuntu 20.04/Foxy CI package versions:

| Package | Version |
|---|---|
| ros-foxy-cyclonedds | 0.7.0-1focal.20230527.034024 |
| ros-foxy-nav2-bringup | 0.4.7-1focal.20230606.055931 |
| ros-foxy-nav2-controller | 0.4.7-1focal.20230606.051342 |
| ros-foxy-nav2-dwb-controller | 0.4.7-1focal.20230606.052337 |
| ros-foxy-nav2-navfn-planner | 0.4.7-1focal.20230606.051031 |
| ros-foxy-pointcloud-to-laserscan | 2.0.0-1focal.20230606.040624 |
| ros-foxy-rmw-cyclonedds-cpp | 0.7.11-1focal.20230527.052648 |
| ros-foxy-slam-toolbox | 2.4.1-1focal.20230606.054336 |

The exact full inventory is preserved in downloaded CI artifacts. CI uses the official Foxy final snapshot; this is not evidence that the robot's current APT indexes are configured correctly. install_dependencies.sh --plan resolves only missing dependencies to exact local candidates; --install consumes the reviewed plan and refuses simulated upgrades/removals of installed packages. It does not update indexes, change ROS sources or upgrade ROS/JetPack. Pinned Foxy source fallbacks and SHA values are in third_party.lock; actual source-fallback builds on G1 remain pending. Existing installed Nav2 core must not be rebuilt unnecessarily.

Python3 NumPy is explicit for vectorized cloud transformation/cropping and the offline SVD calibration review. The ROS algorithms remain official pointcloud_to_laserscan, SLAM Toolbox, AMCL, Navfn/DWB and ObstacleLayer. No RealSense/TEB/Smac requirement or Unitree motion SDK dependency is installed by this workspace.
