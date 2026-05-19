# Capability: stable-reader

## Purpose

稳定版抓包读取器：通过 adb exec-out + tcpdump（或 npcap）捕获游戏 TCP 流量，解码为结构化麻将事件，驱动策略分析。

## Requirements

### 抓包采集

稳定版读取器必须在已配置设备、网卡接口与服务端口上，通过 `adb exec-out` 运行 tcpdump 进行抓包。

### 协议解码

稳定版读取器必须将 pcap 字节解码为 TCP 负载，重组麻将协议帧，并产出 deal、hand update、draw、discard、kong、win 的结构化事件。
稳定版读取器必须将 `0x0003 deal` 视为不可信开局标记，不得由该负载初始化手牌或财神。
稳定版读取器必须仅从可信 `0x0216 hand_update` 的前 `count` 张解码手牌，并保留尾部字节为非手牌元数据。
稳定版读取器必须按 stable nibble 映射解码牌值（`0x1*` 万，`0x2*` 条，`0x3*` 筒，`0x4*` 风牌，`0x5*` 三元牌）。
稳定版读取器必须将包含 `0x72` 暗抓标记的 `0x021A` 视为隐藏抓牌，不得为该事件产出可见牌值。

### 映射修正

当原始牌值无法解析时，稳定版读取器必须将其显示为未知映射候选。用户将其绑定到标准 MahjongAI 牌 ID 后，绑定结果必须保存，并对当前历史进行回放重建。

### 分析门控

当且仅当满足以下条件时，稳定版读取器才可触发策略分析：财神已知、当前回合为我方、我方有效手牌数为 14。

### 回放兼容

对保存的 `events_*.jsonl` 进行离线回放时，必须优先基于 `raw_hex` 重解码，以确保历史抓包能够按最新解析逻辑进行验证。

### 手牌显示排序

`PacketStateTracker.snapshot()` 返回的 `players[local_player]["hand"]` 应按以下顺序排序：

1. 花色优先级：万（m）→ 条（s）→ 筒（p）→ 字（z）
2. 同花色按数字升序（字牌按 `1z..7z` 升序）
3. 未识别牌 ID 排到最后

对面玩家的 `hand` 字段始终为空或隐藏，不参与排序。`discards`（弃牌）和 `melds`（副露）必须保留时间/抓包原序。

`PacketStateTracker` 内部的 `players[pid].hand` 列表保持协议解码原序，确保 `_apply_game_event` 中的牌增删逻辑不受影响。排序仅在 `snapshot()` 出口完成。

### TCP 重传去重

`PcapParser._parse_ip_tcp_static` 应在返回 dict 中提供 TCP `seq`（无符号 32 位）。

`MJProtocol` 应维护每个 TCP 流（`(src, dst)` 元组键）的 `next_expected_seq`，并在 `process_packet` 处理新包时：

1. 完全已处理（`seq + payload_len <= next_expected_seq`，modular 比较）：跳过整个包，返回空列表。
2. 部分重叠（`seq < next_expected_seq < seq + payload_len`）：截掉前缀已处理部分，从 `next_expected_seq` 开始处理。
3. 完全新数据或乱序超前：正常处理，更新 `next_expected_seq = seq + payload_len`。

比较运算必须使用 RFC 1982 风格的 modular 算术，正确处理 32 位 seq 回绕。

### 兼容性

- npcap 和 tcpdump 两种抓包模式共用同一份去重和排序逻辑。
- 回放脚本 `scripts/replay_stable_reader.py` 与 UI 接口签名不变。
- `to_battle_state()` 输出格式不变（AI 决策对手牌顺序不敏感，无需排序）。
