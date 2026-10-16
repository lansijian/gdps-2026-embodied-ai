# shared/navigation — G1 EDU (all tracks)

Public API: `shared.navigation.factory.build_navigator` and `docs/interfaces/navigation.md`.

```
shared/navigation/
  api/              # start / goal / pause / stop / status
  perception/       # 2D obstacle gating
  safety/           # stale data, heartbeat, manual stop
  ros2_ws/          # optional Humble package gdps_g1_navigation
  factory.py
  README.md
shared/robot_control/g1/
  adapter.py        # clamps, dry-run, lock, watchdog
  loco_backend.py   # official LocoClient (path B)
  ros_sport_backend.py
```

Default run mode is **dry-run**. Do not send live walking commands until Phase 5 authorization.

Offline check (Windows or Linux, no ROS):

```text
python scripts/g1/dryrun_local.py
python -m unittest tests.navigation.test_safety_and_nav
```
