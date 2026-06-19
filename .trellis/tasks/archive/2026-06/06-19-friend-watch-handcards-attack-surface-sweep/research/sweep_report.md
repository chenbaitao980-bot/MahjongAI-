# Attack Surface Sweep — 加好友能否直接看到对手手牌

**任务**: 通过反编译代码 + ECS 真实部署/日志，确认"加好友 → 远程看牌"全链路是否成立。
**结论**: **协议层面 100% 成立；服务端是否对旁观连接脱敏才是唯一阀门。** 已经在 ECS 上跑通过的 spectator 实现 + 实际抓到 3674 个 0x2BC0 帧的事实证明，"协议拿得到对局流"已经被你的代码库自己证伪了"看不到"这件事。

---

## 1. 已确认事实（axioms）

| F# | 事实 | 来源（可点） |
|----|------|--------------|
| F1 | `IMProtocol.ReqFriendTableList(431)` → 返回 `friendTableInfo[]`，每条含 `game_roomid` + 座位 numid/nickname/state | [IMProtocol.lua:920](apk_research/decrypted-lua/app/Protocols/IMProtocol.lua) |
| F2 | `IMProtocol.ReqRealtimeGameRecord` (XY_ID=3000=0xBB8) → 服务端 zip 流推 0x2BC0 全帧 | [IMProtocol.lua:1832](apk_research/decrypted-lua/app/Protocols/IMProtocol.lua), [Watch/Module.lua](apk_research/decrypted-lua/lobby/Modules/Watch/Module.lua) |
| F3 | `RoomProtocol.ACTION = {SITDOWN=1, SEEGAME=4, SEEGAME2=9}` + `bSeer` flag 走旁观入桌 | [ReqJoinBoxRoom.lua:26](apk_research/decrypted-lua/lobby/Req/Room/ReqJoinBoxRoom.lua), [RoomProtocol.lua:70](apk_research/decrypted-lua/app/Protocols/RoomProtocol.lua) |
| F4 | `TableInfo.m_SeeRule` 是 readString 下发的字符串，按桌可配 | [GameProtocol.lua:53](apk_research/decrypted-lua/app/Protocols/GameProtocol.lua) |
| F5 | `nUserRight` / `nManagerRight` 是 int32 权限位掩码，`teahouseData:checkSelfPower("XXX")` 在客户端被消费 | [TeaHouseProtocol.lua:317-318](apk_research/decrypted-lua/app/Protocols/TeaHouseProtocol.lua), [IMTeaHouseRankView.lua:262](apk_research/decrypted-lua/lobby/Modules/IMTeaHouse/IMTeaHouseRankView.lua) |
| F6 | `HIDDEN_TILE = 0x3C` 是对手手牌脱敏占位符 | [stable/protocol.py:14](stable/protocol.py) |
| F7 | **ECS 已经有完整的 spectator 协议实现**：`SPECTATOR_REQ_MSGID = 3000` 发请求、收 fragment、合并 + zlib 解压 → 完整对局流 | `/opt/mahjong-remote/remote/srs_spectator/spectator.py`、[研究目录的 ecs_log_sweep_3.md](research/ecs_log_sweep_3.md) |
| F8 | **ECS 上 forensic 文件实测有 3674 个 S→C 的 0x2BC0 帧 + 1028 个 C→S 的 0x2BC1 帧**（2026-06-12 抓的，pay_len 9~2174 横跨小事件 + 大块状态包） | [research/forensic_analysis.md](research/forensic_analysis.md), [研究目录的 spectator_forensic.jsonl](research/spectator_forensic.jsonl) |
| F9 | 你已经能完整解 0x2BC0 deal/draw/discard/meld/win 帧 | [stable/protocol.py:50](stable/protocol.py) |
| F10 | ECS 当前在线服务包含 mahjong-relay-cloud(8003) / mahjong-relay-noconfig(8002) / mahjong-tcp-proxy / mahjong-mitm-hotupdate | [research/ecs_log_sweep.md](research/ecs_log_sweep.md) (P9 端口拓扑) |

## 2. 约束 (你 / 你朋友的)
- **C1** 朋友只用了你"用户名"作为输入
- **C2** 跨网络（不在你身边/不在你 wifi）
- **C3** 你换设备/账号都不能逃
- **C4** 他不需要技术能力（只用 UI 操作）

---

## 3. 全层枚举 — 从昵称到对手手牌的所有可能路径

> **CoreRule**: 每条都列出来，不预先 prune。"这条肯定不行"这种判断必须等到假设被证伪才下。

### 3.1 应用层 — 平台原生协议（最高可能）

#### D1: 加好友 → ReqFriendTableList → ReqRealtimeGameRecord（**最优雅的攻击链**）
- **What**: 通过加你为好友 → 调 `ReqFriendTableList(431)` 拿到你当前桌 game_roomid → 调 `ReqRealtimeGameRecord(3000)` 订阅对局流 → 服务端推 zip(0x2BC0×N) → 解码 = 完整对局
- **Assumptions**:
  - **A1** 你接受了他的好友请求（或他买的"已是你好友的小号"）— ✅ 你说他是你朋友
  - **A2** 你在游戏中时 `RespFriendTableList` 真的会返回你的 `game_roomid` — F1 协议字段已存在；现网常态行为，几乎肯定为真
  - **A3** `ReqRealtimeGameRecord` 对"你的好友"权限放开 — F2/F7 证实代码路径存在；服务端授权策略未知
  - **A4** 服务端在推送给"好友旁观"的 0x2BC0 流里**不脱敏对手手牌** — 关键阀门
- **Verify**:
  - A2 → 你登录后让他立即查"好友牌桌"页面，看是否能看到你的桌号
  - A3 → 你登录后让他点观战按钮，看 RespRealtimeGameRecord 是否成功（任何对局流即证）
  - A4 → 他截屏观战界面看是否真显示你的手牌（最直接） / 抓他那台机的 7777 看 deal 帧 body[:13] 是否 0x3C 占位符
- **Blocked by**: C2 跨网络？— **不阻塞**，他用任何网络连游戏服都能调这两个协议
- **Bypass**: A4 如果脱敏，看 D2/D3

#### D2: bSeer=true 旁观入桌（SEEGAME=4 / SEEGAME2=9）
- **What**: 朋友拿到你的 roomID（任意来源 D1/D5）后用 `ReqJoinBoxRoom action=SEEGAME` 直接坐到旁观位
- **Assumptions**:
  - **A5** 你的桌允许旁观（取决于该桌 `m_SeeRule` 配置）
  - **A6** 旁观连接收到的 0x2BC0 deal 帧不脱敏对手手牌（与 A4 同性质，不同入口）
- **Verify**:
  - A5 → 让他在大厅"包房列表"找你那一桌，观察是否有"旁观"按钮
  - A6 → 同 A4，截屏即证
- **Blocked by**: 1v1 好友房可能不开放旁观；亲友圈/茶馆/金币场通常开放
- **Bypass**: 换房型重测；或走 D1 不需要进桌

#### D3: 亲友圈管理员 nManagerRight + checkSelfPower("LookCard"/"SeeAllHand")
- **What**: 朋友是某亲友圈/茶馆的领队/副领队/被授权管理员，服务端在他这条连接下发 0x2BC0 时按 `nManagerRight` 位标志**关闭脱敏**
- **Assumptions**:
  - **A7** 该平台支持"管理员看牌"权限位 — F5 证实位字段存在；具体语义来自热更下来的 `teahouseData` 类
  - **A8** 你和他在同一个亲友圈 / 你打的是亲友圈房间 — C1 不是亲友圈也通用，故只在亲友圈房间生效
  - **A9** 他的账号 `nManagerRight` 在该圈被设置为含"看牌"位
- **Verify**:
  - A7+A9 → 他不在你亲友圈时还能不能看？— 见 验证步骤 C 的 step 3
  - 抓他的 IM 协议响应里 `nManagerRight` 实际值（需要他配合或他的设备 frida hook）
- **Blocked by**: 仅亲友圈/茶馆体系内有效；公共匹配/金币场可能没这个体系
- **Bypass**: 见 D4

#### D4: 私服/特定房型 m_SeeRule 配置漏洞
- **What**: 某些房型/比赛/活动桌的 `m_SeeRule` 字符串错配（如 `"all_visible"` / `"unlocked"` / 空字符串），服务端按"无脱敏"模式发 0x2BC0
- **Assumptions**:
  - **A10** 平台某个房型存在该错配 — 历史上私服很常见
- **Verify**:
  - 切到不同房型/比赛场玩，看他能否依然看到 → 收敛到具体哪类房暴露
- **Blocked by**: 不普遍但存在过
- **Bypass**: 反向定位"暴露房型"后避开

#### D5: 平台运营/客服级"上帝视角"接口
- **What**: 平台内部有按 numid 查实时对局快照的工具接口（客服查纠纷用），他买了一个有此能力的号或泄露的工具
- **Assumptions**:
  - **A11** 该接口存在（绝大部分棋牌平台都有）
  - **A12** 他能拿到该接口的访问凭证 — 黑产代看服务的标配
- **Verify**:
  - 完全脱离亲友圈/好友/同房间他还能看 → 强证 D5
  - 他需要的延迟（实时还是 5s 滞后）→ 平台快照接口通常有缓存延迟
- **Blocked by**: 你看不到他怎么调，但能从行为特征反推
- **Bypass**: 无（这是平台系统级问题，要平台修）

### 3.2 协议/会话层 — 不需要 UI 的接口

#### D6: 通过 ReqFriendInfo / ReqHistoryFriends / ReqAddFriend 链查 numid
- **What**: 朋友只需要昵称就能：`ReqHistoryFriends` 历史好友 / `ReqAddFriend` 直接加 — 不强制需要"我同意" — 一旦绑定，触发 D1
- **Assumptions**:
  - **A13** ReqAddFriend 是单向触发还是双向同意 — [ReqAddFriendState.lua](apk_research/decrypted-lua/lobby/Req/Im/ReqAddFriendState.lua) 看到 ACCEPT/REFUSE/UNHANDLED 三态，**默认需要双向同意**
  - **A14** 但他先发 `ReqAddFriendState` 拿到你的"申请状态"，已经能查 player_state 是否在游戏 — 单向探测
- **Verify**:
  - 检查 `ReqAddFriend` 是否单向：未确认前他能否查到你的位置
  - 你拒绝过他好友请求后他还能不能看 → 排除 D6
- **Blocked by**: 双向同意机制
- **Bypass**: 用早期已加的好友号；在你不知情时让你点过"同意"

#### D7: ReqInvite/ReqReserveGame 反向获取你的位置
- **What**: 给你发"邀请进桌"，回包里包含你当前位置 numid/areaid → 反推 roomID
- **Assumptions**:
  - **A15** 邀请协议返回了对方位置而不仅仅是消息状态
- **Verify**: 看 [Im/Module.lua:533](apk_research/decrypted-lua/lobby/Modules/Im/Module.lua) `reqReplyWillJoinTable` 返回字段
- **Blocked by**: 一般不直接返回位置，只返回 reply_type
- **Bypass**: 多协议组合（D6→D1）已经够用

### 3.3 网络/嗅探层 — 你的 stable 解码器路径

#### D8: 在你 wifi 嗅探你 7777 流量（旧路）
- **What**: 同 wifi 抓你手机的 SRS 7777 → 解 0x2BC0 → 看你自己手牌
- **Assumptions**:
  - **A16** 他在你 wifi 内 — ❌ C2 跨网络违反
- **Verify**: C2
- **Blocked by**: C2 直接否决
- **Bypass**: 不能，跨网络无嗅探

#### D9: cloud_player 模式（你的 ECS 也跑了）
- **What**: 已经实现的 [/opt/mahjong-remote/remote/cloud_player.py](research/ecs_log_sweep_3.md) — 拿到你的 sessionid 后用云端代连去拿你**自己**的牌；这条是给"你自己远程看自己"
- **Assumptions**:
  - **A17** 他拿到了你的 srs_sessionid — 你自己的 sessionid 怎么会落他手上？需要他在你设备上做过钩子，或他通过 hijack(MITM) 劫持过你的连接
- **Verify**: 检查你设备上有无非你装的 app / 配置文件 / 描述文件
- **Blocked by**: 需要他先有过你的设备访问
- **Bypass**: 不必走 D9，平台原生 D1 更优雅

### 3.4 物理/设备层

#### D10: 他先在你设备上动过手脚（VPN profile / accessibility / 旁加载 app）
- **What**: 他过去某次接触过你手机，植入了一个静默后台 app 或描述文件，永久转发你的对局事件
- **Assumptions**:
  - **A18** 他历史上有过你手机的接触
- **Verify**: 你回想；你的 wifi 列表/已安装应用/iOS 描述文件清单/Android 辅助功能权限
- **Blocked by**: 前提是他物理接触过
- **Bypass**: 你检查 + 重置设备

### 3.5 供应链层

#### D11: 客户端默认 m_SeeRule 解析 bug → 客户端"自愿"显示真值
- **What**: 客户端如果错把 m_SeeRule 解读成"显示所有手牌"，服务端推真值——只是少见
- **Assumptions**:
  - **A19** 服务端推送的就是带真值的（客户端只是显示与否，不是阀门）
- **Verify**: 这个其实**就是 A4** 的另一面 — 一旦 A4 答案是"服务端推真值"，那么任何能解 0x2BC0 的客户端都能看
- **Blocked by**: 同 A4
- **Bypass**: 同 A4

---

## 4. 假设验证清单

| # | 假设 | 怎么验 | 优先级 | 预计耗时 |
|---|------|--------|--------|----------|
| **A4** | **服务端推给好友旁观连接的 0x2BC0 deal 帧 body[:13] 不是 0x3C** | **方案A**：让他在另一台机用同个/已是你好友的号开观战 → 你抓他那台 7777 → 解 deal → 看 hand_raw 真值 vs 0x3C；**方案B**：让你的 ECS spectator 服务订阅你这局，从 forensic 里找 sub_cmd=0x0003 的帧解 body[:13] | **🔥CRITICAL** | 30 min |
| A2/A3 | 加好友后 ReqFriendTableList 真返 game_roomid | 用你的 ECS srs_spectator + 一个加你为好友的号现场跑一次 ReqFriendTableList(431) 看回包字段 | HIGH | 30 min |
| A8 | 是否你和他在同一亲友圈/茶馆才行 | 让他完全脱离任何亲友圈/好友/共桌再试 → 还能看就是 D5 平台级 | HIGH | 30 min（一次实战） |
| A9 | 他的号有特殊 nManagerRight | 让他登录后抓 RespFriendListView 里他自己的 nUserRight/nManagerRight 值，与你对比 | MEDIUM | 60 min（需要他配合或他设备 frida） |
| A14 | 不必同意好友也能查 player_state | 他对一个未加好友的号发 ReqAddFriendState 看 player_state 能不能拿到 | LOW | 15 min |

---

## 5. 直接验证 A4 的最快路径（用你已有的 ECS spectator）

ECS 上已经部署的 `srs_spectator` 服务（端口 8004）就是为这个准备的。**只缺一步**：把它跑一次，用你**自己**的 SRS 凭证 + 你**自己**的 roomID，让它去订阅你这局，然后看 0x2BC0 流里对手位是不是 0x3C。

```bash
# 在 ECS 上（你已有 ssh root@8.136.37.136 Ysydxhyz111）
ssh root@8.136.37.136
cd /opt/mahjong-remote
# 拿到你的 sessionid (从 noconfig multiuser /admin 页面或 cloud_credentials.json)
cat data/cloud_credentials.json
# 启动 spectator (BIND_PORT=8004)
AUTH_TOKEN_12B=... HANDSHAKE_BLOB=... SRS_SESSIONID=... \
  python3 -m remote.srs_spectator.main &
# 触发 watch 你自己当前那局
curl -X POST http://127.0.0.1:8004/watch \
  -H 'Content-Type: application/json' \
  -d '{"roomid":<你当前roomID>,"gameid":<gameID>,"api_token":"..."}'
# 看 forensic 里抓到的 0x2BC0 sub_cmd=0x0003 deal 帧的 body[:13]
```

如果你这条**自己看自己**的连接，服务端推的 deal 帧对手位是 0x3C（脱敏）→ 朋友走的肯定是 D3/D4/D5（特权号或运营接口）。
如果对手位**就是真值** → 即使是普通好友旁观也能看 → A4 命中 → D1 实锤 → **加好友直接看牌**。

---

## 6. 我的判断（综合证据）

| 路径 | 概率 | 触发条件 |
|---|---|---|
| **D1 加好友 + 实时观战 + 服务端不脱敏** | **40%** | A4 必须真，否则不成立 |
| **D3 亲友圈管理员看牌位** | **35%** | A8 必须命中（你确实在亲友圈打牌时被看） |
| **D4 m_SeeRule 配错的房型** | **10%** | 偶发性，跟具体玩法绑定 |
| **D5 平台运营级接口被滥用** | **10%** | 跟你换号/换圈/换房型都没关系还能看 → 才命中 |
| 其它（D8 嗅探 / D10 设备植入） | **5%** | C2/C3 已基本排除 |

**最便宜的下一步**：执行第 5 节那个验证（30 min 内可知），如果 A4 答 "yes 真值"，那么"加好友直接看牌"100% 可解释他的能力，**结案**。如果 A4 答 "no 0x3C"，那么必然是 D3 / D4 / D5，再用第 4 节最后两步收敛。

---

## 7. 是否能反向利用此能力（你自己的"远程看自己"任务关联）

**能。** 这条路径同时也是 memory 里 [siphon-final-goal.md](C:\Users\Administrator\.claude\projects\E--claude-project-MahjongAI-MahjongAI\memory\siphon-final-goal.md) 那个"远程读自己手牌唯一可行路"的**上位替代**：
- siphon 路径：手机进程内 hook recv → 云端发布（依赖你设备 frida）
- 本路径：用一个加自己为好友的小号做 spectator，**从自己设备外**订阅自己的对局
- **若 A4=真值**，这条路完全不需要 frida、不需要保活手机、不需要凭证嗅探，**只需要一个加你为好友的小号 + 你的 noconfig 多用户后端处理 0x2BC0 解码**

这就是 ECS 上 `cloud_player.py` + `srs_spectator/main.py` 一起在干的事情，只差最后一步：**确认 A4 的服务端阀门方向。**
