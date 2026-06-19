# 15 真因候选 sweep — "ReqRealtimeGameRecord 不回包"

PoC v2 (game 7777) 和 PoC v4 (lobby 47.96.101.155:5748) 都 45s 静默无回包。我前面归因为"同 numid 不能旁观自桌的 hard wall"，但严格按 attack-surface-sweep CoreRule 重审：**这只是 15 个候选真因之一**，且没排除其他 14 个。

## H1 — 同 numid 不能旁观自桌

- **What**: 服务端拒绝 `request.numid in room.players` 的 watch 请求
- **Assumptions**: 服务端有此规则
- **Verify**: 用第三方 numid 测（C1 当前阻塞）
- **Bypass**: H2-H15 任一成立则 H1 不一定是真因

## H2 — appid 算错（=0），路由不到 frontend

- **What**: `lobby/Req/Watch/ReqRealtimeGameRecord.lua:56` 调 `getAppid(roomid)`：
  ```lua
  appid = SvrAppidList[roomid % len(SvrAppidList) + 1]
  ```
  我的 PoC 写死 0
- **Assumptions**: 服务端按 appid 路由到房间所在游服 frontend
- **Verify**: 抓主号 lobby 的 `RespOpenFriendList(409)` / `RespFriendList(414)`，查找 SvrAppidList 字段，按 935804 % len(list) + 1 算
- **Bypass**: 修对 appid 重测

## H3 — wire frame 缺 processid/appid 三元组

- **What**: lua native 调用 `tcp:sendMessage(processID=100, appID=appid, msgid=3000, body)`，是四元组。我们的 12B header `<HHHHI>` 只塞了 msg_type，processid/appid 完全没塞
- **Assumptions**: wire frame 实际编码方式与我们的 frame.py 不一致
- **Verify**: 抓主号大厅 RespFriendInfo(467) 等 IMProtocol 帧，解 wire bytes，对照 sub_type/extra 实际值
- **Bypass**: 重新逆向 wire format，processid 可能在 sub_type，appid 可能在 extra

## H4 — watch1006 强制 MatchLinkProtocol

- **What**: lua: `if lobbyJsonData.watch1006 then MatchLink else IMProtocol`
- **Assumptions**: 主号当前房型/区域配置 `watch1006=true` → 必须走 MatchLinkProtocol(processid=1006, appid=0)
- **Verify**: 抓主号 ConfigurationModule 拉的 lobby JSON，搜 watch1006 字段
- **Bypass**: PoC 改走 MatchLinkProtocol（XY_ID 相同 3000，仅 processid 改 1006）

## H5 — 缺 ReqJoinBoxRoom action=SEEGAME 前置

- **What**: lua 调用链：`Im/View.lua:875 → reqRealtimeGameRecord` 但前置必须 `setIsSeer(true)`，触发条件是先 `ReqJoinBoxRoom action=SEEGAME=4`
- **Assumptions**: 服务端要求该 numid 在加入房间前先标记为旁观者
- **Verify**: 看 lua client 完整 join → watch 流程的逻辑顺序
- **Bypass**: PoC v5 先发 ReqJoinBoxRoom(roomid=935804, action=4) 等 RespJoinTable，再发 ReqRealtimeGameRecord

## H6 — askid 验证

- **What**: 服务端可能要 askid 与某个 nonce/sequence 关联
- **Assumptions**: askid != random
- **Verify**: 抓主号 lobby 任何 askid 流，看是否递增 / hash
- **Bypass**: 复用主号最新 askid 的 +N 模式

## H7 — sticky routing 与主号现有连接冲突

- **What**: 主号现在 lobby 有活跃连接，第二条 PlayerConnect(同 sessionid) 被 frontend 当成"重连迁移"
- **Assumptions**: 服务端按 sessionid 做粘性路由，第二连接顶替第一连接
- **Verify**: 比对 PoC v4 PlayerData 的 protecturl 和主号实时 lobby 的 protecturl
- **Bypass**: 用不同 sessionid（C1 阻塞）/ 用不同源 IP

## H8 — identify 字段不匹配

- **What**: 我们用 `identify="020000000000"` 默认值；主号真实是 RC4 加密设备指纹
- **Assumptions**: 服务端把"identify mismatch"标记为非可信连接，watch 不放
- **Verify**: 抓主号实际 PlayerConnect 的 identify 字节
- **Bypass**: 复制主号 identify

## H9 — 主号"在游戏中" flag 阻止 watch

- **What**: lua client RX 过滤 `if position.gameAppID ~= 0 then return end`，服务端可能也对该 numid 当前在 game 时拒绝旁观
- **Assumptions**: 服务端有"该 numid 在 game frontend 持有连接"则拒绝任何 watch 请求
- **Verify**: 主号下场后立即重发 ReqRealtimeGameRecord 看是否回包
- **Bypass**: 主号下场（破坏 C2）

## H10 — SrsGroupID 错

- **What**: lua: `sendMsg(req, resp, srsGroupID=areaData:getSrsGroupID(), appid)`，第三参数指定路由组
- **Assumptions**: 服务端按 srsGroupID 路由到正确的 srs frontend
- **Verify**: 主号大厅查 areaData，找 srsGroupID（17:57 抓到 RespJoinTable.srsgroupid=5045）
- **Bypass**: extra 字段塞主号实测 srsGroupID=5045

## H11 — 真服 IP 不一样

- **What**: 47.96.101.155:5748/5749 是 tcp_proxy DEFAULT_LOBBY_PORTS，主号实际可能在 5749 或别的 IP
- **Assumptions**: 主号当前活跃 lobby IP/Port 可能不是 5748
- **Verify**: ss -tnp 看主号当前活跃 lobby 连接的实际目的 IP
- **Bypass**: 连主号实测的那个 IP

## H12 — 房间已结束 / 主号换桌

- **What**: roomid=935804 是 17:57 抓的，PoC v4 在 19:15，间隔 78 分钟，主号可能换桌或局结束
- **Assumptions**: 房间 935804 在 19:15 不再活跃
- **Verify**: 拉 ECS 实时主号最新 RespJoinTable
- **Bypass**: 用最新 roomid 重测

## H13 — payload 需加密

- **What**: 当前 `pack_frame(3000, struct.pack("<iiii",...))` 是明文 16 字节
- **Assumptions**: PlayerConnect 后所有 payload 必须用 sessionkey/m_key CFB 加密
- **Verify**: 抓主号 lobby C->S 任何 IMProtocol 帧 payload 是否密文（与已知协议结构对比熵值）
- **Bypass**: encrypt_payload(req_body) 后再 pack_frame

## H14 — server_port 与 client port 不匹配

- **What**: spectator 协议可能要走特殊 srs frontend
- **Assumptions**: 5748/5749 不是 spectator 入口
- **Verify**: 看 lua sendMsg 第三参数 srsGroupID 解析后是哪个 IP/Port
- **Bypass**: 复刻完整 dispatch 流程

## H15 — 服务端"该 numid 在 game"主动拒绝（H9 服务端版）

- **What**: H9 是 client 过滤，H15 是服务端规则。即只要主号现在在打牌，**任何二号连接（即使不同 numid）**都不能 watch 主号那桌
- **Assumptions**: 服务端"是否同 numid"和"是否在 game"是不同检查
- **Verify**: 主号下场后再发 ReqRealtimeGameRecord 看是否回包
- **Bypass**: 主号下场（破坏 C2）/ 用全新 numid

---

## 验证矩阵（按成本排）

| H# | 假设 | 工具 | 时间 | 命中后做什么 |
|---|---|---|---|---|
| H12 | 房间过期 | ECS 实时拉主号 roomid | <1 min | 重发 PoC v5 |
| H7 | sticky routing | 比 PlayerData.protecturl | <1 min | C1 阻塞，跳过 |
| H11 | 真服 IP 不对 | ss -tnp | <1 min | 改 PoC 目的 IP |
| H10 | SrsGroupID 错 | 5045 在 RespJoinTable 中已抓 | 1 min | extra 塞 5045 |
| H2 | appid 错 | 抓 RespFriendList 拿 SvrAppidList | 5 min | 算对 appid |
| H4 | watch1006 | 抓 lobbyJsonData | 5 min | 改 PoC 走 1006 路径 |
| H13 | payload 加密 | 比 lobby C->S payload 熵值 | 10 min | encrypt before pack |
| H3 | wire 缺 processid | 解主号实际 IMProtocol 帧 wire | 15 min | 重逆向 wire |
| H8 | identify 错 | 解主号 PlayerConnect | 15 min | 复制 identify |
| H5 | 缺 SEEGAME 前置 | 看 lua join 流程 | 20 min | PoC 加 ReqJoinBoxRoom |
| H6 | askid 验证 | askid 流 pattern 分析 | 30 min | 复刻 askid pattern |
| H9 | game flag | 主号下场后测 | C2 阻塞 | C2 阻塞 |
| H15 | game flag 服务端 | 同 H9 | C2 阻塞 | C2 阻塞 |
| H14 | server_port | 完整 dispatch 跟踪 | 60 min | 等 H10/H11 先验 |
| H1 | 同 numid 拒绝 | 第三方 numid（C1 阻塞） | C1 阻塞 | 等 H2-H10 全失败再说 |

**最便宜组合**：H12 + H7 + H10 + H11（4 分钟）→ 立刻可砍掉/确认 4 个

**最高 ROI**：H2 + H4 + H5（30 分钟）→ 大概率命中（覆盖 lua client 完整调用流程）

---

## 注意事项

- 不要再说"hard wall"——这是过早归因
- 每条候选都有"验证步骤"和"绕过路径"，不允许 silently skip
- C1 (小号不连热点) 和 C2 (主号不下线) 是用户硬约束，但 H1/H9/H15 之外的 12 个候选**完全不依赖**这两个约束
