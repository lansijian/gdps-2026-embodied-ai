# Quality Inspection Phase 4 Handover

## Scope

Read-only hardware subscribers, TF/calibration trust gates, strict P1 localization, field diagnostic bundle. No P2–P6 expansion, no motor writes.

## Tests (dev)

```bash
cd competition
python -m pytest tests/ -q
```

See CI/local pytest for current counts (Phase 4.1 adds field-readiness regression tests).

## Field diagnostic bundle

See `scripts/g1/field_diag_bundle/README_DEPLOY.md`.

## On-site verification still required

- Actual RGB/Depth/CameraInfo topic names and teleimager path
- G1 URDF path, variant DoF, `robot_center`→`pelvis` extrinsic
- Dex3 DDS topics and HandState layout vs SDK2
- TCP pinch offsets (currently unverified; plans are read-only)

## Next on-site steps

1. Edit `/tmp/qi_topics.yaml` from example config.
2. Run dry-run diagnostics JSON, then `--live --timeout 5`.
3. Set `GDPS_G1_URDF_PATH` and re-run; confirm joint snapshot not UNKNOWN.
4. Apply verified base_pelvis + camera calibration before expecting `CALIBRATED_WORLD`.
5. Run `P1_LOCALIZE_01` with `allow_relative_table` only after table/camera trust passes.
