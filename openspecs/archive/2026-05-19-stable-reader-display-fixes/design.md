# 设计：稳定版抓包显示修复

## 现状

- `PcapParser._parse_ip_tcp_static` 只提取 `src/dst/payload`，丢弃了 TCP `seq` 字段。
- `MJProtocol.process_packet` 按 `(src, dst)` 维护 `stream_bufs`，把每个新 TCP 包的 payload **无条件**追加到缓冲并扫描帧。npcap 在链路层抓到的 TCP 重传包会被当成新数据二次处理，应用层无从感知。
- `PacketStateTracker.snapshot()` 直接复制 `players[pid].hand` 列表，列表顺序是协议字节流中的原始顺序。

## 实测证据

| 实际 | 识别 | 备注 |
|------|------|------|
| `四万 一条 一条 五条 一筒 五筒 六筒 六筒 七筒 八筒 九筒 九筒 白` | `五筒 一筒 五条 九筒 白 六筒 九筒 一条 六筒 八筒 一条 七筒 四万` | 多重集一致，顺序不同 |
| 弃牌 `东 二筒 一万 四条 九条 南` | `东 二筒 一万 四条 四万 九条 南` | 中间多 1 张 `四万` |

## GitNexus 影响范围确认

- `MJProtocol.process_packet` 上游：
  - `ui/main_window.py::_run_tcpdump`、`_run_npcap.on_ip_packet`
  - `scripts/replay_stable_reader.py::_iter_messages`
- `PacketStateTracker._resolve_tiles` 上游：仅 `tracker.apply` 和 `rebuild_from_history`，再上一层是 `scripts/replay_stable_reader.py::replay`。
- `snapshot()` 调用方：`stable_battle_panel.set_snapshot`、`main_window._refresh_stable_snapshot`。

**结论**：所有改动都在 `stable/protocol.py`、`stable/tracker.py` 内部，方法签名不变，回放脚本和 UI 无需同步修改。

## 方案设计

### 修复 1：手牌排序

新增 `game/tiles.py::tile_sort_key(tile_id) -> tuple`：
- 花色权重：`m=0, s=1, p=2, z=3`（万→条→筒→字）
- 同花色按数字升序，未识别牌排到最后

在 `PacketStateTracker.snapshot()` 中，仅对**我方手牌**调用 `sorted(hand, key=tile_sort_key)`。对面手牌为隐藏状态、弃牌按时间序、副露按抓包序，均不改变。

内部状态 `players[pid].hand` 保持协议原序——`_apply_game_event` 中的增删牌逻辑（`hand.append(tile)`、`_remove_one(hand, tile)`）依赖列表语义，不受顺序影响。

### 修复 2：TCP 序号去重

**1) 抓包层补字段** — `PcapParser._parse_ip_tcp_static` 增加 `seq` 字段：

```python
seq = struct.unpack(">I", tcp[4:8])[0]
return {..., "seq": seq, "payload": payload}
```

**2) 协议层去重** — `MJProtocol` 新增 `stream_next_seq: dict[(src, dst), int]`，`process_packet` 改造为：

```python
seq = int(pkt.get("seq") or 0)
payload = bytes(pkt["payload"])
key = (str(pkt["src"]), str(pkt["dst"]))

prev_next = self.stream_next_seq.get(key)
if prev_next is not None:
    # seq 之后期望的下一个 byte 序号
    end_seq = (seq + len(payload)) & 0xFFFFFFFF
    # 完全已处理过（含 32 位回绕处理简化为 modular 比较）
    if _seq_le(end_seq, prev_next):
        return []  # 整包重传，跳过
    if _seq_lt(seq, prev_next):
        # 部分重叠，砍掉已处理的前缀
        offset = (prev_next - seq) & 0xFFFFFFFF
        payload = payload[offset:]
        seq = prev_next

self.stream_next_seq[key] = (seq + len(payload)) & 0xFFFFFFFF
buf = self.stream_bufs.get(key, b"") + payload
# 后续帧扫描逻辑不变
```

辅助函数 `_seq_lt(a, b)` / `_seq_le(a, b)` 用 RFC 1982 风格的 modular 比较（`(a - b) & 0xFFFFFFFF` 的高位判符号），处理 32 位 seq 回绕。

**乱序处理简化**：如果 seq 超前 `prev_next`（中间丢包或乱序），我们直接更新 `prev_next` 并把这个 payload 完整加入缓冲。代价是中间空缺会被忽略——但游戏帧首字节是 `0x40/0x80` 魔数，缓冲扫描有自同步能力，最坏情况只是丢一帧。

### 不做的事

- 不做"帧字节去重"备用方案。TCP seq 去重已经在源头解决，再加一层只增加误判风险。
- 不引入完整的 TCP 重组（如 reassembly），保持轻量。

## 风险与回滚

| 风险 | 评估 | 缓解 |
|------|------|------|
| TCP seq 回绕（32 位） | 单局对战的传输量远小于 4 GB，理论可忽略 | RFC 1982 modular 比较已覆盖 |
| 乱序包导致丢帧 | 局域网+服务器直连场景几乎无乱序 | 帧魔数自同步，丢一帧不致命 |
| 第一个包带 seq=0 但实际是非零 SYN 状态 | 我们只在抓到第一个 payload 包后初始化 `prev_next`，无影响 | 直接以首包 seq 为基准 |
| 排序破坏副露/弃牌时序 | 仅排序 hand，弃牌/副露不动 | 测试覆盖 |

回滚：把 `snapshot()` 中的 `sorted(...)` 改回 `list(...)`，移除 `stream_next_seq` 相关分支即可。两处改动互相独立。

## 待解决

- [ ] 是否需要把"内部 hand 也按协议序保留 + 显示时单独排序"扩展到 `to_battle_state()`？AI 决策对手牌顺序不敏感，初版按现状不动。
