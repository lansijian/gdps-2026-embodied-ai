# Stage 3 时间策略

F1采信：偏差每次上电变化、会话内稳定。默认offset，前10个有效header采样delta=系统time.time()-原stamp，中位数锁定本次偏差，10帧全部不转发；第11帧起使用原stamp+offset，保留采样间隔。cloud/odom/IMU分别估计到系统墙钟域，不从一源的偏差猜另一源。

校正后再执行新鲜度、future、乱序、主机时钟跳变检查。raw_streams保留原header偏差，offsets报告实际值；30帧delta最大最小差>50ms WARN，不偷偷更新offset。cloud/直接TF odom在启动30秒不足10帧时明确报错退出。

preserve用于已同步场景；receive_time已deprecated，仅供诊断，会影响健康标志。没有硬编码69.8或4883，也不修改系统时钟。offset对齐不等于已验证采样同步/deskew，实际传输延迟和外参仍须G1验收。clock_preflight始终审计原始时间，看到原始偏差应保留记录，不要求把它改为“原始同步通过”。

原始发布端均RELIABLE（F2）；项目订阅BEST_EFFORT/depth5，内部cloud_timed发布BEST_EFFORT/depth10。官方转换器只接内部云，Nav2与RViz仅消费scan/map/path。详见STAGE3_DEPLOY.md。
