# Field day — navigation, lidar, camera (Phase 4.2)

## Safety checklist (human, before any LIVE motion)

- [ ] Operator present with hardware E-stop reachable
- [ ] Walking mode verified with Unitree official procedure (not this repo)
- [ ] Single motion lock owner (`gdps_g1_navigation`); no vendor teleop conflict
- [ ] `max_vx` / `max_wz` / `max_vy` reviewed; LIVE keeps `max_vy=0` unless explicitly re-authorized on site
- [ ] `GDPS_G1_LIVE=1` + token + phrase `ENABLE LIVE MOTION` only after checklist
- [ ] Short duration commands; watchdog timeout active

## Windows (pack / review)

```powershell
cd E:\GDPS\competition
python -m pytest tests/navigation tests/quality_inspection/test_mission_flow.py -q
python scripts/g1/field_gate_check.py --gate all
```

## G1 Linux — read-only first

```bash
cd /home/unitree/gdps-qi-field-diag   # or full repo clone
source /opt/ros/foxy/setup.bash
export GDPS_QI_EXECUTION_MODE=field
export PYTHONPATH=$PWD/tracks/quality-inspection:$PWD:$PYTHONPATH

# Gate 0–5 (add --live on robot for ROS probes)
python3 scripts/g1/field_gate_check.py --gate all --live --timeout 5 \
  --rgb-topic "<fill>" --depth-topic "<fill>" --camera-info-topic "<fill>"

# Lidar only
bash scripts/g1/perception_dryrun.sh

# Nav dry-run stack (no LIVE)
source shared/navigation/ros2_ws/install/setup.bash
ros2 launch gdps_g1_navigation local_avoid_dryrun.launch.py
```

## Velocity topic chain

`gdps_local_navigator` → `/gdps/cmd_vel_local` → (optional) `gdps_cmdvel_bridge` → `/gdps/cmd_vel_filtered`

Do **not** run bridge and navigator with two motion adapters on one host (motion lock).

## Foxy note

Use `scripts/g1/ros2_one_shot.py` instead of `ros2 topic echo --once`.
