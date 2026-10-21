# 参考实现（非运行依赖）

- g1_doubao_voice.py：豆包端到端实时语音 + G1 麦克风/喇叭的最小可运行 demo，
  是 guide/doubao_realtime.py 的来源。保留用于现场对照排障（DDS、组播、PlayStream）。
  正式运行请用 scripts/tourism/guide_node.py，不要直接跑本文件。
- scripts/tourism/g1_camera_fix.sh：G1 上 RealSense D435i 的一键修复/查看脚本
  （videohub 占用、USB 省电、udev、出流自检），来自同一现场调试目录。
