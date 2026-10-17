# Phase 4.4 官方复用审查（2026-10-17）

以本轮读取的分支 SHA 为版本依据；不把 Rolling 文档作为 Foxy API 依据。分支解析记录见 `phase44-source-refs.json`，逐文件 SHA256 见 `phase44-source-audit.json`。本机读到了下列实际源码；机载已安装版本仍为 UNKNOWN，必须执行依赖探测并保存现场 `ros2 pkg prefix`/`dpkg-query` 结果。

| 上游 / 分支 | 决策 | 读取的官方源码 | 当前仓库职责及处置 |
|---|---|---|---|
| ros2/geometry2 / foxy | **REUSE** | [tf2_ros/src/tf2_ros/buffer.py](https://github.com/ros2/geometry2/blob/d1dc38b8a0e706fbd67a800a241fee950fce39f4/tf2_ros/src/tf2_ros/buffer.py) | 实时订阅/缓存/查询交给 Buffer 与 TransformListener；`scripts/g1/field_evidence.py` 与 `gdps_qi/transforms/ros_tf.py` 使用官方实现。`TransformManager` KEEP，仅离线历史数学和既有测试。 |
| ros2/message_filters / foxy | **REUSE** | [src/message_filters/__init__.py](https://github.com/ros2/message_filters/blob/5042d46bee8d4e31f64fe5610c1c4c2401e62788/src/message_filters/__init__.py) | `field_evidence.py` SimpleFilter + ApproximateTimeSynchronizer，三路真实 header 时间；`perception/message_sync.py` 同步工厂保留。缺任一路不构造零时间差。 |
| ros-perception/vision_opencv / foxy | **REUSE** | [image_geometry/image_geometry/cameramodels.py](https://github.com/ros-perception/vision_opencv/blob/72152d9d1d8edcfcafd707a1d0103810db8613ba/image_geometry/image_geometry/cameramodels.py) | `field_evidence.py` 用 cv_bridge 解码、PinholeCameraModel 读取内参/ROI/binning/射线，mono R=I 时同映射校正 RGB 与已注册深度。`readonly/image_decode.py` KEEP 为 Windows 数学/历史诊断后端。 |
| ros-perception/image_pipeline / foxy | **REPLACE_LATER** | [depth_image_proc/src/register.cpp](https://github.com/ros-perception/image_pipeline/blob/7dcd819d5d39ccacba6171969dd959967955b579/depth_image_proc/src/register.cpp) | 仅在驱动未提供注册深度且真实 depth→RGB 外参已知时使用 RegisterNode。当前不启动新节点、不造外参；非 mono/R≠I 或未注册深度输出 UNKNOWN。 |
| ros-perception/pointcloud_to_laserscan / foxy | **REPLACE_LATER** | [src/pointcloud_to_laserscan_node.cpp](https://github.com/ros-perception/pointcloud_to_laserscan/blob/21c8973506b559fbeaf662b181b8a0d2f0955658/src/pointcloud_to_laserscan_node.cpp) | 官方组件具有 target_frame、transform_tolerance、height/range/angular 参数。现场确认安装、点云 frame/外参、自遮挡参数、频率/CPU 后再切换现有导航输入；本轮保留 shared/navigation/perception/pointcloud_to_laserscan.py 离线参考，Gate B 用 sensor_msgs_py 读取真实点云。 |
| unitreerobotics/teleimager / main | **UNSUPPORTED** | [src/teleimager/client.py](https://github.com/unitreerobotics/teleimager/blob/ee4422b6e50ebe1f7448bfb4869fe1ae983fec37/src/teleimager/client.py) | 当前 TeleImageClient 与旧 ImageClient API 不同；图像传输不等于 ROS RGB-D/CameraInfo/header 同步来源。不得用视频流伪造深度或相机标定。本轮不接入、不开相机服务。 |
| unitreerobotics/xr_teleoperate / main | **KEEP** | [teleop/teleop_hand_and_arm.py](https://github.com/unitreerobotics/xr_teleoperate/blob/817fb00c63cde15e5f24a0f8fa08e1e33ed89d3b/teleop/teleop_hand_and_arm.py) | 保留为遥操作/图像消费参考；主入口导入 motion_switcher/Loco 等，不属于只读诊断依赖，禁止打包/运行。其 ImageClient 导入与本次 teleimager main 不匹配，不能假定两者最新分支兼容。 |
| Livox-SDK/livox_ros_driver2 / master | **KEEP** | [src/lddc.cpp](https://github.com/Livox-SDK/livox_ros_driver2/blob/21445540f0d100dc86a7e6df312dd70bbdb4afdf/src/lddc.cpp) | 维持机载驱动；Lddc 区分 PointCloud2 与 CustomMsg，Gate B 仅支持 sensor_msgs/PointCloud2。CustomMsg 在本工具 UNSUPPORTED，应记录原始数据，人工检查已存在的 PointCloud2 topic；不得覆盖驱动或自动切格式。 |
| ros2/rosbag2 / foxy | **REUSE** | [ros2bag/ros2bag/verb/record.py](https://github.com/ros2/rosbag2/blob/77f5a51b4d5cd70ea6a78d53cffe964e3b9afaf7/ros2bag/ros2bag/verb/record.py) | 官方 ros2 bag record/play 及 SQLite 原始存储。Foxy 支持 --qos-profile-overrides-path；不假定 Rolling --duration/新版 rosbag2_py。提取在 G1 由 rclpy.deserialize_message 完成，Windows 只读派生 JSON/NPY。 |

## 精确版本

- `ros2/geometry2` `foxy`：`d1dc38b8a0e706fbd67a800a241fee950fce39f4`
- `ros2/message_filters` `foxy`：`5042d46bee8d4e31f64fe5610c1c4c2401e62788`
- `ros-perception/vision_opencv` `foxy`：`72152d9d1d8edcfcafd707a1d0103810db8613ba`
- `ros-perception/image_pipeline` `foxy`：`7dcd819d5d39ccacba6171969dd959967955b579`
- `ros-perception/pointcloud_to_laserscan` `foxy`：`21c8973506b559fbeaf662b181b8a0d2f0955658`
- `unitreerobotics/teleimager` `main`：`ee4422b6e50ebe1f7448bfb4869fe1ae983fec37`
- `unitreerobotics/xr_teleoperate` `main`：`817fb00c63cde15e5f24a0f8fa08e1e33ed89d3b`
- `Livox-SDK/livox_ros_driver2` `master`：`21445540f0d100dc86a7e6df312dd70bbdb4afdf`
- `ros2/rosbag2` `foxy`：`77f5a51b4d5cd70ea6a78d53cffe964e3b9afaf7`

## Foxy API 边界

- Buffer(cache_time=None, node=None)、TransformListener(buffer, node)、lookup_transform(target, source, Time)；实时 provider 不建立第二套缓存。离线提取使用 Buffer.set_transform / set_transform_static 后按相机 header 时间查询。
- ApproximateTimeSynchronizer(fs, queue_size, slop, allow_headerless=False)。本轮未使用 queue_offset、sync_arrival_time 等后续版本参数。回调内部捕获异常，避免 Foxy 同步器锁被异常路径留住。
- CvBridge.imgmsg_to_cv2(msg, desired_encoding)、PinholeCameraModel.fromCameraInfo / rectifyImage / projectPixelTo3dRay；该版本射线为单位向量，不能把 unit ray 直接乘轴向深度。Windows 用已校正的 fx/fy/cx/cy 做轴向深度反投影。
- ROS CameraInfo 的 P 用于校正后内参。mono、R=I、P 无平移时，RGB 双三次校正，已注册深度用最近邻同映射；保留原始 K/D/R/P 与原始 RGB/depth NPY。非支持路径一律不授权距离或运动。
- tf2 的 latest 查询不自动证明新鲜；导出动态边 age/stale，静态链单独按原始 /tf_static 分类，不能把动态零时间戳当静态。相机 TF 逐帧按 header 查询，输出可用率；缺失链不补 identity。
- 本轮不安装 apt、不升级 ROS、不改 Livox 或导航服务。所有读取上游源码只用于审查，第三方源码不随诊断 ZIP 打包。
