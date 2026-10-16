# Phase 0 — G1 navigation open-source review

Reviewed on 2026-10-16 from shallow clones under local `.research/` (gitignored).
Do not copy those trees into this repository.

## 1. guruadp/unitree-g1-slam-nav

| Field | Value |
| --- | --- |
| URL | https://github.com/guruadp/unitree-g1-slam-nav |
| Commit | `b9a1fbd5459bda72a056e71eb8f9aa9a437f0228` (2026-03-26, "initial commit") |
| License | `package.xml` says Apache-2.0; **no LICENSE file in tree** |
| Default branch | `master` (not `main`) |
| ROS | Humble workspace (`ws_slam`) |

What it actually does:

- Livox MID-360 → `pointcloud_to_laserscan` (`/scan_raw`) → `scan_restamper` (`/scan`)
- `slam_toolbox` mapping or localization; Nav2 Regulated Pure Pursuit + NavFn/A*
- `odom_tf_broadcaster` subscribes **`/dog_odom`** and republishes TF with ROS clock
- `cmdvel_to_sport.py` publishes `unitree_api/msg/Request` on **`/api/sport/request`**
- API id **7105**, JSON `{"velocity":[vx,vy,wz],"duration": ...}` at 30 Hz
- Timeout 0.25 s zeroes velocity; default max 0.20 m/s / 0.30 rad/s
- Frames: `robot_center` (not `base_link`)

G1 EDU fit:

- API **7105 matches official G1 `LocoClient.SetVelocity`** (`g1_loco_api.py`).
- Topic names `/api/sport/request` and `/dog_odom` look inherited from Go2-style stacks.
- **Not verified on this team's firmware.** Enabling path A requires `ros2 topic list` / `ros2 interface show`.
- We reuse: restamp idea, Nav2 layering, conservative velocity clamp. We do **not** vendor the whole workspace.

## 2. Hucebot/g1pilot

| Field | Value |
| --- | --- |
| URL | https://github.com/Hucebot/g1pilot |
| Commit | `5346e52191e97d3ec07312f23c87bb58a849fdf7` |
| License | BSD-3-Clause |
| ROS | README badge Jazzy; Docker text still mentions Ubuntu 22.04 + Humble |

What it actually does:

- `ChannelFactoryInitialize` + official `LocoClient`
- Walking via `Move(..., continous_move=True)` / `StopMove()`
- Also calls `Damp()`, `SetFsmId`, `SetStandHeight`, `BalanceStand`, `Start()`
- MOLA odometry, custom Dijkstra planner, joystick mux, arm/cartesian stack, Docker

G1 EDU fit:

- Confirms **path B**: ROS nodes should wrap `LocoClient`, not Go2 `SportClient` / `ObstaclesAvoidClient`.
- We do **not** import their FSM / Damp / height dance. Software stop here is `StopMove` only.
- We do **not** vendor MOLA, URDF meshes, or Docker images.

## 3. unitreerobotics/unitree_sdk2_python

| Field | Value |
| --- | --- |
| URL | https://github.com/unitreerobotics/unitree_sdk2_python |
| Commit | `814556d15970dd2ecf1c9984e845ca02ab07e206` |
| License | BSD-3-Clause |

Relevant API (`unitree_sdk2py/g1/loco/`):

- Service name is still `"sport"` (`LOCO_SERVICE_NAME`) — this is G1 loco, not Go2 SportClient.
- `SetVelocity(vx, vy, omega, duration=1.0)` API id 7105
- `StopMove()` → `SetVelocity(0,0,0)`
- `Move(...)` same as SetVelocity with optional long duration
- Init: `ChannelFactoryInitialize(0, networkInterface)` then `LocoClient.Init()`
- Example: `example/g1/high_level/g1_loco_client_example.py`

**Forbidden as software stop in this project:** `ZeroTorque()`, `Damp()` (FSM id 0 / 1). Those can drop support.

Go2 `ObstaclesAvoidClient` lives under `example/obstacles_avoid` and is **not** used.

## Control path decision

| Path | Mechanism | Status in this repo |
| --- | --- | --- |
| **B (default live candidate)** | `/cmd_vel` → `G1MotionAdapter` → `UnitreeLocoBackend` → `LocoClient.SetVelocity` | Implemented; hardware untested |
| **A (optional)** | `/cmd_vel` → `RosSportRequestBackend` → `unitree_api/Request` api_id 7105 | Implemented behind adapter; topics **unverified** |
| Mock | Adapter dry-run + `MockLocoBackend` | Default; unit-tested on Windows |

Upper layers (`SharedNavigator` and tracks) never import `unitree_sdk2py`.

## What is still site-unknown

- SSH user, robot IP, which RJ45 port / NIC
- Whether Livox MID-360 is installed and which ROS driver/topics
- Odometry topic (`/dog_odom` is not trusted)
- Base frame (`robot_center` vs `base_link`)
- Whether `unitree_api` ROS messages exist on the EDU image
- CycloneDDS / RMW config across Windows vs robot
