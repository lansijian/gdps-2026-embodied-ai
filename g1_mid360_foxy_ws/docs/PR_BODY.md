Historical baseline PR draft only. Field fix r2 is local-only; do not publish this stale draft. See FIELD_FIX_R2.md.

# G1 MID-360 Foxy navigation dry-run

Adds an isolated Ubuntu 20.04 / ROS 2 Foxy colcon workspace for factory MID-360 cloud/IMU and dog_odom, with evidence-gated quaternion calibration, timestamp auditing, unique TF ownership, official pointcloud_to_laserscan, SLAM Toolbox mapping, AMCL localization and Nav2 Navfn/DWB dry-run planning. Missing physical calibration, time evidence, footprint or environment review blocks downstream startup.

The dry bridge uses the existing cooperative motion-lock convention, validates finite planar commands and conservative limits, and stops preview output on stale health/commands or near obstacles. LIVE is disabled in code: no SDK write transport, DDS publisher, FSM transition, camera driver or factory service modification is installed. Existing code and the original dirty worktree are preserved.

Validation evidence and current CI outcomes are in docs/VERIFICATION_REPORT.md. Local contracts and existing robot/navigation regressions ran on Windows; Foxy container tests are separate synthetic evidence. All actual G1/ARM64/sensor/calibration/time/map/planning and hardware acceptance remain ROBOT_VERIFICATION_PENDING. This PR is not motion authorization.

Final validation: Windows 54 new tests plus 104 existing regressions passed. Native ARM64 and x86_64 Ubuntu 20.04/Foxy CI each passed 54 unit/script tests, 3 launch rejection checks and 27 ROS integration checks, built all 7 packages and discovered all 5 launch entries. Synthetic representative load uses 20,064 points with 32-byte stride at 10Hz and configured 800Hz odom/200Hz IMU. Runtime SDK write calls remain zero; strict clean shutdown assertions also pass. Evidence: https://github.com/lansijian/gdps-2026-embodied-ai/actions/runs/39376281980 .
