# Capability: stealth-hardening

## Purpose

降低 MahjongAI 在游戏运行环境中的检测面：tcpdump 进程伪装、安全自检脚本、Frida Gadget 框架。

## Requirements

### 安全自检脚本

`scripts/check_detection.py` 应通过 ADB 连接模拟器执行以下检查：
1. 进程列表中是否有已知工具名（tcpdump、frida、capture、hook、inject、xposed）。
2. TCP 端口中是否有已知默认端口（27042、27043、8080）。
3. `getprop` 输出中是否有模拟器指纹字段（ro.hardware、ro.product.model、ro.kernel.qemu）。
4. `/proc/self/maps` 中是否有 frida-agent 或 gadget 内存映射。
5. `/data/local/tmp/` 中是否有已知工具二进制文件。

脚本应输出评分报告：安全（0 项发现）、警告（1-2 项轻微）、危险（任何严重项）。

### tcpdump 进程伪装

`build_tcpdump_command` 应接受 `disguise_name` 参数（默认：`.sys_health`）。生成的命令应：
1. 若伪装路径文件不存在，先将 tcpdump 复制到 `/data/local/tmp/{disguise_name}`。
2. 从伪装路径执行，而非 `/system/bin/tcpdump`。

### Frida Gadget 框架

#### 配置

`frida/gadget_config.json` 应配置 Gadget 为 script 模式，指向设备上可配置路径的 Hook 脚本。

#### Hook 脚本

`frida/hook_recv.js` 应：
1. Hook 游戏进程中 `libc.so!recv`。
2. 按游戏服务器文件描述符过滤（端口 7777 或配置值）。
3. 将捕获数据写入本地文件供主机消费。

#### 部署脚本

`frida/setup_gadget.py` 应：
1. 接受 ADB 路径和设备序列号作为参数。
2. 将重命名后的 gadget 库推送到设备。
3. 将 Hook 脚本推送到设备。
4. 提供使用 `LD_PRELOAD` 启动游戏的操作说明。
