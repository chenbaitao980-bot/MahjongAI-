# 稳定版抓包显示规格（增量）

本规格描述对已归档 `stable-packet-reader` 的两点修订与一项兼容性约束。

> **状态**：本 change 已实施完毕（tasks.md 全部勾选），下列 Requirement 已通过 `/opsx:sync` 等价操作合并进主规范 `specs/stable-reader/spec.md`。保留本文件作为「修订意图」的历史记录，归档前用 `## MODIFIED Requirements` 段头让冲突预检能正确识别这是修订而非新增。

## MODIFIED Requirements

### Requirement: 手牌显示排序

`PacketStateTracker.snapshot()` 返回的 `players[local_player]["hand"]` 应按以下顺序排序：

1. 花色优先级：万（m）→ 条（s）→ 筒（p）→ 字（z）
2. 同花色按数字升序（字牌按 `1z..7z` 升序）
3. 未识别牌 ID 排到最后

对面玩家的 `hand` 字段始终为空或隐藏，不参与排序。`discards`（弃牌）和 `melds`（副露）必须保留时间/抓包原序。

`PacketStateTracker` 内部的 `players[pid].hand` 列表保持协议解码原序，确保 `_apply_game_event` 中的牌增删逻辑不受影响。排序仅在 `snapshot()` 出口完成。

#### Scenario: 我方手牌按花色数字排序

- **WHEN** `snapshot()` 被调用且 local_player 的协议解码顺序乱序（如 `5p 1p 5s 9p 7z 6p 9p 1s 6p 8p 1s 7p 4m`）
- **THEN** 输出 `hand` 字段为 `4m 1s 1s 5s 1p 5p 6p 6p 7p 8p 9p 9p 7z`（万→条→筒→字，同花色升序）

#### Scenario: 对面玩家 hand 不参与排序

- **WHEN** `snapshot()` 处理非 local_player 的玩家数据
- **THEN** `hand` 字段保持为空或隐藏值，不调用排序

#### Scenario: 内部状态保留协议原序

- **WHEN** 排序后 `_apply_game_event` 被调用处理新事件
- **THEN** 它读到的 `players[pid].hand` 仍是协议解码原序，事件处理逻辑不受排序影响

### Requirement: TCP 重传去重

`PcapParser._parse_ip_tcp_static` 应在返回 dict 中提供 TCP `seq`（无符号 32 位）。

`MJProtocol` 应维护每个 TCP 流（`(src, dst)` 元组键）的 `next_expected_seq`，并在 `process_packet` 处理新包时：

1. 完全已处理（`seq + payload_len <= next_expected_seq`，modular 比较）：跳过整个包，返回空列表。
2. 部分重叠（`seq < next_expected_seq < seq + payload_len`）：截掉前缀已处理部分，从 `next_expected_seq` 开始处理。
3. 完全新数据或乱序超前：正常处理，更新 `next_expected_seq = seq + payload_len`。

比较运算必须使用 RFC 1982 风格的 modular 算术，正确处理 32 位 seq 回绕。

#### Scenario: 重传包完全跳过

- **WHEN** 收到 `seq=1000, payload_len=200` 的包，且 `next_expected_seq=1300`
- **THEN** `process_packet` 返回空列表，不将该 payload 追加到 `stream_bufs`

#### Scenario: 部分重叠裁剪

- **WHEN** 收到 `seq=1000, payload_len=500` 的包，且 `next_expected_seq=1200`
- **THEN** 跳过前 200 字节，从 offset 200 开始处理 payload，并更新 `next_expected_seq=1500`

#### Scenario: seq 32 位回绕

- **WHEN** 收到 `seq=0` 的包，且 `next_expected_seq=0xFFFFFF00`
- **THEN** RFC 1982 modular 比较判定为「新数据」（而非「已处理」），正常处理

### Requirement: 兼容性

- npcap 和 tcpdump 两种抓包模式共用同一份去重和排序逻辑。
- 回放脚本 `scripts/replay_stable_reader.py` 与 UI 接口签名不变。
- `to_battle_state()` 输出格式不变（AI 决策对手牌顺序不敏感，无需排序）。

#### Scenario: 两种抓包模式行为一致

- **WHEN** 同一份原始 TCP 字节流分别由 npcap 和 tcpdump 模式喂入
- **THEN** 解码事件序列、手牌排序结果、TCP 去重行为均完全相同

#### Scenario: 回放脚本接口签名不变

- **WHEN** 现有 `scripts/replay_stable_reader.py` 调用 `PacketStateTracker.snapshot()`
- **THEN** 返回字段结构和键名不变，仅 `players[local_player]["hand"]` 顺序按新规则排序
