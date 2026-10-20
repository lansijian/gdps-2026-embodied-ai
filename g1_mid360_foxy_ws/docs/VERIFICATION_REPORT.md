# 第三阶段实际验证记录（2026-10-20）

本轮未连接G1、未安装到机器人、未修改原厂服务/时钟、未发送真实SDK运动指令。设计输入采信STAGE3_SPEC.md F1–F6。已实现并在CI应用OOM缓解措施；不能声称实机OOM已解决。

## 最终代码与执行记录

测试代码：`49a483a383989c11a18464be40e565e1921b5dfc`。
GitHub运行： https://github.com/lansijian/gdps-2026-embodied-ai/actions/runs/39395322718 。

| 原生架构 / RMW | 七包构建、140合同、11安装入口、6 launch、3负向启动 | BE/RELIABLE→offset→scan两组 | ROS集成 | 结论 |
|---|---|---|---|---|
| ARM64 / CycloneDDS | 完成 | 完成 | 28/28，包括航点与正常退出 | 主目标合成检查完成 |
| x86_64 / CycloneDDS | 完成 | 完成 | 28/28 | 主目标合成检查完成 |
| ARM64 / FastDDS | 完成 | 完成 | 完成9项，航点阶段超时；出现cloud/scan收包下降与TF过旧 | 对照未验收 |
| x86_64 / FastDDS | 完成 | 完成 | 完成26项，生命周期关闭超时 | 对照未验收 |

**该workflow整体结论是failure，来自两组FastDDS集成失败；不能写成四组全部成功。** 默认产品目标仍是CycloneDDS，FastDDS仅保留显式诊断入口，不能推荐为已验证替代。ARM64与x86两组FastDDS失败阶段不同，不能合并描述为同一种航点失败。

四份原始artifact下载后均以GitHub元数据SHA256核验，并保存在logs/release-stage3-*；摘要与逐项结果见docs/ci/stage3-release.json及四份分组JSON。原始ZIP与源码分开交付，源码不含日志/地图/真实站点数据。尾部交付commit仅更新报告/文件清单，实际运行代码SHA以本段为准。

## 负载与覆盖范围

全部输入均标记SYNTHETIC_TEST，隔离domain87，Ubuntu20.04/Foxy容器、系统Python3.8。ARM64原生runner使用navigation入口但allow_live=false，x86使用navigation_dryrun，均没有SDK导入/运动写调用。

负载：20,064点×32-byte stride约10Hz；cloud/dog_odom原始发布RELIABLE，odom定时器800Hz、IMU200Hz。源定时器不等于实收频率。RViz GUI未在CI启动。

CycloneDDS两组完成：源/scan/TF、offset、SLAM非空地图、occupancy/posegraph保存、AMCL重载、七个生命周期ACTIVE、Navfn非空规划、DWB与Stamped安全预览、官方FollowWaypoints与客户端汇总、障碍标记/停障、cloud/odom断流、过期/未来/错误frame/不支持布局、TF/heartbeat丢失、重复TF owner、SDK写次数零、生命周期清理与进程正常退出。

航点场景是合成地图中的两个近点，用于验证真实action/包装器/结果，并非机器人真实巡航。动态障碍场景证明合成代价地图标记与预览归零，不代替G1实际绕行闭环。故障末次快照会包含±5秒注入引起的delta波动，不可解读为正常链路或G1漂移。

DDS模板请求30MB；CI内核受限时，启动显式WARN并记录受限副本，未改sysctl。不能把CI结果写成G1的30MB配置通过。health保留末次进程RSS快照；本次artifact未采集完整RSS时序到工作空间，因此不据此报告进程峰值或长期不泄漏。

## 本机与安装检查

Windows/Python3.11工作空间140项、既有robot_control/navigation104项完成；9个Shell脚本实际bash -n无语法错误，PowerShell部署脚本AST无错误。离线检查覆盖Python3.8语法/XML/YAML、offset边界、TF投影、旧节点匹配与factory排除、DDS副本/内核cap、RSS PID范围、Stamped拒绝、SDK有限租期/过期命令/待完成RPC互斥、归档manifest与执行位/安全时间戳。

原生CI额外检查11个已安装入口可执行、可导入/调用；元数据检查不创建节点，也不导入SDK。默认SDK关闭，只有显式navigation allow_live与真实interface/domain后才能惰性初始化。代码不自动切FSM/BalanceMode/站立或控制低层关节。

## 修复过程与限制

早期失败原样保留：Foxy --ros-args解析、Foxy不含RaiseError动作、隐藏rmem_max与接收缓冲能力、Node.executor与SDK pool重名、Foxy /FollowWaypoints大小写。先前8913代码的四组成功仅作历史记录，不能覆盖本最终候选的FastDDS失败。

实际自编译~/cyclonedds_ws的ABI/配置、每会话offset、OOM缓解、真实标点/巡航/纸箱绕行、精标定/足迹、SDK租期/超时与独立急停须在G1验收，见STAGE3_G1_PENDING.md。FastDDS对照失败根因未在本轮定位，不等同于证明发生OOM。

原始dirty checkout状态保持，所有开发提交只在导航特性分支；没有合并main，没有声称创建了新PR。
