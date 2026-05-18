# 任务清单：防检测优化

## 代码实现

- [x] 更新 `openspecs/config.yaml` 添加防检测上下文。
- [x] 在 `requirements.txt` 中添加 `scapy>=2.5.0`。
- [x] 在 `stable/protocol.py` 中新增 `NpcapCapture` 类（含 L2→L3 自动回退）。
- [x] 重构 `StableCaptureThread.run()` 支持双抓包模式。
- [x] 在配置默认值中添加 `capture_mode` 和 `npcap_iface`。
- [x] 在 `stable_battle_panel.py` UI 中添加抓包模式选择下拉框。
- [x] 新建 `scripts/check_detection.py` 安全自检脚本。
- [x] 为 `build_tcpdump_command` 添加 `disguise_name` 参数。
- [x] 新建 `frida/gadget_config.json` Gadget 配置。
- [x] 新建 `frida/hook_recv.js` recv Hook 脚本。
- [x] 新建 `frida/setup_gadget.py` 自动化部署脚本。
- [x] 修复 `NpcapCapture` L2 `RuntimeError` 异常捕获（原代码只捕获 `OSError`）。
- [x] 修复 `NpcapCapture` L3 sniff 稳定性：添加 `timeout=2` 循环、保存 socket 引用以便 `stop()` 强制关闭、检测 L2 静默返回后回退 L3。
- [x] 增加 `_on_stable_stop_requested` 等待超时至 5 秒，防止快速重启时 socket 未释放。
- [x] 清理 `stable/` 和 `ui/` 目录下的 stale `.pyc` 缓存。

## 环境准备

- [x] npcap 驱动安装（含 WinPcap API 兼容模式，L2 抓包可用）。
- [x] scapy + frida-tools 安装到项目虚拟环境（frida 17.9.10）。
- [x] 确认网卡接口：WLAN `\Device\NPF_{BB42CC54-32EE-4972-A58B-BD4684AA5E8E}`。
- [x] 下载解压 `frida-gadget-17.9.10-android-x86_64.so`（26.5 MB）。
- [x] MuMu Root 已开启。
- [x] 安全自检：评分 SAFE（0 critical, 0 warnings）。

## 实测发现（2026-05-18）

- [x] 游戏进程确认运行：`com.xm.zjgamecenter`。
- [x] 游戏实际连接 `47.96.0.227:7777`，代码默认端口 7777 正确。
- [x] 模拟器内网 `10.0.2.15`，通过 NAT 出主机 WLAN `192.168.210.99`。
- [x] npcap L2 模式双向抓包验证通过：C→S 和 S→C 均正常捕获。
- [x] 端到端验证：npcap → IP 解析 → 协议解码，910+ 条协议消息。
- [x] npcap 模式下模拟器内安全自检 SAFE，`ps -A` 无任何抓包进程。

## 已完成（原待完成项）

- [x] 端口确认：游戏使用 `7777`，代码默认值正确，无需修改。
- [x] 验证主机侧 npcap L2 可双向捕获游戏流量（需安装 npcap 含 WinPcap 兼容模式）。
- [x] 端到端验证通过（npcap 模式 → 协议解码 → 消息 emit → UI）。
