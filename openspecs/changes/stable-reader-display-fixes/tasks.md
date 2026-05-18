# 任务清单：稳定版抓包显示修复

## 代码实现

- [x] `game/tiles.py`：新增 `tile_sort_key(tile_id)`，按万、条、筒、字和数字升序生成显示排序键，未知牌兜底。
- [x] `stable/protocol.py::_parse_ip_tcp_static`：从 TCP header 提取 `seq` 字段，加入返回 dict。
- [x] `stable/protocol.py::MJProtocol.__init__`：新增 `self.stream_next_seq: dict[tuple[str, str], int]`。
- [x] `stable/protocol.py::MJProtocol.process_packet`：在追加 payload 到 `stream_bufs` 前用 RFC 1982 modular 比较去重；新增 `_seq_lt` / `_seq_le` 静态辅助函数。
- [x] `stable/protocol.py::MJProtocol`：新增 `auto_detect_frames`，允许 npcap 模式在非配置端口上识别麻将业务帧。
- [x] `stable/protocol.py::NpcapCapture.sniff`：支持 `port_filter=0` 抓全 TCP，再交给协议层筛业务帧。
- [x] `stable/protocol.py::_decode_game_event`：`0x0216 hand_update` 支持从 `[0x01, tile]` 包尾补入右侧分离的第 14 张手牌。
- [x] `ui/main_window.py::_run_npcap`：npcap 模式改为抓全 TCP，并启用协议帧自动探测，避免二人模式业务包走非 7777 端口时抓不到手牌。
- [x] `stable/tracker.py::PacketStateTracker.snapshot`：仅对我方 hand 调用 `sorted(..., key=tile_sort_key)`。
- [x] `stable/protocol.py` / `stable/tracker.py`：修复副露/吃碰杠取牌，副露拿走的弃牌会从可见弃牌区移除，避免幽灵牌残留。

## 验证

- [x] 单元验证：重传包只解码一次，部分重叠包裁剪已处理前缀，seq 回绕正常。
- [x] 单元验证：非配置端口在 `auto_detect_frames=True` 时可解析麻将帧，默认关闭时仍忽略。
- [x] 单元验证：非麻将 payload 即使开启自动探测也会忽略。
- [x] 单元验证：真实二人模式手牌包 `...0139...` 会补入 `9筒` 作为第 14 张。
- [x] 单元验证：吃/碰/明杠会移除被拿走的弃牌，吃碰不扣剩余牌，杠才扣剩余牌。
- [x] 实测反馈：我方手牌顺序 OK。
- [ ] tcpdump 模式暂不考虑，后续需要时再验证。

## 不需要手动操作

本次变更不需要视觉兜底；稳定版读取仍走纯抓包链路。
