# Quality Inspection Phase 4.1 — Field read-only diagnostics

## Changes

- Dex3 / LowState: HG IDL fields (`q`, `dq`, `tau_est`); no zero-fill; DDS `network_interface` config.
- Camera: step/endian/depth_scale gates; RGB–depth sync; no default intrinsics on live probe.
- Package: whitelist + `MANIFEST.sha256` + zip summary with commit SHA.

## G1 manual run

See `scripts/g1/field_diag_bundle/README_DEPLOY.md`.

## Troubleshooting (short)

| Symptom | Check |
|--------|--------|
| DDS timeout | `unitree_dds.network_interface` (e.g. eth0), CycloneDDS env, topic names |
| LowState reject | motor array length ≥ 29, index map vs firmware |
| Depth unusable | set `camera.depth_scale_m`, enable `allow_16uc1_depth`, RGB/depth stamp delta |
| intrinsics_trusted false | subscribe `camera_info` topic, match resolution |
| Pinocchio skip on PC | expected on Windows dev host; run URDF checks on robot |
