# 稳定版抓包显示规格（增量）

本规格描述对已归档 `stable-packet-reader` 的两点修订。

## 需求

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
