# Execution specification traceability

The complete supplied specification is archived as EXECUTION_SPEC.md with SHA256. Status does not infer hardware success from unit tests.

| Spec | Implementation / evidence | Hardware limitation |
|---|---|---|
| 0, 1, 2 scope/audit/preserve | EVIDENCE_BASELINE.md, third_party.lock, isolated branch/worktree | User field observations remain unverified here |
| 3 colcon/packages/Foxy/Python3.8 | 6 ament_python packages + 1 rclcpp GID monitor, setup/install metadata, Foxy CI | ARM64 build pending |
| 4 inverted sensor and TF | Quaternion validator/axis tests, measured odom TF, external TF agreement, floor/obstacle CSV tool and RViz | Actual xyz/quaternion/floor/footprint unknown; BLOCKED |
| 5 time/QoS | Read-only 30s audit, sensor QoS, preserve-only normalized cloud/odom/IMU, age/order/jump gate | Clock source not established; non-preserve strategies blocked; packet loss cannot be exactly counted without source sequence |
| 6 perception/mature algorithms | Official cloud_to_scan target-frame filtering + independently calibrated cloud -> Nav2 ObstacleLayer | Real CPU load/3D obstacle coverage/scan latency pending; no negative obstacle guarantee |
| 7 SLAM/localization/Nav2 | SLAM Toolbox mapping, mutually exclusive AMCL/map_server localization, Navfn/DWB, wait-only recovery, lifecycle managers | Real map/goal/path/convergence not validated; synthetic tests are separate |
| 8 motion bridge | Existing lock convention, isolated zero-SDK DryGate, finite/bounds/acceleration/timeout checks and command observer | SDK write backend and independent hardware stop absent, LIVE impossible; true FSM/SetVelocity signature/RPC pending |
| 9 launch/deployment | Five integrated launch files, process exit preflight gate; install/build/copy/smoke/map-save scripts | No robot SSH/deploy/install/launch occurred; scripts fail on missing prerequisites |
| 10A local/CI | Windows contracts, baseline regressions, Python3.8/Foxy container build and ROS integration | x86_64 CI is not ARM64/robot evidence |
| 10B-C sensor/TF | Health stats, TF GID monitor, clock audit, tf2_echo smoke | Real subscription/frequencies/ground/unique TF pending |
| 10D map | Synthetic SLAM occupancy/posegraph save, AMCL occupancy reload harness | No real bag provided; real mapping/localization pending |
| 10E dynamic/fault | Contract fault gates and ROS synthetic integration scenarios | DDS QoS mismatch and real negative obstacle detection not hardware-verified |
| 10F bridge | Tripwire mock SDK calls zero; no SDK module imported in installed source | No LIVE transport or field authority |
| 10G migration/Git | Source ZIP/tar manifests, feature commits pushed, PR body prepared | PR creation blocked by connector and repository Actions policy (403); no PR URL fabricated |
| 11 delivery | README, deployment/calibration/time/safety/troubleshooting/verification docs, source archive and audit trail | Explicit pending items retained |

Timestamp repair, LIVE execution and independent hardware watchdog are intentionally incomplete rather than silently emulated. They must not be described as implemented or certified.
