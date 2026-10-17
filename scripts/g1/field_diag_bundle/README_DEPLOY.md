> Phase 4.4: this legacy package does not contain the current Gate A-E/replay toolchain. Use `scripts/g1/package_phase44.ps1` and `docs/deployment/phase44-field-replay.md`; unpack into a new directory.

# G1 质检只读现场诊断包（Phase 4）

## 目的

在 **不覆盖** 现有 `gdps_g1_navigation` 部署的前提下，将只读诊断工具解压到独立目录运行。

## Windows 打包前审核（开发机）

```powershell
cd E:\GDPS\competition
.\scripts\g1\field_diag_bundle\package_field_diag.ps1
# 输出: dist\gdps-qi-field-diag-<date>.zip
```

检查 zip 内仅含：`scripts/`、`tracks/quality-inspection/gdps_qi/`、`tracks/quality-inspection/configs/`、本 README，**无** `.env`、密钥、日志。

## G1 PC2 部署（人工 SSH，不自动执行）

```bash
# 1) 在开发机将 zip 通过 scp 复制到机器人（示例）
# scp dist/gdps-qi-field-diag-*.zip unitree@192.168.123.164:/home/unitree/

# 2) SSH 登录后解压到独立目录
mkdir -p /home/unitree/gdps-qi-field-diag
unzip -o gdps-qi-field-diag-*.zip -d /home/unitree/gdps-qi-field-diag
cd /home/unitree/gdps-qi-field-diag

# 3) 使用已有 Foxy 环境（不 apt / 不 sudo）
source /opt/ros/foxy/setup.bash
export GDPS_QI_EXECUTION_MODE=field
export PYTHONPATH=$PWD/tracks/quality-inspection:$PYTHONPATH

# 4) 复制并编辑 Topic 配置
cp tracks/quality-inspection/configs/g1/qi_topics_readonly.example.yaml /tmp/qi_topics.yaml
# 人工填入实测 rgb / joint_states / lowstate / dex3 topics
# 必填：unitree_dds.network_interface（如 eth0）、camera.depth_scale_m（若用 16UC1 深度）

# 5) 干跑 schema（不订阅）
python3 scripts/g1/qi_hardware_diagnostics.py --config /tmp/qi_topics.yaml

# 6) 只读 live 探测（需现场确认 CycloneDDS / ROS 环境已就绪）
python3 scripts/g1/qi_hardware_diagnostics.py --live --timeout 5 --config /tmp/qi_topics.yaml \
  | tee /tmp/gdps_qi_diag_$(date +%Y%m%d_%H%M%S).json
```

## 禁止项

- 不运行 `sudo`、`apt`、`systemctl`、`rm -rf`
- 不启动 arm_sdk / HandCmd / 运动控制
- 不修改 `/home/unitree/gdps-2026-embodied-ai` 内已有导航包

## 输出

统一 JSON：`devices.*`、`urdf`、`compatibility`、`notes`；未知项显式 `UNKNOWN` / `missing`。
