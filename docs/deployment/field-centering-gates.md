# Field centering Gates A–E (Phase 4.3)

No LIVE motion in these gates. Human checklist required before any `GDPS_G1_LIVE=1`.

## Windows (offline / CI)

```powershell
cd E:\GDPS\competition
python -m pytest tests/quality_inspection/test_phase43_centering.py -q
python scripts/g1/field_gates_centering.py --gate D,E
```

## G1 Linux

```bash
export PYTHONPATH=$PWD:$PWD/tracks/quality-inspection:$PYTHONPATH
export GDPS_QI_EXECUTION_MODE=field

# A: camera read-only
python3 scripts/g1/field_gates_centering.py --gate A --live \
  --rgb-topic "<rgb>" --depth-topic "<depth>" --camera-info-topic "<info>"

# B: lidar + odom note
python3 scripts/g1/field_gates_centering.py --gate B --live --pc-topic /utlidar/cloud_livox_mid360

# D: lateral / rotate dry-run previews
python3 scripts/g1/field_gates_centering.py --gate D

# E: TF template + sensor validation scaffold
python3 scripts/g1/field_gates_centering.py --gate E
```

## LIVE lateral (separate authorization)

- Hardware E-stop, operator present
- Walking mode per Unitree procedure
- Single `MotionLock` owner
- `max_vy=0` for LIVE unless explicitly reconfigured on site
- Short duration, low `max_vx`, lidar CLEAR in lateral sector
