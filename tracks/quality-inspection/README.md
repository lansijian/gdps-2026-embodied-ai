# Track: quality-inspection (primary)

Do not implement a second navigation stack here.
Import `shared.navigation.factory.build_navigator` and pass **this track's goals**.

Robot motion stays in `shared/robot_control/g1`.

## Package layout

- `gdps_qi/` — P1–P6 技能、TF/视觉/抓取、任务调度（默认 **dry-run**，无真机运动）
- `configs/workstation_calib.example.yaml` — 工位标定模板（现场填 `calibrated: true` 后才允许接触）
- 文档：`docs/handover/quality-inspection-2026-10-17.md`、`docs/hardware_interface_matrix.md`

## Quick test

```bash
python -m pytest tests/quality_inspection -q
```
