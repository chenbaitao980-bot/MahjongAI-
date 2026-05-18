# 任务清单：稳定版抓包显示修复

## 代码实现

- [ ] `game/tiles.py`：新增 `tile_sort_key(tile_id)`，按 万→条→筒→字 + 数字升序生成排序键，未识别牌兜底。
- [ ] `stable/protocol.py::_parse_ip_tcp_static`：从 TCP header 提取 `seq` 字段，加入返回 dict。
- [ ] `stable/protocol.py::MJProtocol.__init__`：新增 `self.stream_next_seq: dict[tuple[str, str], int]`。
- [ ] `stable/protocol.py::MJProtocol.process_packet`：在追加 payload 到 stream_bufs 前用 RFC 1982 modular 比较去重；新增 `_seq_lt` / `_seq_le` 静态辅助函数。
- [ ] `stable/tracker.py::PacketStateTracker.snapshot`：仅对我方 hand 调用 `sorted(..., key=tile_sort_key)`。

## 验证

- [ ] 单元验证：构造重传包数据流，确认重复帧只解码一次。
- [ ] 实测：完整对局中我方手牌 UI 显示与游戏画面 1:1 对照（顺序一致）。
- [ ] 实测：完整对局中弃牌序列与游戏画面 1:1 对照（无幽灵牌）。
- [ ] 回放脚本 `scripts/replay_stable_reader.py` 跑历史 events.jsonl 仍能正确重建状态。
- [ ] tcpdump 模式下同样验证一遍（确保 TCP 去重不破坏原模式）。

## 不需要手动操作

本次变更全部为代码改动，无需用户安装软件、调环境或操作模拟器。
