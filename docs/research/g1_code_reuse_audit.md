# G1 code reuse audit (Phase 4.2)

Baseline repo: `lansijian/gdps-2026-embodied-ai` @ `4d74365` (pre–4.2 nav fixes on branch `feat/quality-inspection-agent`).

References (upstream HEAD families, verify on site):

| Project | Role | Pin for audit |
|---------|------|----------------|
| unitree_sdk2 | C++ IDL / Loco / DDS | `unitree_hg::msg::dds_::MotorState_`, `HandState_` (commit family `c55e8558` on GitHub) |
| unitree_sdk2_python | Python DDS + Loco | `unitree_sdk2py/core/channel.py` `ChannelFactoryInitialize`, `ChannelSubscriber` |
| xr_teleoperate | Teleop + URDF names | `assets/g1/g1_body29_hand14.urdf` (documented in `g1_joint_map.py`) |
| unitree_ros2 | ROS2 sport APIs | sport request topics (not wired LIVE in gdps) |
| pointcloud_to_laserscan | PC2→LaserScan | ROS package `pointcloud_to_laserscan` (optional on robot) |
| geometry2 / tf2 | TF math | used indirectly via `robot_state_publisher` on robot |
| Nav2 Foxy | Global nav | **not** hard dependency; launch scaffold only |
| g1_slam (vitorsmends) | Architecture reference | Humble-oriented; **not** imported |

## Already calling / aligning with official SDK

| Our path | Official source | Notes |
|----------|-----------------|-------|
| `shared/robot_control/g1/loco_backend.py` | `unitree_sdk2_python` Loco client | LIVE gated by `G1MotionAdapter.enable_live` |
| `gdps_qi/adapters/readonly/dds_readonly.py` | HG `HandState_` / `LowState_` IDL | `q`, `dq`, `tau_est`; read-only `ChannelSubscriber` |
| `gdps_qi/hardware/g1_joint_map.py` | xr_teleoperate URDF + SDK low-level index tables | `DOCUMENTED_UNVERIFIED` until field JSON |
| `shared/navigation/ros2_ws/.../odom_tf_node.py` | `/dog_odom` vendor odom | No synthetic pose |

## Self-developed (keep)

| Module | Why |
|--------|-----|
| `shared/navigation/api/navigator.py` | Competition safety: fail-closed, dry-run preview, obstacle gating |
| `shared/navigation/safety/supervisor.py` | SSH/heartbeat + sensor staleness policy |
| `shared/robot_control/g1/motion_lock.py` | Single-writer motion ownership |
| `gdps_qi/transforms/calibration_trust.py` | CALIBRATED_WORLD gate |
| `gdps_qi/mission/mission_flow.py` | P1–P6 decision tree / evidence |
| `scripts/g1/field_gate_check.py` | Unified field gates |

## Could replace with mature ROS (if present on PC2)

| Our component | ROS / vendor alternative | Blocker on G1 Foxy image |
|---------------|------------------------|----------------------------|
| `perception/pointcloud_to_laserscan.py` | `pointcloud_to_laserscan` node | Package may be missing; we ship `gdps_pointcloud_to_laserscan` |
| NumPy scan projection | `laser_geometry` / PCL | Extra deps; numpy path kept for dry-run |
| TF publishing | `robot_state_publisher` + URDF | URDF + extrinsics UNVERIFIED |
| Global planning | Nav2 | `nav2_bringup` often missing; not field-hard-dep |

## Missing on robot → cannot adopt yet

- `slam_toolbox`, `nav2_bringup` (called out in `perception_dryrun.sh` dep check)
- Pinocchio + full G1 URDF on dev Windows host
- Verified `livox_frame` → `robot_center` extrinsic (obstacle forward distance **not** calibrated)

## Mock / no real hardware interface

| Area | Status |
|------|--------|
| `MockLocoBackend` | Dry-run only |
| `SimplifiedTestKinematics` | Tests only; not G1 |
| `CameraAdapter.set_mock_frame` | Simulation / CI only |
| `register_simulation_workstation()` | `GDPS_QI_EXECUTION_MODE=simulation` |
| Default `backend: mock` in `safety.json` | No SetVelocity until LIVE |

## Duplication watchlist

- Two `G1MotionAdapter` instances if both `local_navigator` and `cmdvel_bridge` run → **MotionLock** second connect fails (-30); run one adapter owner per process.
- Internal numpy PC2→scan vs ROS `pointcloud_to_laserscan`: keep both; compare latency on site (Gate 1).

## Action items after field JSON

1. Confirm DDS `network_interface` and Dex3/LowState topics.
2. Confirm camera topics + `depth_scale_m`; teleimager vs ROS image topics.
3. Measure lidar TF; set `lidar_frame_extrinsic_verified` + `lidar_forward_angle_offset_rad` in `safety.json`.
4. Only then enable `allow_auto_forward` for station approach tests (still dry-run first).
