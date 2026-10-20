# Stage 3 运行边界

节点启动与允许真实运动分开。非命令安全site问题为WARN+健康状态，允许粗标定定位调试；速度/加速度/命令超时硬上限仍Blocked。mapping启动只要求cloud基础流量健康30秒，其他模式检查运行链路。粗标定/未知足迹/场地未确认使healthy=false，bridge预览归零。

navigation提供显式SDK后端，但allow_live默认false；dry_run模式不能使能。SDK接口/domain无虚构默认，要求显式提供。后端只发送有限租期SetVelocity，不调用FSM、BalanceMode、站立/趴下或低层关节。独立worker中RPC超时/错误粘性锁止，不能把SDK失联停止当成独立物理急停已验证。

TwistStamped必须robot_center且新鲜，legacy默认false。源速度/健康publisher必须唯一，map→odom有效、传感器/TF健康与障碍条件满足才允许预览/显式输出。运动互斥沿用/tmp/gdps_g1_motion.lock。

预检仅停止明确匹配的同用户旧导航进程，保护当前launch祖先与宇树原始DDS/雷达进程；不改服务/时钟。重复TF owner、旧scan残留、旧服务重启均明确失败。资源watchdog只看本launch后代；独立终端RViz通过去点云显示减负，但不在该PID集合中。

所有实机使能、独立急停、足部/负障碍、制动与实际SDK租期效果见STAGE3_G1_PENDING.md。开发测试没有连接G1或发出真实运动指令。
