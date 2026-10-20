> Historical baseline snapshot. Stage 3 current facts and outcomes are STAGE3_SPEC.md / VERIFICATION_REPORT.md.

# Evidence baseline - 2026-10-20

Target facts in EXECUTION_SPEC.md are user-supplied field observations, not revalidated by this Windows session.

- Correct origin: https://github.com/lansijian/gdps-2026-embodied-ai.git
- Remote main: 8974a103d2ea914e5b6230bbfaa32bbb45ca3598 (git ls-remote verified).
- Original checkout: E:/GDPS/competition at c4ff94b, branch codex/g1-field-baseline-stage2-20261017.
- Original dirty files: deleted tomorrow_field_checklist.md; untracked task spec, GDPS_G1_20261017_Field_Baseline_Codex_Offline/, docs/handover/field-deploy-freeze-4d74365.md, local bridge ZIP. Preserved.
- Separate existing main worktree dist/two-level-merge-20261018/checkout is not edited. Stage 3 historical state is not this project's baseline.
- New isolated checkout: dist/g1-mid360-foxy-20261020, branch codex/g1-mid360-foxy-dryrun-20261020, based on origin/main.
- Local runtime: Windows, Python 3.11.4; pytest/PyYAML available. rclpy, unitree_sdk2py, Docker, colcon and gh CLI unavailable. WSL executable exists but no distro installed. Git Bash available for shell syntax checks.
- No robot address, robot session, real bag or measured calibration supplied. No robot SSH attempted. ROBOT_VERIFICATION_PENDING.

## Third party review
ZIP SHA256: 1D09F2B5667949A31A84F212692F12F86356C1AB3ECB6E526DF28661D16BDD19.
Extracted locally into ignored external/unitree_g1_ros2-main with COLCON_IGNORE. ZIP has no Git commit identity and no standalone LICENSE. package.xml declares BSD-3-Clause. Upstream observed main 6ce74366553cca3dc7d8f5b46f155ed66d11f384 is not assumed to identify ZIP.

Only unchanged pure joint_names.py is installed as safe g1_ros2_bridge metadata; 29 unique names tested. DDS monkey-patching uses private SDK fields and newer Interfaces XML: excluded. cmd_vel_bridge defaults dry_run=false, 0.6/0.4/0.6 limits, Move/StopMove writes: excluded. loco FSM services, camera, low-level state bridge, robot.launch.py: excluded. Upstream odom converts SportModeState into base_link and restamps receive time; incompatible with known dog_odom/robot_center: excluded. URDF livox_joint uses rpy="3.141561 0 0", parent mid360_link; this is an unverified candidate, not the target's measured transform. No meshes/URDF or upstream launch files are redistributed.

Existing MotionLock reviewed and copied into standalone workspace with Python 3.8 typing. Same gdps_g1_motion.lock filename retained. Existing adapter/loco_backend reviewed; write-capable backend is intentionally excluded, as there is no independently verified SDK watchdog or field authorization. Previous gdps_g1_navigation local avoidance is not used as a planner/controller. Navfn, DWB, SLAM Toolbox and official cloud-to-scan supply the algorithms.

Foxy rclpy executor upstream source passes only the message to subscription callbacks; it cannot audit publisher GIDs. A small rclcpp authority monitor therefore audits duplicate TF owners. This compatibility finding is reflected in actual code.

## Dependency gaps
Target historical nav2 core availability is unverified; nav2_bringup/slam_toolbox/cloud-to-scan historically missing. preflight.sh measures actual package prefixes, APT source records/candidates, architecture/interface/QoS, clocks and installed SDK source signatures. install_dependencies --plan records exact missing-package APT candidates; --install consumes that reviewed plan. Existing installed packages are not upgraded. No indexes, ROS sources or system clock/services are changed by these scripts. Pinned source fallback SHAs are in third_party.lock. ARM64, SDK RPC signatures and live FSM remain pending target audit.
