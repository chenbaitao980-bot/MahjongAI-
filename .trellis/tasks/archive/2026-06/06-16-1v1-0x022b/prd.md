# 好友房 1v1 手牌解码（0x2bc0 sub_cmd 0x022b）

## Goal

让好友房 1v1 模式的手牌能在 noconfig 多用户页 / 手牌面板正常刷出。当前金币局可读牌，但好友房读不出（hand_raw=None）。

## Root Cause（已用真机数据坐实，见 research/live-frames-2026-06-16.md）

- 好友房 1v1 的起手发牌用 **0x2bc0 内层 sub_cmd=0x022b**，而 stable/protocol.py 只处理 0x0003/0x0216/0x021A/0x021B/0x0218/0x021F/0x0220，没有 0x022b 分支 → 起手手牌从未进 tracker。
- 0x022b payload 结构：`<2B sub_cmd=0x022b><2B data_len> 10000000 00 0d <13字节instance手牌> 00 ...尾部其它数据`
- 只有**第一个 0d 块**是玩家自己的 13 张手牌（instance id 唯一性验证：仅 block1 无重复 id）。1v1 服务器只下发本人手牌。
- 解码：`tile = _GAME_INSTANCE_TILE_IDS[(byte-1)//4]`（条→万→筒→字）。
- 验证样本：block1 = `1m 2m 5m 3p 3p 3p 5s 5s 5s 6s 6s 7s 9s`（待用户确认与游戏内一致）。

## Requirements

0. **[首要/阻塞]** 修复游服代理跨连接共用旧 session key（见 research/root-cause-stale-session-key.md）：让 `TcpProxy` 游服代理**每条连接新建** `GameS2CDecryptor` + `GameTapDecoder`（+ presence 状态），与大厅 `s2c_rewriter` 工厂一致。这是当前"好友房/第二局起完全无数据"的真正根因；不修则 0x022b 永远拿不到明文。
   - 给 `TcpProxy` 加 per-connection `on_bytes` 工厂；`build_game_proxy` / `DynamicGameProxyManager` 改为每连接造新解码器。
   - 不破坏大厅、presence、push、C→S 透传。

1. stable/protocol.py 增加 sub_cmd **0x022b** 处理：从 payload 取首个 `0d`(=13) 前缀块的 13 字节，instance 解码为手牌，作为起手手牌事件（trusted hand，与 0x0216 同等地位）。
2. 兼容现有增量：起手后摸/打（0x021A/0x021B 已支持）继续维护手牌，使面板实时刷新。
3. 不破坏金币局（0x0003/0x0216）现有路径——只新增分支，不改旧分支。
4. GAME_SUB_NAMES 补 0x022b 命名（如 "deal_1v1"）。

## Non-Goals

- 不解对手手牌（1v1 服务器也不发）。
- 不做座位映射（0x022b 只含本人，无歧义）。
- 0x2bc0 加密变体（本链路是明文，不涉及）。

## Acceptance Criteria

- [ ] 用户确认 block1 解码 = 游戏内起手牌。
- [ ] 解析 0x022b 起手帧 → tracker 得到 13 张手牌，hand_trusted=True。
- [ ] 好友房 1v1 实战：手牌在多用户页 / 面板刷出并随摸打更新。
- [ ] 金币局回归不受影响（0x0003/0x0216 仍正常）。
- [ ] 新增单元测试：用 research 里的真机 block1 帧断言解出 = 1m2m5m3p3p3p5s5s5s6s6s7s9s。

## Definition of Done

- stable/protocol.py + 单测通过；ECS 部署 tcp-proxy 重启；真机好友房验证刷牌。

## Risks

- 0x022b 尾部结构（`0113 0134..` 等）含义未知，可能在某些局形（如带百搭/暗杠）下首块不是 13 张——需保留对 `0d` 长度的健壮判断（非 0x0d 时跳过，不硬切）。
