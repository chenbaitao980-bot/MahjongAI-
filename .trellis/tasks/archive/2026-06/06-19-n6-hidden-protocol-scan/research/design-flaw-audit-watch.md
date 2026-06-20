# 设计漏洞审计：旁观/视野/房型规则

- **Query**: 审计反编译客户端 Lua 里旁观/视野/房型规则代码，找能让服务端改变 view filter（不再把对手手牌抹成 0x3c）行为的设计漏洞
- **Scope**: internal（纯离线只读 apk_research/decrypted-lua）
- **Date**: 2026-06-20
- **重要前提**：静态包里没有牌局场景源码（热更下载）。本审计覆盖的是**大厅/进桌/旁观入口层**的全部可控输入。真正序列化手牌的 game-process 逻辑在热更包，本文不能直接看到，但能精确定位"客户端发什么参数能驱动它走不同分支"。

---

## §1 旁观子系统逻辑梳理

### 1.1 客户端有【两条】完全不同的旁观路径（关键发现）

反编译实锤：客户端旁观分两条互斥路径，由**服务端下发的 lobby json 配置 `openGPWatch` 开关决定**走哪条。三处入口都是同一判断：

| 入口文件:行 | 判断 |
|---|---|
| `lobby/Modules/Im/View.lua:868` | `if lobbyJsonData.openGPWatch then 走A路 else 走B路` |
| `lobby/Modules/Im/Module.lua:1842` | 同上 |
| `lobby/Modules/JoinBoxRoom/Module.lua:92` | 同上（房满转观战时） |

**路径 A — 实时入座旁观（live SEEGAME）**：`openGPWatch=true` 时
`JoinBoxRoom:reqJoinBoxRoom(roomid, nil, true)`（`Im/View.lua:872`）
→ `ReqJoinBoxRoom.lua:26`：`repJoin.action = SEEGAME(4)`
→ 发 `RoomProtocol.ReqJoinTable`（XY_ID=13）到 **LobbyProcess**，再进 **真实 game-process**
→ 旁观者作为活动连接挂在跑着的游戏服务器上，**直接收 game-event 帧**（与坐着玩家同一条 game 帧流）。

**路径 B — 回放型旁观（record/replay）**：`openGPWatch=false`（或不存在）时
`Watch:reqRealtimeGameRecord(roomid, 0, gameid, chair_count)`（`Im/View.lua:875`）
→ `ReqRealtimeGameRecord.lua`：发 `IMProtocol.ReqRealtimeGameRecord`（XY_ID=3000）到 **boxdata 服务**
→ 返回 zlib 压缩的 record payload（分包 current/total，merge 后 inflate）。

> **这正是 H16 穷举针对的对象**：H16 测的是服务端"推 game-event 时把非归属 hand_raw 抹 0x3c"。这个穷举基于已观测的帧流——很可能是路径 B 的 record 帧 + 主号自己桌的 round_start 帧。**路径 A（live SEEGAME 直连 game-process 的旁观帧流）是否被同样的 filter 覆盖，是本次审计暴露的最大未验证面。**

### 1.2 watch1006 两条路由差异

`ReqRealtimeGameRecord.lua:41` 和 `ReqUnwatchRealtimeGameRecord.lua:29`：再有一个服务端配置 `watch1006`：
- `watch1006=true` → 用 `MatchLinkProtocol.ReqRealtimeGameRecord`（processid=**1006**），`appid=0`
- `watch1006=false` → 用 `IMProtocol.ReqRealtimeGameRecord`（processid=**100**），`appid = roomid % #appidList + 1`

**两个协议的 bostream/bistream 字节完全一致**（已逐字段比对 IMProtocol.lua:1833-1895 vs MatchLinkProtocol.lua:516-578）：请求 `askid/room_id/offset/before_round`，响应 `askid/flag/room_id/max_offset/current/total/zip/payload_size/payload`。差异只在**路由到哪个服务进程**（IM 进程 vs MatchLink/比赛场进程）。这两个不同服务端实现各自的 filter 可能不一致。

### 1.3 收包处理（两条 record 路由共用逻辑）

`Watch/Module.lua:66-102`（onRespRealtimeGameRecord / onRespRealtimeGameRecord1006）：
- `zip==1` 的包被当作分片回放数据交给 ReqProtocol 累积；`zip~=1` 直接 return（实时增量帧另走）
- 玩家自己在游戏中（`position.gameAppID~=0`）时**丢弃**旁观下发——说明 record 帧和 live 帧是分流的。

---

## §2 客户端可控的可见性输入（关键）

列出所有"客户端能传、可能影响服务端可见性决策"的字段。**标注是否值得验证**。

| # | 字段 | 所在请求 | 文件:行 | 客户端怎么填 | 服务端可能怎么用 | 验证优先级 |
|---|---|---|---|---|---|---|
| 1 | `action` = SEEGAME(4)/SEEGAME2(9)/CHANGETOSEEGAME(6) | `RoomProtocol.ReqJoinTable` (XY_ID=13) | RoomProtocol.lua:70-80,236; ReqJoinBoxRoom.lua:26 | 客户端硬编码 `bSeer and SEEGAME or SITDOWN`，可任意改成 9 或 6 | 决定服务端把你登记成"旁观位"还是"座位"，进而决定下发哪套帧 | **高** |
| 2 | `action` (game-process 版) 同上枚举 | `GameProtocolGT.ReqPlayerAct` (XY_ID=11016) | GameProtocolGT.lua:147-188 | `bos:writeUInt32(self.action)`，客户端可任意填 4/6/9 | 进 game-process 后切换座位↔旁观状态；CHANGETOSEEGAME=6 是"坐着的变旁观" | **高** |
| 3 | `bSeer` (bool) | `TeaHouseProtocol.ReqCreateTableAutoSit` | TeaHouseProtocol.lua:1329,1372 | `bos:writeBool(self.bSeer)` 末字段 | 比赛场/茶馆建桌即入座时声明旁观身份 | 中 |
| 4 | `acOtherInfo` / `logicData` / `gamerule` / `roomrule` (任意字符串) | `ReqJoinTable` / `ReqCreateTable` | RoomProtocol.lua:207,206,131,130 | 客户端拼字符串（现仅放 GPS 经纬度） | 服务端解析逻辑扩展字段——可能藏未文档化的 kv（如 seer=1） | 中 |
| 5 | `before_round` (0/1) + `offset` | `Req(Match/IM)RealtimeGameRecord` | IMProtocol.lua:1839; ReqRealtimeGameRecord.lua:46 | `isDelay and 1 or 0`；offset 客户端给 | 决定取实时还是历史段；不同 offset/round 组合可能命中"未过滤的历史快照" | 中 |
| 6 | `room_id` | record 请求 | 同上 | 客户端任意填 | 能否填**自己不在场**的任意房间号拉 record（越权旁观） | 中 |
| 7 | `hardwareflag` / `clienttype` / `clienttypecustom` | ReqJoinTable | RoomProtocol.lua:222,221,229 | 客户端任意填（PC/TV/WEB/自定义） | 服务端可能对"web 观战端/TV 端"用不同序列化（演示端往往全亮） | 低-中 |
| 8 | `ntype` (客户端游戏方式) | ReqJoinTable/ReqCreateTable | RoomProtocol.lua:225 | `bos:writeUInt8(self.ntype)` | 标示"客户端游戏方式"，语义不明，可能含调试/演示模式 | 低 |

**不可控（已排除为攻击面）**：`m_right`(GameProtocolGT.lua:303,351)、`nUserRight`/`nManagerRight`(TeaHouseProtocol.lua:317-318,394-398) —— 全是**服务端→客户端只读**字段，请求里没有对应可写项，客户端无法伪造权限位让自己变管理员。但它们的**存在证明服务端有按 right 位分支的逻辑**（见 §4 候选3）。

---

## §3 房型/规则审计

### 3.1 m_SeeRule（旁观规则字符串）

`GameProtocol.TableInfo`(GameProtocol.lua:53,74,93)：桌子信息里有 `m_SeeRule`（"旁观规则"）字符串字段，与 `m_JoinRule`/`m_GameRule` 并列。这是**服务端下发**的桌级旁观规则。
- 静态包里没有任何 lua **解析/分支 m_SeeRule 内容**的代码（牌局场景在热更包）。
- 语义未知：可能编码"是否允许旁观/旁观能看几家牌"。**这是房型放开视野的最可疑配置载体。**

### 3.2 SEEGAME 三档枚举的语义差

`RoomProtocol.ACTION` & `GameProtocolGT.ReqPlayerAct.ACTION`：
- `SEEGAME=4` — 普通旁观（桌上有人才可旁观）
- `CHANGETOSEEGAME=6` — **坐着的变成旁观**
- `SEEGAME2=9` — 新增旁观（空桌也可旁观）

客户端目前只用 4（ReqJoinBoxRoom.lua:26 写死）。6 和 9 走的是不同服务端分支，**6（先坐下再变旁观）尤其可疑**——见 §4 候选4 状态机漏洞。

### 3.3 明牌/教学/演示房型搜索结果

搜 `明牌/亮牌/看牌/视野/教学/演示` 在 decrypted-lua 全树：**无任何"明牌房/教学房/演示房"房型定义**。`AreaData.lua`/`GameSub.lua`/`AreaConfig.lua` 里房型由 gameid + 服务端下发的 rule 字符串驱动，房型定义本身也在服务端/热更。
- 结论：静态包**不能证否**存在明牌房型，只能说客户端没有硬编码的明牌入口 UI。明牌玩法（若存在）由 `m_GameRule`/`m_SeeRule` 字符串编码，需 live 抓包看真实 rule 串。

### 3.4 openGPWatch / watch1006 配置来源

两个开关都**只被读取、从不被客户端写入**（grep 全树确认 openGPWatch 仅 3 处读、0 处写）。来源是 `Configuration` 模块的 `getConfigJsonData(LOBBY,"lobby")`——服务端下发的 lobby json。意味着**服务端可以对单个账号/区下发 openGPWatch=true，强制该号走 live SEEGAME 路径**。这也是"朋友凭用户名看牌"最可能的运营侧解释：给特定号开了 live 旁观位。

---

## §4 设计漏洞候选（assumption-first）

> 遵循 attack-surface-sweep CoreRule：不写"行不通"，只写需要的假设 + 验证步骤。

### 候选 1 ★最高 ROI — Live SEEGAME 旁观帧流可能未被 H16 filter 覆盖
- **What**：强制走路径 A（`openGPWatch` 分支），以 `action=SEEGAME` 直连 game-process 当 live 旁观者，收坐着玩家同一条 game-event 帧流。
- **假设**：H16 穷举针对的是 record/replay 帧（路径 B）+ 自己桌 round_start。服务端给 **live 旁观连接**下发帧时，可能复用"发给桌内玩家"的序列化路径而**漏掉对旁观者的 hand 抹除**（或抹除逻辑只在 record 导出器里，不在 live 推送器里）。
- **怎么验证**：
  1. 抓包确认目标号 lobby json 是否含 `openGPWatch`；若无，MITM 在 lobby json 里注入 `openGPWatch=true`（热更 MITM 已有覆盖 NetConf 的能力，注入 json 同理）。
  2. 触发"房满转观战"或好友列表点旁观 → 抓 `ReqJoinTable action=4`（XY_ID=13）→ 进 game-process 后抓 game-event 帧。
  3. 比对帧里非归属玩家 hand 字段：是 0x3c 还是真实 tile_id。
- **被什么挡**：若服务端的 hand 抹除在 game-process 推送层统一做，live 旁观也会 0x3c。
- **怎么绕**：见候选 4（状态机）和候选 2（SEEGAME2/CHANGETOSEEGAME 走不同分支）。

### 候选 2 — SEEGAME2(9) / CHANGETOSEEGAME(6) 走未充分测试的服务端分支
- **What**：客户端写死只发 `SEEGAME=4`；手工构造 `ReqPlayerAct action=9`（空桌旁观）或 `action=6`（坐着变旁观）。
- **假设**：三档旁观是不同时期叠加的代码（注释"新增旁观"），服务端对 6/9 的 view filter 实现可能不如 4 完整（漏改一个分支）。
- **怎么验证**：进 game-process 后用 `GameProtocolGT.ReqPlayerAct`(XY_ID=11016) 分别发 action=6/9，抓返回帧的 hand 字段。需要先能给 game-process 发包（Frida 注入或 MITM 改写客户端发的 action 值——后者最简单：把 ReqJoinBoxRoom.lua:26 / ReqPlayerAct 的 action 改 4→9）。
- **被什么挡**：服务端可能对未授权 action 直接拒绝（RespPlayerAct flag=SHOW_MESSAGE）。
- **怎么绕**：先合法 SEEGAME=4 进场，再 CHANGETOSEEGAME=6 切换（候选4）。

### 候选 3 — 管理员/领队视角（nManagerRight / m_right 位）
- **What**：比赛场/茶馆有 `nManagerRight`/`nUserRight`（TeaHouseProtocol）、game-process 有 `m_right`（PlayerInfo）。这些是服务端按身份下发的权限位。领队/管理员视角很可能服务端**对高 right 位玩家不抹手牌**（运营查牌需求）。
- **假设**：服务端序列化 hand 时判断 `if viewer.right & MANAGER then 发真牌 else 抹0x3c`。"朋友凭用户名看牌"= 朋友号被授予了某 right 位。
- **怎么验证**：
  1. 抓自己号 `RespTeaHouseInfoByPlayerType` 的 `nManagerRight`/`nUserRight` 值（TeaHouseProtocol.lua:394-398），抓 game-process `PlayerInfo.m_right`（GameProtocolGT.lua:351）。
  2. 找一个**能看到牌的朋友号**，对比抓它的 right 值差异 → 定位是哪个 bit。
  3. 客户端**无法伪造** right（请求里无此字段）；验证目标是确认"这条路存在 + 是哪个 bit"，绕过需服务端侧授予（创建自己的茶馆当领队，自动有 manager right）。
- **被什么挡**：right 服务端鉴权，客户端伪造不了。
- **怎么绕**：自建茶馆/比赛场当领队，看领队对自己房间的旁观是否解除抹除——这是**合法获得高 right 的唯一路径**，ROI 取决于领队 right 是否真解 view filter。

### 候选 4 — 状态机漏洞：先入座拿视野再切旁观
- **What**：`CHANGETOSEEGAME=6`="坐着的变成旁观"。先以**玩家身份正常入座**（action=SITDOWN，服务端给你自己的真手牌视野），开局后发 `ReqPlayerAct action=6` 变旁观，但服务端可能**没重置已建立的 per-seat 可见性状态**。
- **假设**：服务端把"该连接能看哪些 seat 的牌"在入座时初始化一次；CHANGETOSEEGAME 只改座位占用，没重算 visibility filter → 旁观状态下仍持有入座时的视野（但入座视野只含自己牌，对偷对手牌无直接帮助）。**更危险变体**：4 人桌坐满、你坐 1 号，开局后变旁观，若服务端按"旁观看全部"逻辑且没清你的 seat 绑定，可能既看自己又被当旁观补发其他 seat。
- **怎么验证**：合法入座一局 → 发 action=6 → 抓变旁观后服务端补发的帧，看是否含此前看不到的 seat hand。
- **被什么挡**：服务端变旁观时强制 reset filter / 踢出重连。
- **怎么绕**：配合候选2的 9，或在切换瞬间的时序窗口抓帧。

### 候选 5 — 越权拉任意房间 record（room_id 无归属校验）
- **What**：`Req(Match/IM)RealtimeGameRecord.room_id` 客户端任意填。填**自己从未参与**的房间号拉 record。
- **假设**：record 服务端可能不校验"请求者是否该房间参与者/好友"，只要 room_id 存在就返回完整 record。若 record 本身是**导出时已抹 0x3c 的过滤版**，越权也只拿到抹过的；但若某些房型（比赛场已结束局）导出**完整未过滤**版（赛后复盘需求），则越权 + 历史 offset 能拿真牌。
- **怎么验证**：用自己号对一个**不认识的活跃房间号**发 record 请求（offset=0 实时、offset=max 历史、before_round=1），抓返回 payload 解码看 hand。已有 stable 解码器可还原（见 memory: stable 从 pcap 已还原完整手牌）。
- **被什么挡**：服务端校验归属 → flag=NOT_GOOD 或"旁观数据不存在"。
- **怎么绕**：先加好友再拉（缩小到好友房），或针对比赛场已结束局。

### 候选 6 — acOtherInfo / logicData 隐藏 kv 注入
- **What**：`ReqJoinTable.acOtherInfo`/`logicData` 是自由字符串扩展字段，现仅放 GPS。服务端解析可能识别未文档化的 key（如 `bSeer='1'`、`viewAll='1'`、`debug='1'`）。
- **假设**：扩展字段解析器对未知 key 宽容，存在调试/内部 key 能放开视野。
- **怎么验证**：在 acOtherInfo 里追加候选 key（`seer='1';viewall='1';debug='1';`）抓返回。低成本可穷举几组。
- **被什么挡**：解析器只认 GPS key，其余忽略。

---

## §5 判定与 ROI 排序

**存在值得 live 验证的设计漏洞候选——是。** 静态分析无法看到 game-process 序列化（热更包），但已精确定位"客户端能驱动服务端走的不同分支"。按 ROI 排序：

| 排名 | 候选 | ROI 理由 | 需要的验证手段 |
|---|---|---|---|
| 1 | **候选1 Live SEEGAME 帧流** | H16 穷举可能只覆盖 record 路径B；live 路径A 是全新未验证面，且已有 MITM 注入 lobby json 的能力直接打开 openGPWatch | MITM 注入 `openGPWatch=true` + 抓 game-process 帧（**真机+抓包**） |
| 2 | **候选3 管理员/领队视角** | 最符合"朋友凭用户名看牌"的现象；自建茶馆当领队是合法拿高 right 的唯一路径 | 抓自己 vs 能看牌朋友的 right 值对比；自建茶馆测领队视野（**真机+抓包**） |
| 3 | **候选4 CHANGETOSEEGAME 状态机** | 时序漏洞经典面；客户端只需把 action 4→6 即可试 | MITM 改写 action 值 / Frida 发包（**真机+抓包**） |
| 4 | **候选2 SEEGAME2/6 未测分支** | 多档旁观叠加易漏改 filter | 同候选3，改 action→9 |
| 5 | **候选5 越权拉 record** | 已有 stable 解码器可即时验证 payload；纯请求改 room_id 即可试，无需进 game | 改 room_id 发 record 请求（**抓包，可半离线复用已有 pcap 工具**）— **最低成本可先做** |
| 6 | **候选6 acOtherInfo kv 注入** | 命中概率低但成本极低 | MITM 在 acOtherInfo 追加 key |

### 需真机/抓包验证的假设（不能纯离线证实）
- 所有候选的"服务端实际抹不抹手牌"判定 —— game-process 序列化在热更包，必须 live 抓帧。
- 候选1：openGPWatch live 路径下 game-event 帧的 hand 字段是否 0x3c。
- 候选3：哪个 right bit 解 filter（需对比有/无看牌权限的两个号）。
- 候选5：record 服务端是否校验 room_id 归属 + 是否存在未过滤的历史导出。

### 建议下一步（最低成本先行）
**先做候选5**（改 room_id 拉 record，半离线可用已有 stable 解码器验证），同时准备候选1 的 MITM 注入 `openGPWatch=true`（复用现有热更 MITM 框架）。这两个不需要 Frida、改动最小，能最快判定 record/live 两条路是否各自漏了 filter。

---

## 附：关键文件清单

| 文件 | 作用 |
|---|---|
| `apk_research/decrypted-lua/lobby/Modules/Watch/Module.lua` | 旁观子系统主逻辑、两条 record 路由收包 |
| `apk_research/decrypted-lua/lobby/Req/Watch/ReqRealtimeGameRecord.lua` | record 请求(路径B)，watch1006 路由分叉 |
| `apk_research/decrypted-lua/lobby/Req/Room/ReqJoinBoxRoom.lua:26` | bSeer→action=SEEGAME，live 旁观入口(路径A) |
| `apk_research/decrypted-lua/lobby/Modules/JoinBoxRoom/Module.lua:92` | openGPWatch 分叉(A vs B) |
| `apk_research/decrypted-lua/lobby/Modules/Im/View.lua:868-879` | openGPWatch 分叉主入口 |
| `apk_research/decrypted-lua/app/Protocols/RoomProtocol.lua:70-80,187-239` | ACTION 枚举 + ReqJoinTable(action 可控) |
| `apk_research/decrypted-lua/app/Protocols/GameProtocolGT.lua:147-188` | ReqPlayerAct(game-process 内 action 可控)；PlayerInfo.m_right |
| `apk_research/decrypted-lua/app/Protocols/GameProtocol.lua:53,74` | TableInfo.m_SeeRule 旁观规则字符串 |
| `apk_research/decrypted-lua/app/Protocols/TeaHouseProtocol.lua:317-318,1329,1372` | nManagerRight/nUserRight；ReqCreateTableAutoSit.bSeer |
| `apk_research/decrypted-lua/app/Protocols/IMProtocol.lua:1833-1933` / `MatchLinkProtocol.lua:516-616` | 两条 record 协议(字节一致，仅 processid 100 vs 1006) |
