# Verification report - 2026-10-20

## Scope and immutable boundaries

Target Ubuntu 20.04 ARM64 / ROS 2 Foxy / CycloneDDS / Unitree G1 EDU 29-DOF / factory MID-360. LIVE DISABLED; SDK write transport is absent, not merely switched off. No robot SSH, motor/FSM command, original driver/service replacement, system clock modification, merge, tag or force push occurred.

All ROS CI input is **SYNTHETIC_TEST** in isolated domain 87. Native ARM64 container results demonstrate architecture/runtime compatibility; they do not establish G1 firmware/SDK/sensor calibration, real mapping/planning, braking or hardware safety. Original dirty checkout and existing main worktree are preserved.

## Executed local checks

- `python -m pytest g1_mid360_foxy_ws/tests/test_contracts.py g1_mid360_foxy_ws/tests/test_scripts.py -q`: **54 passed, 0 failed** on Windows Python 3.11.4. Includes Python 3.8 grammar, 7 package manifests/YAML/XML, 29-joint ZIP metadata hash, quaternion axis/floor calculations, floor-below-body-origin handling, endian/organized PointCloud2 decoding, clock age/future/order/jumps, bounded 30-second statistics, dry-run tripwire SDK zero writes, velocity/acceleration/timeouts, cooperative lock, archive manifest/privacy exclusions, no-import SDK source audit and numeric SVD floor CLI.
- Existing `python -m pytest tests/robot_control tests/navigation -q`: **104 passed, 0 failed** on this isolated baseline. These do not certify new hardware behavior.
- All six shell files pass Git Bash `bash -n`; deploy PowerShell script passes the actual PowerShell AST parser. Remote transfer, dependency installation and G1 script execution remain target pending.
- ZIP SHA256 and unchanged reused joint metadata SHA256 match third_party.lock. Git diff whitespace verification is checked before final delivery.

## ROS CI evidence

The dedicated workflow builds all 7 packages under actual Python 3.8/Foxy and discovers all five launch entries. Both x86_64 and native ARM64 use the same pinned Ubuntu 20.04 Foxy image digest; the runner host OS is not the container OS. The workflow records installed ROS versions and uploads logs, maps and JSON results.

Earlier integration runs exposed and corrected POSIX lock initialization, wrong OccupancyGrid dimension access, Foxy's integer millisecond map-saver timeout, Foxy ComputePathToPose.pose action field and premature goals before ACTIVE lifecycle states. Earlier failures remain visible in Git/CI history and local logs/ci. No earlier failed run is relabelled as passed.

Current final ROS outcome is filled after the running checks finish; see the appended CI outcome section below. Observed earlier milestones include source/scan/TF health, nonempty SLAM occupancy map, occupancy + pose graph save, AMCL map reload and real Navfn action paths in synthetic scenes.

## Launch coverage

| Entry | Evidence scope |
|---|---|
| sensor_check.launch.py | Installed/discovered; shared sensor pipeline is exercised by ROS integration; standalone target run pending |
| mapping.launch.py | Synthetic full startup, 30s runtime gate, SLAM map/save exercised |
| localization.launch.py | Installed/discovered; same AMCL/map-server path exercised inside navigation_dryrun; standalone target run pending |
| navigation_dryrun.launch.py | Synthetic lifecycle/action/costmap/command/fault acceptance harness; final result below |
| g1_nav_bringup.launch.py | Installed/discovered; actual negative launch checks block live, missing site and unknown calibration; positive behavior shares the mode implementation |

`--show-args` success means launch discovery only, not positive sensor/map acceptance. Unknown site parameters prevent real positive runs by design.

## Unverified and hard blockers

**BLOCKED_NEEDS_CALIBRATION / ROBOT_VERIFICATION_PENDING**: full robot_center->livox_frame xyz + quaternion + axis evidence; real body-frame floor_z/margin, height window and low/table-edge retention; actual robot footprint; measured scan_time/frequency/QoS; real sensor/odom/IMU time sources, offsets/jumps/latency and same-clock proof; current interface/domain/CycloneDDS config; actual dog_odom semantics/unique TF; real map/localization convergence/path/costmap/dynamic obstacle behavior; G1 CPU load, blind spots, stairs/negative obstacles, stopping distance; target installation/build/launch logs.

**BLOCK LIVE**: real installed SDK signature/version and read-only FSM result, hardware emergency stop/fall protection, unique hardware motion authority, independent watchdog resistant to SDK stalls, site authorization and progressive physical speed/braking tests are incomplete. No SetVelocity/Move/StopMove backend is enabled or supplied as an executable. Non-preserve timestamp repair strategies are explicitly blocked pending real clock evidence.

## GitHub delivery restriction

Feature branch pushes through the existing authenticated SSH identity succeeded. PR creation was attempted through the GitHub connector (403 Resource not accessible by integration) and a narrowly scoped repository workflow (403 GitHub Actions is not permitted to create or approve pull requests). Repository permissions were not changed. The temporary PR workflow job was removed. **No PR was created and no PR URL is claimed.** PR_BODY.md and the GitHub compare/create link provide a concrete reviewable handoff. Main remains unchanged.
