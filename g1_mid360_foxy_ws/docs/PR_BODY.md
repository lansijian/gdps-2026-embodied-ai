# G1 MID-360 Foxy navigation dry-run

Adds an isolated Ubuntu 20.04 / ROS 2 Foxy colcon workspace for factory MID-360 cloud/IMU and dog_odom, with evidence-gated quaternion calibration, timestamp auditing, unique TF ownership, official pointcloud_to_laserscan, SLAM Toolbox mapping, AMCL localization and Nav2 Navfn/DWB dry-run planning. Missing physical calibration, time evidence, footprint or environment review blocks downstream startup.

The dry bridge uses the existing cooperative motion-lock convention, validates finite planar commands and conservative limits, and stops preview output on stale health/commands or near obstacles. LIVE is disabled in code: no SDK write transport, DDS publisher, FSM transition, camera driver or factory service modification is installed. Existing code and the original dirty worktree are preserved.

Validation evidence and current CI outcomes are in docs/VERIFICATION_REPORT.md. Local contracts and existing robot/navigation regressions ran on Windows; Foxy container tests are separate synthetic evidence. All actual G1/ARM64/sensor/calibration/time/map/planning and hardware acceptance remain ROBOT_VERIFICATION_PENDING. This PR is not motion authorization.
