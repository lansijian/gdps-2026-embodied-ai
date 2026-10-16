# Shared navigation interface

Tracks (`quality-inspection`, `retail`, `cultural-tourism`) must use this API.
Do not call `LocoClient`, `SportClient`, or publish `/api/sport/request` from track code.

## Python (no ROS required)

```python
from shared.navigation.factory import build_navigator
from shared.navigation.api.types import Pose2D
from shared.navigation.perception.obstacle_monitor import ScanFrame

nav = build_navigator()          # dry-run + mock backend by default
nav.start()
nav.set_goal(Pose2D(x=1.0, y=0.0, yaw=0.0, frame_id="map"))
nav.on_scan(ScanFrame(...))      # required while require_sensor=true
nav.on_pose(Pose2D(...))         # optional until odom is verified
status = nav.get_status()
cmd = nav.step()                 # clamped velocity; live output gated
nav.pause()
nav.stop("task_done")
nav.notify_path_unreachable()
nav.adapter.close()
```

### Status fields

| Field | Meaning |
| --- | --- |
| `state` | `idle` / `running` / `paused` / `stopped` / `fault` |
| `capability` | `local_avoid` (implemented) or `full_autonomous_nav` (Nav2, not verified on site) |
| `mode` | `dry-run` (default) or `live` |
| `halt` | safety reason if motion is blocked |
| `last_decision` | `stop` / `slow` / `detour_*` / `clear` / `no_sensor` |
| `last_return_code` | backend code; `0` is OK |

### Live mode

`G1MotionAdapter.enable_live(token, "ENABLE LIVE MOTION")` plus env `GDPS_G1_LIVE=1`.
Phase 5 only, after the human checklist. Default limits: **0.10 m/s**, **0.15 rad/s**.

## ROS 2 topics (when Humble is present)

| Topic | Direction | Notes |
| --- | --- | --- |
| `/cmd_vel` | Nav2 → `cmdvel_bridge` only | Do not also run `guruadp` `cmdvel_to_sport` |
| `/gdps/cmd_vel_local` | local navigator output | Avoids feeding unverified sport bridges |
| `/gdps/cmd_vel_filtered` | bridge → debug | clamped command |
| `/scan_raw` → `/scan` | restamper | Livox clock workaround |
| `/gdps/nav_status` | out | human-readable status |
| `/gdps/manual_stop` | in | software stop |
| `/gdps/host_heartbeat` | in | SSH-loss heuristic |
| `/goal_pose` | in | local navigator goal |

Odometry topic is **not** hardcoded. Set `odom_topic` after `ros2 topic list`.

## Safety contract

- Default `dry-run`: mock/history only, no DDS SetVelocity.
- Command watchdog zeroes velocity after `command_timeout_s`.
- Stale scan / optional stale odom/TF / optional host heartbeat → `StopMove` path (zero velocity).
- Local navigator publishes `/gdps/cmd_vel_local` so it cannot accidentally drive an unverified `/api/sport/request` bridge.
- One motion lock file so two controllers cannot both own the backend.
- Process exit calls `adapter.close()` → software stop, **not** torque-off.
- Software stop ≠ hardware e-stop.

## Capability split

| Capability | Needs | Today |
| --- | --- | --- |
| Local avoid | 2D scan-like ranges | Implemented + unit-tested |
| Full Nav2 | map, TF, odom, Nav2, verified lidar | Launch files only; **unverified** |
