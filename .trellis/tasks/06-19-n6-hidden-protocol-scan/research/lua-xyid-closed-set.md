# Lua XY_ID Closed Set — Client-known Protocol Catalog

- **Query**: 扫遍 `apk_research/decrypted-lua/app/Protocols/*.lua`，提取**所有**已知 XY_ID(msg_type)；区分协议(processid)；标注 wire 已观察过的子集
- **Scope**: internal — APK 解密 lua 静态分析
- **Date**: 2026-06-19
- **Source**: 16 个 Protocol .lua 文件，自动提取脚本 `_extract_xyids.py`
- **Output sibling**: `xyid_closed_set.json`（机器可读完整闭集）

---

## §1 总体统计

| 指标 | 值 |
|---|---|
| 处理 Protocol 文件数 | 16 |
| 不同 msg_type 总数（含跨协议复用 ID）| **207** |
| msg_type 在 [1, 5000] 区间内的不同值 | **155** |
| 总定义条数（含重复声明） | 284 |
| 已观察过的 wire msg_type 数（PoC v5/v6） | 6 |

> N6 的 fuzz 范围 [1, 5000] 中：客户端**已知** 155 个 → **未知/隐藏候选** = 5000 − 155 = **4845 个**（A 级 + B 级合计；下面 fuzz-strategy.md 进一步分级）。

---

## §2 各 Protocol processid 与角色映射

| Protocol | processid | 实测 wire 观察 | 简要分组 | XY_ID 数 |
|---|---|---|---|---|
| **AuthProtocol** | 3 | — | Auth/系统通知 | 1 |
| **AgBaseProtocol** | 1 | — | 公共基础（聊天/弹窗/SRS 错误） | 3 |
| **DispatchProtocol** | 147 | — | 匹配队列 | 9 |
| **SRSProtocol** | 0 | ✅ (0_5/0_6 握手) | 入口路由 | 8 |
| **GameProtocol** | 1 | — | 游戏基础 | 3 |
| **GameProtocolGT** | 140 | — | 游戏台桌（GT=Gold Table?） | 11 |
| **RoomProtocol** | 84 | ✅ (84_13 PoC v6) | 房间/桌子 | 11 |
| **IMProtocol** | 100 | ✅ (100_306 心跳; 100_3000 spectator) | 即时消息 / 好友 / 邀请 / 回放 | 67 |
| **MailProtocol** | 141 | — | 邮件 | 12 |
| **BagSysProtocol** | 92 | ✅ (92_506 心跳) | 道具背包 | 20 |
| **TaskProtocol** | 120 | — | 任务 | 12 |
| **ToolProtocol** | 62 | — | 玩家工具/信息 | 15 |
| **BoxDataProtocol** | 113 | — | 大盒数据/排行/管理 | 29 |
| **MatchLinkProtocol** | 1006 | ✅ (1006_25100) | 比赛场入口 | 18 |
| **TeaHouseProtocol** | 116 | — | 茶馆/比赛场房 | 35 |
| **ActiveProtocol** | 30 | — | 活动/账单 | 30 |

**Wire 已观察过的 sub_type (processid) 值**: 0, 1, 84, 92, 100, 1006（PoC v5 抓到的）。这些就是 fuzz 时 `--sub-types` 参数的核心矩阵。

---

## §3 Wire 已观察过的 msg_type（来自 `poc-v5-result.md`）

| msg_type | sub_type | XY_ID 含义 | extra(appid) | 说明 |
|---|---|---|---|---|
| 306 | 100 | IMProtocol.ReqKeepAlive | 自增序号 | IM 心跳 |
| 506 | 92 | BagSysProtocol.ReqKeepAlive | 自增序号 | Bag 心跳 |
| 11201 | 1 | (game frame, 未在 lua 闭集) | 0x29b3=10675 (gameappid) | ⚠ **客户端 lua 中没有 11201，但服务端在 wire 上发** — 这是 N6 已经命中的「服务端实现但客户端无显式定义」的活样本（虽然可能是动态计算或被剥离的 game logic ID） |
| 25100 | 1006 | MatchLinkProtocol.ReqJoin | 0 | 比赛场入队 |
| 3000 | 100 | IMProtocol.ReqRealtimeGameRecord | 0 | spectator 回放（PoC v5 H3+H11+H12+H13 已通） |
| 14 | 84 | RoomProtocol.RespJoinTable | gameappid | PoC v6 试 SEEGAME2=9 |

> **关键观察**：`11201` 不在我们提取的 XY_ID 闭集（脚本扫不到）。说明 game-loop 帧（0x2BC0/0x2BC1 类的子帧封装）走的是另一套 in-band sub_cmd 编号，不是 lua Protocols 注册表里的 XY_ID 路由表。**N6 fuzz 应聚焦 lobby (5748) 这个 Protocols-注册的总线**，game (5045) 的帧编号要单独走另一套（参考 `stable/protocol.py` 的 0x2BC0 sub_cmd 表）。

---

## §4 已知 XY_ID 完整列表（按数值排序，[1, 5000] 子集）

下表所有 ID 都是「客户端 lua 主动发起或注册回调」的协议号。fuzz 时**默认跳过**（除非命名邻域里有 dump/admin 嫌疑词）。

| msg_type | 主要绑定 (protocol.struct) | processid | 方向 |
|---:|---|---:|---|
| 1 | RoomProtocol.* / Mail.ReqCheckNewMail / Tea.* / Box.ReqRealNameAuth / Active.ReqLedger / Task.ReqTaskConfig / Dispatch.CheckAct | 多 | req/notify |
| 2 | MailProtocol.RespCheckNewMail / Box.RespRealNameAuth / Active.RespLedger / Task.RespTaskConfig | 多 | resp |
| 3-12 | 各 protocol 早期 ID（mail/active/box/dispatch/task/tea） | 多 | req/resp |
| 11 | RoomProtocol.ReqCreateTable / AuthProtocol.ReportNewPlayer / SRSProtocol.RespSRSLoad / Mail.ReqGetAward / Task.ReqTaskProtocol | 多 | mixed |
| 13 | **RoomProtocol.ReqJoinTable** ⭐(processid=84, 用于 PoC v6) | 84 | req |
| 14 | **RoomProtocol.RespJoinTable** | 84 | resp |
| 15 | RoomProtocol.ReqPlayerPosition / SRS.ReqSRSAddr / Box.ReqGetConfigDataEx | 多 | req |
| 16 | RoomProtocol.RespPlayerPosition / Box.RespGetConfigDataEx | 多 | resp |
| 17 | RoomProtocol.ReqJoinTableWithGold / Box.ReqRoomPlayerCount | 多 | req |
| 18 | RoomProtocol.RespJoinTableWithGold / Box.RespRoomPlayerCount / Active.ReqTeaBigWinnerBill | 多 | resp |
| 19 | Box.ReqGetUseEmojiPropInfo / Active.RespTeaBigWinnerBill / Task.ReqWebTaskList | 多 | req |
| 20 | Box.RespGetUseEmojiPropInfo / Active.ReqDealBigWinnerBill / Task.RespWebTaskList | 多 | resp |
| 21 | Active.RespDealBigWinnerBill | 30 | resp |
| 23 | Box.ReqVisitorHeart / SRS.ReqPlayerPlusData / RoomProtocol.StartGameByLobby | 多 | req/notify |
| 24 | Box.RespVisitorHeart / SRS.RespPlayerPlusData / RoomProtocol.ReqGetGoldRoomInfo / Active.ReqCurTime | 多 | resp |
| 25 | Box.ReqOtherUserInfo / Active.RespCurTime / Room.RespGetGoldRoomInfo | 多 | req/resp |
| 26-28 | 各种 ReqOther/Resp/GetBan | 多 | mixed |
| 31-32 | Active.ReqTeaBillInfo/Resp | 30 | req/resp |
| 35-36 | Active.ReqSelectTeaBillInfo/Resp | 30 | req/resp |
| 42-43 | Active.ReqBoxLedger/Resp | 30 | req/resp |
| 101 | AgBaseProtocol.PopupMsgBox（公共弹窗） | 1 | notify |
| 106 | Active.BatchProtocol | 30 | ? |
| 107 | AgBaseProtocol.ChatMsg | 1 | notify |
| 118 | AgBaseProtocol.ReportSRSErr (`SRS REPORTSRSERR` — fuzz silent 判定基础) | 1 | notify |
| 223-228 | TeaHouseProtocol.ReqOpen/CloseTeaHouse/Kick | 116 | req/resp |
| 231 | TeaHouseProtocol.UserInfo | 116 | ? |
| 241 | TeaHouseProtocol.SetupTeaHouse | 116 | ? |
| 251-252 | TeaHouseProtocol.ReqTeaHouseRight/Resp | 116 | req/resp |
| 277 | TeaHouseProtocol.ReqSetPayType | 116 | req |
| 281-284 | TeaHouseProtocol.ReqCreateTableAutoSit/Resp/JoinTea | 116 | req/resp |
| 287-288 | TeaHouseProtocol.ReqSetTeaInfo/Resp | 116 | req/resp |
| 298-299 | TeaHouseProtocol.ReqInvitePlayer/Resp | 116 | req/resp |
| 300-307 | TeaHouseProtocol.* / IMProtocol 早期 (301=ReqAppidList...307=RespKeepAlive) | 多 | mixed |
| 337-340 | TeaHouseProtocol.ReqUserInfoListCnt / ReqQuitTeaHouse / Resp | 116 | req/resp |
| 377-378 | TeaHouseProtocol.ReqOperationHistory/Resp | 116 | req/resp |
| 401-402 | IMProtocol.ReqJoinIM/Resp | 100 | req/resp |
| 408-414 | IMProtocol.ReqOpen/CloseFriendList / NotifyPlayerInfo / ReqFriendList/Resp | 100 | mixed |
| 415-422 | IMProtocol.ReqInviteGame/Resp/Notify/ReqReply | 100 | mixed |
| 425-426 | IMProtocol.ReqInviteddList/Resp | 100 | req/resp |
| 431-432 | IMProtocol.ReqFriendTableList/Resp ⭐(C2 PoC v5 H12 attack-surface 四件套) | 100 | req/resp |
| 437-443 | IMProtocol.RespWillJoinTable / NotifyWillJoinTable / ReqReplyFollow / ReqFolloweddList | 100 | mixed |
| 450-478 | IMProtocol.* (邀请/好友/预约/搜索/添加好友 全套) | 100 | mixed |
| 461 | IMProtocol.ReqWillJoinTable | 100 | req |
| 501-507 | BagSysProtocol.ReqAppidList/Resp/Notify/PlayerConnect/KeepAlive | 92 | mixed |
| 549-550 | TeaHouseProtocol.RespOpenTeaHouse(2) | 116 | req/resp |
| 591 | TeaHouseProtocol.NotifyCardCount | 116 | notify |
| 596-598 | TeaHouseProtocol.ReqRecomendInvitation/ReqDeal | 116 | req |
| 601-613 | BagSysProtocol.ReqJoinBoxProp/PropsConfig/BackpackData/UseProps/OperateProps/Notify/GiftPack | 92 | mixed |
| **3000-3003** | IMProtocol/MatchLinkProtocol Realtime Game Record (PoC v5 spectator) | 100/1006 | req/resp |

---

## §5 区间分布与 fuzz 候选总数

| 区间 | 已知 ID 数 | 候选 unknown 数 | 备注 |
|---:|---:|---:|---|
| [1, 100] | 33 | 67 | 单 protocol 内常用编号；很多 CMDT 早期值 |
| [101, 500] | 81 | 319 | TeaHouse + IM 主战场 |
| [501, 1000] | 21 | 478 | BagSys + TeaHouse 尾部 |
| [1001, 3000] | 0 | 1999 | **完全空白 — A 级冲击区** |
| [3001, 5000] | 4 (3000–3003) | 1996 | 仅回放 4 个 ID; **A 级 + B 级覆盖区** |
| [5001, 10000] | 1 (5050) | 4994 | 出 5000 fuzz 范围（参考） |
| [10000, 12099] | 21 | — | Box/Game/Tool 高编号区（>5000，跳过） |

**结论**：`[1001, 3000]` 是几乎完全的客户端空白带，最值得重点扫；`[3001, 5000]` 仅有 spectator 4 个 ID，邻域可能藏 admin/dump 协议（DEFCON 套路：dev 接口往往做在主功能 ID 邻域）。

---

## §6 Caveats / 已知不确定

1. **Cocos2d-Lua `dispatch` 表不是闭集**：lua 只注册了**回调**的协议（即客户端**期望服务端响应**的）；纯下行 notify（服务端 push 客户端，但客户端不发）也注册。但**纯调试/admin/dump 协议**通常**没有 lua dispatch**——服务端有 handler 但客户端不感知。这正是 N6 利用的 gap。
2. **GameProtocol(processid=1) 高编号区 [11000, 12100]**：`11201` 在 wire 已观察但不在 lua 闭集，说明 game-loop 帧走另一套（in-band sub_cmd 在 0x2BC0 帧 body 头部）。N6 fuzz 不要碰 [11000, 12099]，那不是 Protocols 总线。
3. **TeaHouseProtocol 部分 XY_ID = N + XY_ID_PLUS(=200)**：已正确解析（如 51+200=251）。
4. **重复 msg_type**：很多 ID 在多个 protocol 里复用（同 ID 在不同 processid 下表示不同含义）。fuzz 时**(msg_type, processid) 是真正的 key**，不是单 msg_type。
5. **`event_key = processid_XYID`**：客户端用 `event_key` 做 dispatch；服务端收 inbound 帧用 `(processid, msg_type)` 路由 → fuzz 必须穷举 (msg_type × sub_type) 矩阵。

---

## §7 完成

- 解析脚本：`_extract_xyids.py`
- JSON 闭集：`xyid_closed_set.json`（按 msg_type 排序，每条含 protocol/struct/processid/direction/source_file/source_line）
- 解析中间产物：`_extract_summary.json`（按 protocol 分组的完整 entries，含 cmdt 常量解析结果）
