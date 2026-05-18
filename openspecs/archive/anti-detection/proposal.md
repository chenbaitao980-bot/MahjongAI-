# 防检测优化

## 为什么要做

当前抓包方案在 MuMu 模拟器内以 root 权限运行 `tcpdump`，游戏反作弊系统可通过进程扫描、root 检测、模拟器指纹识别等手段发现。一旦被检测到，可能导致账号封禁和历史数据丢失。

## 变更内容

按优先级实施四层防检测：

1. **P0 — 主机侧 npcap 抓包**：在 Windows 主机上用 scapy+npcap 嗅探数据包，模拟器内零痕迹。
2. **P1 — 安全自检脚本**：自动扫描模拟器内可疑进程、端口、指纹等可被检测的特征。
3. **P2 — tcpdump 进程伪装**：将 tcpdump 二进制文件重命名后执行，进程列表中不显示 tcpdump。
4. **P3 — Frida Gadget 框架**：用 Gadget 注入替代独立 frida-server（无服务进程、无默认端口）。

## 不在范围内

- 不修改协议解码逻辑（PcapParser、MJProtocol）。
- 不修改策略/AI 决策引擎。
- 不修改现有视觉识别对战标签页。

## 成功标准

- npcap 模式下，模拟器内 `ps -A` 无任何抓包相关进程。
- npcap 模式下，events JSONL 输出与 tcpdump 模式对同一局对战结果一致。
- `check_detection.py` 在 npcap 模式下报告安全评分为 SAFE。
- 选择 tcpdump 模式时，原有功能正常工作。
