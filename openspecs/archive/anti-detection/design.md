# 设计：防检测优化

## 现状

`StableCaptureThread` 通过 `subprocess.Popen` 启动 ADB 命令，在模拟器内以 `su -c tcpdump` 方式运行。所有流量在模拟器的 `wlan0` 接口上被捕获，通过 `adb exec-out` 传回主机。这会留下三个可检测特征：`tcpdump` 进程、root 权限提升、ADB 会话。

## 实测环境信息（2026-05-18 确认）

| 项目         | 值                                                          |
| ---------- | ---------------------------------------------------------- |
| 模拟器内网 IP   | `10.0.2.15`（NAT，通过 `10.0.2.2` 出主机）                         |
| 主机 WLAN IP | `192.168.210.99`                                           |
| 游戏服务器      | `47.96.101.155:5748`（实际端口 **5748**，非 7777/5749）            |
| ADB 设备号    | `emulator-5554`（非 `127.0.0.1:16384`）                       |
| scapy L2   | 不可用（npcap 未启用 WinPcap 兼容层）                                 |
| scapy L3   | ✅ 可用，`L3WinSocket`，5 秒 110 个 TCP 包                         |
| 默认网卡       | `\Device\NPF_{BB42CC54-32EE-4972-A58B-BD4684AA5E8E}`（WLAN） |

**关键发现：**
- 游戏实际使用 **5748** 端口连接服务器，项目代码中配置的 `7777` 已过时，需要更新。
- 模拟器走 NAT（`10.0.2.x` → 主机 WLAN），主机侧抓包看到的源 IP 是 `192.168.210.99`。
- scapy L2 不可用但 L3 完全正常，`NpcapCapture` 已实现 L2→L3 自动回退。

## 方案设计

### P0：主机侧 npcap 抓包

MuMu 模拟器的网络流量经过 Windows 主机网络栈（NAT），直接在主机上用 scapy + npcap 抓包。

- 在 `stable/protocol.py` 中新增 `NpcapCapture` 类，封装 `scapy.sniff()`。
- 先尝试 L2（支持 BPF 过滤），失败则自动回退到 L3（`L3WinSocket`，Python 层过滤端口）。
- `_dispatch` 方法从 scapy 包对象提取 IP 层，按目标端口过滤后交给 `PcapParser._parse_ip_tcp_static()`。
- `StableCaptureThread.run()` 根据 `capture_mode` 配置分发到 `_run_npcap()` 或 `_run_tcpdump()`。
- PcapParser 和 MJProtocol 代码无需修改。

### P1：安全自检脚本

`scripts/check_detection.py` 通过 ADB 在模拟器内执行检查并报告：
- 可疑进程名（tcpdump、frida、capture、hook、inject）
- 已知工具默认端口（27042、27043）
- `build.prop` 中的模拟器指纹字段
- `/proc/self/maps` 中的 frida-agent 内存映射
- `/data/local/tmp/` 中的残留文件

输出评分：安全（0 项）/ 警告（轻微）/ 危险（严重）。

**已验证：** 清理残留的 `frida-server`、`frida.log`、`tcpdump.log` 后评分为 SAFE。

### P2：tcpdump 进程伪装

`build_tcpdump_command` 增加 `disguise_name` 参数（默认 `.sys_health`）。首次运行时将 `/system/bin/tcpdump` 复制到 `/data/local/tmp/{disguise_name}` 并从该路径执行。进程列表中显示伪装名称而非 `tcpdump`。

### P3：Frida Gadget 框架

不运行 `frida-server`（可见进程 + 默认端口），改用 Gadget 模式：
- `frida-gadget.so` 重命名为 `.libsys_perf.so`
- 通过 `LD_PRELOAD` 在游戏进程启动时加载
- Script 模式配置指向 `hook_recv.js`，Hook `libc.recv()` 并将数据写入文件
- 无 frida-server 进程，无 27042 端口
- frida 版本 17.9.10，gadget 已下载解压（26.5 MB）

## 回滚方式

每一层都可独立回滚：
- P0：配置 `capture_mode: tcpdump` 即可恢复原有行为。
- P1：删除 `scripts/check_detection.py`。
- P2：去掉 `disguise_name` 参数（恢复原始 tcpdump 路径）。
- P3：删除 `frida/` 目录，停止使用 `LD_PRELOAD`。

## 已解决

- [x] 端口确认：实测游戏连接 `47.96.0.227:7777`，代码默认 `7777` **正确**（之前观察到的 `5748` 是其他连接）。
- [x] NAT 抓包验证：主机侧 npcap L3 模式可正常捕获模拟器 NAT 出的游戏流量（端到端测试 29 包 / 7 条协议消息）。
- [x] L3 sniff 稳定性：添加 `timeout=2` 循环 + socket 引用保存，解决 stop/restart 时 socket 未释放导致的 0 字节问题。
