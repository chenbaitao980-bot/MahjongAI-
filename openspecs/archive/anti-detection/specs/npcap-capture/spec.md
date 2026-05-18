# npcap 主机侧抓包规格

## 需求

### 抓包源

npcap 抓包模式应使用 scapy 的 `sniff()` 函数配合 npcap 后端，在 Windows 主机上捕获 TCP 数据包，按配置的游戏服务器端口进行过滤。

### 接口选择

npcap 抓包应接受可选的网卡接口名。为空时使用 scapy 默认接口。用户可通过 `scapy.get_if_list()` 查看可用接口。

### 数据管线兼容

捕获的数据包应转为原始 IP+TCP 字节，通过现有 `PcapParser` 和 `MJProtocol` 管线处理，不修改这两个类。

### 双模式支持

`StableCaptureThread` 应支持通过 `stable_reader.capture_mode` 配置切换两种模式：
- `"npcap"`：主机侧抓包，使用 `NpcapCapture`（默认）。
- `"tcpdump"`：模拟器内抓包，使用现有 `build_tcpdump_command` + subprocess。

### 配置项

`stable_reader` 下新增配置键：
- `capture_mode`：`"npcap"`（默认）或 `"tcpdump"`。
- `npcap_iface`：npcap 网卡接口名（空字符串 = 自动选择）。

### 界面

稳定版对战面板应显示抓包模式下拉框，允许用户在启动抓包前切换 npcap 和 tcpdump 模式。

### 文件持久化

两种模式应使用相同的输出格式和目录结构保存原始 pcap 和 events JSONL 文件。
