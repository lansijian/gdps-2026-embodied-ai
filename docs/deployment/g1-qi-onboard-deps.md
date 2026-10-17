# G1 质检 `gdps_qi` 机载依赖清单（Phase 2）

目标环境：Ubuntu 20.04 aarch64 · Python **3.8.10** · ROS 2 Foxy

## 已用（仓库内，无额外安装）

- `numpy`（导航/质检共用）

## 现场探测 / P1 视觉（按需安装，版本需与 Foxy 一致）

| 包 | 用途 | 状态 |
|---|---|---|
| `opencv-python` 或 `python3-opencv` | 圆检测、图像读写 | 开发机可选；机载待确认 |
| `Pillow` | `HeadCameraReadOnly.read_file` 离线读图 | 可选 |
| `pytesseract` + `tesseract-ocr` | 奶片编号 OCR | 可选，未装则标签 `UNREAD_xx` |
| `pinocchio` | G1 URDF FK/IK | **未在 PC2 验证**；`G1UrdfKinematicsAdapter` 无则保持 UNAVAILABLE |
| `casadi` | xr_teleoperate 官方 IK | 未纳入仓库；移植前仅只读研究 |
| `unitree_sdk2_python` | Dex3/臂只读状态 | 不写入仓库；现场 venv 隔离安装 |
| `PyYAML` | 标定 YAML | 若机载缺失：`python3 -m pip install pyyaml`（需队里授权） |

## 明确不安装（本轮）

- ROS Humble / Ubuntu 升级
- 修改厂商 `unitree` 系统服务
- 未验证的自动 `pip install pinocchio` 到系统 Python

## 环境变量

| 变量 | 含义 |
|---|---|
| `GDPS_QI_EXECUTION_MODE` | `field`（默认）或 `simulation` |
| `GDPS_G1_URDF_PATH` | 经验证的 `g1_body29_hand14.urdf` 绝对路径 |
