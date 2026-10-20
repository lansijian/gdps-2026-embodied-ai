# 第三阶段实际验证记录（2026-10-20）

以STAGE3_SPEC.md F1–F6为实机设计输入。开发过程中未连接G1、未安装到机器人、未修改原厂服务/时钟、未发送真实SDK运动指令。OOM仅实现并在合成环境执行缓解措施，不能声称已解决。

## 本机记录

Windows/Python3.11：工作空间合同/脚本/阶段回归140项、既有robot_control/navigation回归104项；它们是离线逻辑检查，不是ARM64或硬件证明。9个Shell脚本经Git Bash bash -n检查；Python3.8语法、XML/YAML、7包metadata与源归档manifest/隐私排除随测试覆盖。PowerShell部署脚本以实际AST检查。日志保存在logs，源码包不含机器人日志/真实站点配置。

## 原生Foxy CI记录

代码8913b18255d0a6e28ebbdef9e5927fb47a3b10d2在运行39394662324完成两个架构×两个RMW的四组记录：Ubuntu20.04容器、系统Python3.8、Foxy，原生ARM64及x86_64，CycloneDDS/FastDDS。每组7个包构建、6个launch入口发现、139项合同、3项负向启动、实际BE/RELIABLE→offset→scan、合成SLAM/地图/AMCL/Nav2/FollowWaypoints/动态故障与退出检查均完成。

CI URL：https://github.com/lansijian/gdps-2026-embodied-ai/actions/runs/39394662324

末尾正式配置别名/旧入口识别和安装entry_points校验正在以最终代码重新运行CI，最终SHA/运行/各组结果写入docs/ci/stage3-release.json；该摘要存在前不能把旧SHA结果冒称新SHA结果。最终汇总会据实际CI状态更新本段。

合成负载：20,064点×32-byte stride约10Hz，原始cloud/dog_odom发布RELIABLE，odom定时器800Hz、IMU200Hz。观测速率与延迟见真实artifact，定时器设定不等于实收速率。ARM64使用navigation入口但allow_live=false，x86使用navigation_dryrun；两者均无SDK导入/写调用。FollowWaypoints用测试地图内两个近点验证action/客户端汇总，不是G1实际巡航。

首次原生运行暴露并修正：Foxy附加--ros-args、Foxy无RaiseError动作、内核30MB缓冲限制（容器隐藏rmem_max时改为独立socket探测）、bridge误用Node.executor、Foxy action名/FollowWaypoints大小写。失败运行保留在GitHub，不改写成成功。

## 证据解释与待验证

- CI检查的是合成环境和所安装Foxy版本，不是机器人自编译~/cyclonedds_ws的完整ABI/配置认证。
- DDS模板请求30MB；CI内核不足时使用明确记录的受限副本，不修改sysctl，不能把该结果写成30MB配置在G1通过。
- RSS低于阈值的合成测试不证明实机长期不OOM。真实OOM缓解效果、每次offset值/漂移、两种机器人业务闭环、精标定/足迹、SDK有限租期与独立急停均见STAGE3_G1_PENDING.md。
- 真实输出后端只在显式allow_live与真实接口/domain参数下惰性初始化。所有测试保持默认关闭，不自动FSM/BalanceMode/站立或低层关节。
- 原始dirty工作树和Stage3示教工作树保持独立；本轮只提交/推送当前导航特性分支，没有合并main。
