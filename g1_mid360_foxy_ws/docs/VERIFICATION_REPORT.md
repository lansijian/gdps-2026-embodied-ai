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

Validated representative-load run: https://github.com/lansijian/gdps-2026-embodied-ai/actions/runs/39376281980 at 7fcbe0c9d3d91d049baaa736c1f7d3c1bd62be7f. Both native ARM64 and x86_64 jobs passed: 54 contract/script tests, 3 real negative launch checks, 27 ROS integration checks, 7 packages built and all 5 launch entries discovered. This final code run includes the unsupported-layout failure case, refusal of pre-existing map TF ownership, isolated cmd_vel routing and strict no-crash shutdown checks; all passed.

The workload is explicitly synthetic: 20,064 points / 32-byte stride at 10Hz, odom timer configured 800Hz, IMU 200Hz. Geometry is repeated to represent processing volume, not real MID-360 angular coverage. Actual receiver observations (BEST_EFFORT can drop packets):

| Native architecture | cloud Hz | raw odom received Hz | IMU Hz | scan Hz | scan header-to-receipt P95 | finite scan ratio |
|---|---:|---:|---:|---:|---:|---:|
| arm64 | 10.000 | 721.700 | 200.000 | 10.000 | 16.22ms | 97.36% |
| x86_64 | 10.000 | 657.391 | 196.603 | 10.004 | 31.59ms | 97.36% |

These are VM/container synthetic observations, not G1 performance or real clock synchronization evidence. Full metrics and all individual ROS check names are in docs/ci/. Downloaded artifact SHA256 values were checked against GitHub metadata; local logs/release-arm64 and logs/release-x86_64 preserve the archives, maps, pose graphs, installed package versions and logs. Source archives deliberately exclude runtime logs and site configuration.

Shutdown diagnosis found CycloneDDS receive threads active during librmw_implementation's library unloading (GDB recvMC/ddsrt_recvmsg and dlclose stacks). A per-process LD_PRELOAD reference to the exact installed CycloneDDS RMW is applied only to this workspace's SLAM/controller child processes; no system library, factory service or SDK factory method is modified. Both architectures subsequently passed explicit no-crash assertions for SLAM and Nav2 shutdown. Nav2 is first deactivated/cleaned/shut down using its lifecycle managers. This is a bounded process-lifetime mitigation, not a claim that the upstream object-lifetime issue is fixed. Primary related report: https://github.com/ros2/rclcpp/issues/2567.

The raw Nav2 command is isolated at /g1_nav/cmd_vel_nav2, with preview at /g1_nav/cmd_vel_safe and recovery command output separately disabled. The integration test verifies no global /cmd_vel publisher. LIVE remains absent. Layouts other than little-endian FLOAT32 XYZ are rejected before official cloud-to-scan receives them; the offline/vectorized decoder can support additional layouts without falsely claiming Foxy's converter does.

No debugger is used in the normal representative-load acceptance run. Debug prefix is opt-in via G1_NAV_DEBUG_SLAM=1 for diagnosis only.

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

## Final outcome

- **Windows**: 54 new contract/script tests + 104 existing robot/navigation regressions passed, 0 failed.
- **Native ARM64 Foxy / native x86_64 Foxy**: each 54 contract/script tests + 3 negative launch checks + 27 ROS integration checks passed, 0 failed; each built 7 packages and discovered 5 entry points. Final normal launches run without gdb.
- Actual maps and pose graphs were saved, AMCL map reloaded, all six Nav2 lifecycle nodes reached ACTIVE, Navfn action returned a nonempty path, DWB produced isolated command output and preview, a new obstacle was marked in local costmap, required data/clock/TF/heartbeat faults inhibited preview with explicit reasons, SDK writes remained 0, and both SLAM/Nav2 shut down without process crashes.
- CI summaries under docs/ci are synthetic evidence only. The delivery documentation commit may follow this tested code commit; src/scripts/tests/workflow must remain byte-identical to the validated code for this evidence to apply.
- Robot hardware, target transfer/install/build/launch and LIVE acceptance remain pending. PR remains blocked by the documented 403 permission restrictions; no PR URL exists.
