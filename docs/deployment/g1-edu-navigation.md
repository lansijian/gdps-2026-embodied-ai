# G1 EDU 现场连接、SSH 与导航部署

本文区分三台角色：

| 角色 | 本次开发机实测 | 职责 |
| --- | --- | --- |
| Cursor 开发电脑 | **Windows 10**, Python 3.11.4, **未安装 WSL**, **无 ROS 2** | 写代码、单测、dry-run |
| G1 机载计算机 | **未接入，参数未验证** | 建议运行实时 ROS 2 / DDS 节点 |
| 运动控制 | Unitree DDS `LocoClient` | 仅高层 `SetVelocity` / `StopMove` |

`192.168.123.164` 只是文档里常见候选地址，**不是**这台 EDU 的已确认 IP。

**禁止：** 猜测 SSH 用户名/密码、改网卡静态 IP（需你确认后再做）、覆盖机器人预装服务、发运动指令、把软件停车当成急停。

---

## 0. 本机检测结果（2026-10-16）

在 `E:\GDPS\competition` 上执行只读检查：

- `platform`: Windows 10 (22631)
- `wsl -l -v`: 未启用适用于 Linux 的 Windows 子系统
- `ros2`: 不在 PATH
- IPv4 摘录：
  - `WLAN 2`: `192.168.43.9`
  - `以太网`: `169.254.164.13`（链路本地 / APIPA，**不像已配置的机器人网段**）
  - 另有 VMware / ZeroTier / Tailscale 虚拟网卡

结论：现在**还不能** SSH 到 G1。请先用网线接到**已授权开发网口**，再在 PowerShell 里重跑预检。

---

## 1. 连接前检查

### Windows（当前开发机）

```powershell
cd E:\GDPS\competition
powershell -ExecutionPolicy Bypass -File .\scripts\g1\preflight.ps1
Get-NetAdapter
Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias, IPAddress, PrefixLength
```

期望（网线接好且机器人侧 DHCP/静态已通之后，**具体数字待你确认**）：

- 接到机器人的那块网卡 `Status = Up`
- 出现与机器人同网段的 IPv4（候选网段 `192.168.123.0/24`，未验证）
- 不再只有 `169.254.x.x`

若仍是 APIPA：先查线序、口位、机器人是否上电；**不要先改静态 IP**。若必须静态，把当前 `Get-NetIPConfiguration` 贴出来，确认后再改。

探测候选地址（仅在你明确要求时）：

```powershell
ping 192.168.123.164
arp -a
```

### 若以后安装 WSL2

- WSL2 是虚拟网卡，DDS 组播经常不通。
- 实时节点优先放在 **G1 机载 Ubuntu**，或改用原生 Ubuntu 电脑。
- 在 WSL 内跑：`bash scripts/g1/preflight.sh`

### 原生 Ubuntu 工控机

```bash
bash scripts/g1/preflight.sh
ip -br addr
nmcli dev
ls /opt/ros
```

---

## 2. SSH（参数由你填）

```bash
ssh <authorized-user>@<verified-robot-ip>
```

Windows OpenSSH：

```powershell
ssh <authorized-user>@<verified-robot-ip>
```

成功后**只读**：

```bash
hostname
uname -a
cat /etc/os-release
ip -br addr
python3 --version
ls /opt/ros
df -h
```

若 `ros2` 不在 PATH，先 source，再判断没有 ROS：

```bash
ls /opt/ros
source /opt/ros/humble/setup.bash   # 发行版以 ls 结果为准
ros2 doctor --report
ros2 topic list -t
ros2 node list
```

封装脚本（Linux/WSL/Git Bash）：

```bash
bash scripts/g1/ssh_readonly.sh <authorized-user> <verified-robot-ip>
```

日志写在 `logs/g1-ssh/`（已 gitignore）。不要把密码、私钥写进仓库或训练记录。

现场还要核对（只读）：

- `python3 -c "import unitree_sdk2py; print(unitree_sdk2py.__file__)"` 是否存在
- LiDAR：`ros2 topic list | grep -i -E 'livox|points|scan'`
- 里程计：不要假设 `/dog_odom`
- `ros2 topic echo /tf --once`（若有）
- 运动相关：`/api/sport/request` 是否存在；**存在也不等于已授权运动**

---

## 3. DDS / ROS 2 网络

| 问题 | 处理 |
| --- | --- |
| Windows 上无 ROS 2 | 本阶段只跑 Python 单测与 `scripts/g1/dryrun_local.py` |
| WSL2 组播 | 不要把 CycloneDDS 跨 Windows↔WSL↔机器人硬打通作为第一方案 |
| 机器人 ROS_DOMAIN_ID | 读现场值，不要改系统默认，除非你确认 |
| `ChannelFactoryInitialize(0, iface)` | `iface` 必须是机器人（或直连 Linux）上 `ip -br addr` 看到的口 |

推荐部署：

1. 开发电脑：Git + 单测
2. 机载：独立目录（例如 `/home/<user>/gdps-2026-embodied-ai`）跑 ROS 节点与 LocoClient
3. 开发电脑可 SSH 看 topic，**Phase 3 不发 cmd_vel 到 live backend**

---

## 4. 构建与部署（需你打字确认；发行版以 Phase 3 为准）

本机 Windows **不能** `colcon build`。不要默认 Humble：先 `ls /opt/ros`，再 source 实际目录。

```bash
ls /opt/ros
# source /opt/ros/<实测发行版>/setup.bash
bash scripts/g1/build.sh
# 提示后输入 BUILD
```

拷到机器人非系统目录（默认 **没有** `rsync --delete`）：

```bash
bash scripts/g1/deploy.sh <authorized-user> <verified-robot-ip> /home/<user>/gdps-2026-embodied-ai
# 提示后输入 DEPLOY
```

保护：拒绝 `/opt` `/usr` `/etc` `/boot` `/home` 及过浅路径；远端目录名必须是 `gdps-2026-embodied-ai` / `gdps-ws` / `gdps_g1_ws`。`--delete` 仅在远端已有 sentinel `.gdps-g1-deploy-root` 时才允许。不会安装内核模块，不会重启机器人。

---

## 4b. Phase 3 暂停点（当前步骤）

1. 本机只读：`powershell -ExecutionPolicy Bypass -File .\scripts\g1\preflight.ps1`
2. **接入开发网口后再跑一遍** preflight；不要猜测 IP/用户。
3. 你确认用户和 IP 之后：`bash scripts/g1/ssh_readonly.sh <authorized-user> <verified-robot-ip>`
4. 在完成 topic / SDK 记录前，**不要** launch 导航，**不要** live `SetVelocity`。

---

## 5. 分阶段在真机上跑什么

### Phase 3 — 连接诊断（无运动）

预检 + SSH 只读命令。禁止 `LocoClient.Move`、禁止 live adapter。

### Phase 4 — Dry-run 导航

机载（概念命令，topic 名以 Phase 3 为准）：

```bash
export PYTHONPATH=/home/<user>/gdps-2026-embodied-ai:$PYTHONPATH
source /opt/ros/<distro>/setup.bash
source /home/<user>/gdps-2026-embodied-ai/shared/navigation/ros2_ws/install/setup.bash
ros2 launch gdps_g1_navigation local_avoid_dryrun.launch.py
```

确认 `/gdps/nav_status` 在障碍靠近时出现 `decision=stop`，且 `mode=dry-run`。
**此时 mock/dry-run 不得发真实步态。**

若已有地图与 TF，可另开 Nav2 bringup（仍保持 dry-run 桥）：

```bash
ros2 launch gdps_g1_navigation nav2_bringup.launch.py map:=/path/to/map.yaml
```

无地图时只宣称 **局部避障**，不要写“已完成自主导航”。

### Phase 5 — 低速 live（必须你书面确认清单）

清单：场地安全、有人看护、硬件急停可用、原生步态正常、只有一个运动源、传感器与里程计健康、Watchdog 已在 dry-run 验证、可立即停止。

然后才允许：

```bash
export GDPS_G1_LIVE=1
# 仍需在代码/REPL 中 enable_live(token, "ENABLE LIVE MOTION")
```

顺序：读状态 → 零速度 → 短距 ≤0.1 m/s → 遇障停车 → 移障后人工确认再走 → 绕障/目标点。

软件停止：

```bash
bash scripts/g1/stop.sh
```

失联：主机 `heartbeat` 节点停止后，机载 `SafetySupervisor` 在 `heartbeat_timeout_s` 后软件停车。厂商 `SetVelocity(duration=1.0)` 超时行为**未在本仓库验证**，不能当作唯一安全网。

---

## 6. 静态 IP 方案（先讨论，不执行）

仅当 DHCP 失败且你确认口名后，示意（Ubuntu NetworkManager）：

```text
连接名 / 网卡: <from nmcli>
地址: <agreed, e.g. 192.168.123.200/24>
网关: 通常不要乱加
不要改机器人内部已有地址，除非官方文档要求
```

Windows：在“以太网”适配器上设 IPv4，地址与机器人同网段、不同主机号。执行前把 `Get-NetIPConfiguration` 发出来确认。
