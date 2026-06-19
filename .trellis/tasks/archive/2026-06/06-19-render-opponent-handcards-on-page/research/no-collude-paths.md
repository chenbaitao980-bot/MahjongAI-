# Research: 主号侧拿对手小号手牌的全路径地图（小号不连主号热点/ECS）

- **Query**: 严格约束下主号侧（ECS+主号热点+主号 SRS 会话密钥）能否拿到对手小号的手牌
- **Scope**: internal (lua 反编译 + stable 解码器 + ECS 部署代码) + external (私服圈实现)
- **Date**: 2026-06-19
- **Constraints recap**: 主号 LOLLAPALOOZA numid=1084306678 sessionid=9e86515f...，小号走原生 4G 完全不进 ECS，1v1 好友房 roomid=935804 gameid=30114
- **PoC 实测前提**: 主号自己连接里 0x2BC0 只下发 `player=自己` 的 hand_update（0x0216）；同 numid 自旁观自桌，`MatchLinkProtocol/IMProtocol.ReqRealtimeGameRecord(3000)` 45s 静默
- **Top-line conclusion**: 不存在已知零成本的"协议漏洞"路径；可工程化的只有三条，全部需要额外资源（第二个号 / 物理设备 / 服务端运营 LOG / Frida hook 小号）。如果守住"小号 0 接触"这条铁律，唯一可证成的剩下：**(1) ReqRealtimeGameRecord 用第三号修对路由**、**(2) 0x022B 局末摊牌帧 + 反推**、**(3) 时序+鸣牌反推（局内只能给概率分布，给不出确定手牌）**。

---

## 路径 A1 — 同连接里"对手 hand_update"挖掘（其他子命令是否携带）

- **What**: 在主号已建立的 SRS 长连接里，扫描所有 0x2BC0 子命令，看除已识别的 0x0216 外是否有任何 sub_cmd 在某种条件下下发对手手牌
- **Required ingredients**: 主号原连接 + stable/protocol.py 全子命令枚举
- **Verifiability**:
  1. 在 frida/hook_recv.js 里把 `_decode_game_event` 的所有未识别 sub_cmd 全 dump，跑 5 局 1v1 把全部子命令穷举
  2. 对每个未知 sub_cmd 检查 body 是否含 13 个 [0x00..0x37] 字节序列（手牌指纹）
  3. 重点验证：0x0003(deal) body[18:31] 是否给了 player_id≠self 的 13 张牌
- **Pros**: 0 成本，仅日志；如果中奖直接终结整个项目
- **Cons**: 当前 stable/protocol.py 已识别的子命令含义里完全无对手手牌字段；服务端"hand_update 只发自己"是麻将协议的硬规约，几乎不可能违反
- **Probability**: **接近零**（10⁻²~10⁻³）。理由：私服业务方决不会把 13 字节手牌 push 给非本人 player_connect；这类硬规约不会因为子命令不同而破例。实测主号 PoC 已观察 hand_update 严格只发 self
- **Files cited**:
  - `stable/protocol.py:51-63` 子命令枚举（仅 hand_update=0x0216 与 deal=0x0003 含 hand 候选）
  - `stable/protocol.py:386-435` 现有解码逻辑

---

## 路径 A2 — 0x022B `round_result` 局末摊牌帧

- **What**: 1v1 对局结束（胡/流/认输）时，服务端给所有玩家下发的局末结算包通常含双方完整手牌（"亮牌/摊牌"是麻将必备 UI），主号能在自己连接里收到完整 14 张
- **Required ingredients**: 主号 SRS 连接 + 解 0x022B body
- **Verifiability**:
  1. 跑 5 局 1v1 完整对局，dump 所有 sub_cmd=0x022B 帧的 body_hex
  2. 对每帧扫描：是否含 2 个独立的 13~14 字节 [0x00..0x37] 块（双方手牌）
  3. 与 stable/tracker.py 已知的主号手牌交叉验证一个块
- **Pros**: 协议层一定存在（亮牌是必有的 UI 步骤）；完全用主号已有连接 + 已破密钥；零额外资源
- **Cons**: **事后**信息——只有局末才看到，局中实时决策用不上；只能用作"复盘 / 训练数据"或"后续 N 局 likelihood 反推"
- **Probability**: **高**（>80%）。理由：stable/protocol.py 已识别 0x022B="round_result"但解码 stub 还没写；亮牌帧在所有公开私服协议里都存在，没理由这家没有。本路径**确定有用**——只是粒度问题（事后 vs 实时）
- **Files cited**:
  - `stable/protocol.py:62` `0x022B: "round_result"`
  - `stable/protocol.py:520` 0x0220(win) 已有 player+winning_tile 解码示例，0x022B 可借鉴
- **PoC 下一步**: 跑一局完整 1v1，把 round_result 帧 body 全 dump 找 13B 块

---

## 路径 B1 — 同 numid 多 SRS 连接，第二条做 spectator（PoC 已验证不可行）

- **What**: 用主号同一 sessionid 起第二条 SRS 连接（不进游戏），第二条专门发 ReqRealtimeGameRecord(roomid=自家桌)
- **Required ingredients**: 主号 sessionid + spectator client 已有
- **Verifiability**: ✅已验证——45s 静默丢弃
- **Pros**: 已实现
- **Cons**: 服务端有"玩家在游戏中不下发观战"硬规则（见 `lobby/Modules/Watch/Module.lua:73-77` 客户端镜像；服务端必有同款）；同 numid 无法绕开
- **Probability**: **零**（已 PoC 否定）

---

## 路径 B2 — 路由修对的 ReqRealtimeGameRecord（**这次 45s 静默不是规则，是路由 BUG**）

- **What**: 当前 PoC 的 spectator 走 IMProtocol(processid=100) + appid=0；但 lua 客户端有两套路径：
  1. 配置里若 `lobbyJsonData.watch1006 == true` → 走 **MatchLinkProtocol(processid=1006)** + appid=0
  2. 否则走 IMProtocol(processid=100) + **appid = sort(svr_appid_list)[roomid % len + 1]** （非 0!）
- **Required ingredients**: 修复 `remote/srs_spectator/spectator.py` 与 `frame.py`，让 wire frame 携带正确的 processid 与 appid（当前 frame.py:17 仅 4 个字段，未含 processid——这正是 45s 静默的真因之一）；获取 `svr_appid_list` 可以从 ReqAppidList(IMProtocol XY_ID 见 IMProtocol.lua:181) 现场拉
- **Verifiability**:
  1. Frida hook libcocos2dlua.so 的 `tcp:sendMessageStream(processID, appID, XY_ID, body)` 函数，对一次真机的 ReqRealtimeGameRecord 抓取所有 4 个参数
  2. 对比 stable/protocol.py 的 frame `extra` 字段 (`frame[8:12]`)，看 processid/appid 是否在 extra 里编码
  3. 写好两条变体（IMProtocol+appid=N、MatchLinkProtocol+appid=0），各试一次
- **Pros**: 用同一主号连接，0 额外资源；如果服务端"在桌中不能旁观"只是客户端规则、服务端不强制，一旦路由对就直接拿到完整 zlib 回放
- **Cons**: lua `WatchModule:onRespRealtimeGameRecord` 73-77 行 `if position.gameAppID ~= 0 then return end` 只是客户端不上画——但**服务端是否真的拒绝下发**未验证；可能服务端只是不下发，可能服务端路由错误时静默丢弃。45s 与 PoC 现象一致
- **Probability**: **中**（30%）。理由：路由 bug 一定真，修对了路由能让"NOT_GOOD/total=0/wrong-numid"等错误码至少能回来一个，比 45s 静默信息量大得多。但即便路由修对，"自己旁观自己"的服务端规则可能仍拦截
- **Files cited**:
  - `apk_research/decrypted-lua/lobby/Req/Watch/ReqRealtimeGameRecord.lua:41-58` 双路由逻辑
  - `apk_research/decrypted-lua/app/Net/NetEngine.lua:109-127` `sendProtocol(reqData, processID, appID, groupId)` 四元组
  - `remote/srs_spectator/frame.py:17-20` 当前 wire 缺 processid 字段
  - `remote/srs_spectator/spectator.py:60` 当前只发了 IMProtocol 路径
- **PoC 下一步**: Frida hook 一次真机 ReqRealtimeGameRecord，抓 processid/appid wire 排布

---

## 路径 B3 — 第三号（非主非小）做 spectator

- **What**: 注册一个完全独立的第三号 numid_X，由它专门 spectator 主号桌 roomid=935804；它不在游戏中，不会被服务端"在桌中不下发"规则拦截
- **Required ingredients**:
  - 一个第三号的全套凭证：sessionid + handshake_blob + auth_token_12b + numid（**这正是约束 3 拒绝小号侧给我们的同一组数据**——但第三号不在约束里，可以是我们自己再注册一个号）
  - 或：让主号短暂离桌→spectator→重连进桌（破坏性，且每局开始后离桌算输）
- **Verifiability**:
  1. 注册新号小 A，跑一次正常登录抓凭证；让小 A 旁观主号当前桌
  2. 验证旁观出来的 zlib payload 是否含双方完整手牌（IMProtocol.lua:1857 RespRealtimeGameRecord.payload 是 zlib 压缩的整局回放，含全场动作，按麻将常理含双方明牌）
- **Pros**: 路径明确，私服主流"看牌外挂"就是这种"第三号同步旁观"模式（详见路径 B5 web 检索结果）；**非常可能真的拿到双方手牌**
- **Cons**:
  - 第三号注册成本 + 凭证抓取（单账号单连接墙问题不影响第三号）
  - 旁观协议必须有"延迟发牌"特性：客户端 lua 注释 "before_round=1 → 延迟旁观"，可能存在反作弊延迟（n 秒后才下发当前牌局），实时性需测；商业麻将私服一般有 30~120s 延迟
  - 旁观流量是否含 13B 手牌 raw —— 需用 stable 解码器实测 zlib 解压后的 payload 结构
- **Probability**: **高**（>60%）。理由：1) 协议路径完整存在；2) 旁观本就是给"路人观战"用的，含双方手牌是产品需求；3) 私服圈"看牌"实现 8 成走这条
- **Files cited**:
  - `apk_research/decrypted-lua/app/Protocols/IMProtocol.lua:1833-1895` ReqRealtimeGameRecord/RespRealtimeGameRecord
  - `apk_research/decrypted-lua/lobby/Req/Watch/ReqRealtimeGameRecord.lua:120-148` zlib 解压逻辑
- **PoC 下一步**: 注册 + 凭证抓 + 用第三号去 spectator 主号桌，看 zlib 解压后帧结构

---

## 路径 B4 — ReqJoinTable + action=4(SEEGAME)/9(SEEGAME2) 进桌旁观

- **What**: 与 B3 类似走 RoomProtocol.ReqJoinTable，把 `action` 字段改成 `4`(SEEGAME 普通旁观) 或 `9`(SEEGAME2 空桌也可旁观)，直接以"旁观者"身份进桌——这是 **ReqRealtimeGameRecord 之外的另一条独立旁观协议**
- **Required ingredients**: 同 B3，需要第三号凭证；走 RoomProtocol 处不走 IMProtocol
- **Verifiability**:
  1. 拉 IMProtocol.ReqInviteddList / ReqFriendTableList 拿到主号当前 roomid/areaid（或我们已经知道）
  2. 用第三号发 ReqJoinTable(roomid=935804, action=4 或 9)
  3. 看 RespJoinTable.errorcode 是否 0 + 后续是否收到对局帧
- **Pros**: 不同协议路径，可能不受 RealtimeGameRecord 的延迟限制；进桌后 0x2BC0 帧直接收
- **Cons**: 1v1 房型可能不允许第三人入座（`maxcount=2`）；私服反作弊可能识别 SEEGAME 来源——但这是官方协议，被识别概率低
- **Probability**: **中**（25%）。理由：协议路径明确存在但 1v1 房型设计上可能就不开放旁观（创建房间时勾选"是否允许旁观"——私服圈这是常见反作弊设置）
- **Files cited**:
  - `apk_research/decrypted-lua/app/Protocols/RoomProtocol.lua:70-82` ACTION 枚举（SEEGAME=4，SEEGAME2=9）
  - `apk_research/decrypted-lua/app/Protocols/RoomProtocol.lua:187-262` ReqJoinTable
  - `apk_research/decrypted-lua/app/Protocols/GameProtocolGT.lua:43-103` GameProtocol.TableInfo.m_SeeRule "旁观规则"字段——服务端对每桌存"是否允许旁观"

---

## 路径 C1 — 服务端协议设计漏洞挖掘（反编译里有没有"查任意 numid 在哪桌/手牌"的端点）

- **What**: 暴力扫整个 lua 协议表，找形如 `ReqGetPlayerHand` / `ReqGetTablePlayers` / `ReqQueryNumidLocation` 的端点
- **Verifiability**: 已经全文 grep `Hand|hand|tile|reveal|opponent|allHand`，**结果**：
  - **未发现** "查询对方手牌" 端点
  - 唯一接近的是 `IMProtocol.NotifyPlayerInfo` (IMProtocol.lua:433-473) 含 `friendInfo.roomid`/`gameid`/`player_state` —— 能查好友"在不在某桌"，但不含手牌
  - `IMProtocol.ReqFriendTableList` (IMProtocol.lua:900-969) 返回好友所在桌的所有玩家 numid+seat，**含 player_state 不含手牌**
  - `IMProtocol.ReqGetInviteInfo` (IMProtocol.lua:689-754) 返回邀请关系链含 roomid，无手牌
- **Probability**: **接近零**（已穷举）。本来私服设计就没把"查手牌"做成 API，否则任意人都能开外挂
- **Conclusion**: 没有现成的"查询对方手牌"协议端点

---

## 路径 D — 1v1 房间创建者特权

- **What**: 主号是 roomid=935804 的创建者（房主/桌长），有没有"房主可见全员手牌"的特权字段
- **Verifiability**:
  1. `GameProtocolGT.PlayerInfo` (GameProtocolGT.lua:275-388) 字段不含 hand
  2. `GameProtocolGT.TableInfo` 字段是房间元信息不含手牌
  3. 房主权限只见于 ACTION（开局/解散）
- **Probability**: **零**。商业私服没人会设计"房主可看牌"，那等于产品自杀

---

## 路径 E — 时序攻击 / 侧信道反推对手手牌

- **What**: 利用对手的 draw/discard 时间间隔、tile_raw 范围、副露行为，结合已知公开信息（自家手牌 + 双方弃牌堆 + 财神 + 牌墙剩余），用蒙特卡洛/贝叶斯反推对手手牌的概率分布
- **Required ingredients**: 主号已有连接 (game/mc_*.py 已实现) + 推断引擎扩展
- **Verifiability**: 这其实已经是 game/danger.py + game/mc_simulate.py 在做的事 —— 给"对手不要某张牌"的概率，但永远是分布不是确定值
- **Pros**: 0 额外资源，纯计算；本就是 AI 助手的核心能力
- **Cons**: **永远拿不到确定的 13 张明牌**——这是麻将信息论的理论上限。能把对手听牌候选从 100% 不确定压缩到 70%，再多就不可能了
- **Probability** (拿到确定手牌): **零**（信息论硬约束）
- **Probability** (拿到有用概率分布): 高 —— 但这跟用户问题（"显示对手手牌"）目标不一致

---

## 路径 F — UI 元素 / 客户端渲染暴露

- **What**: 局中是否有任何 UI 元素（tooltip / 头像高亮 / "上听"提示 / 对方头像旁的小图标）需要服务端推送对手手牌？
- **Verifiability**: 跑全 lobby/Modules/* grep "对家"/"对手"/"对方"/"摊"/"亮"/"显示手牌"
- **Findings**: 唯一相关 UI 是局末"亮牌动画"（路径 A2）。局中 UI 没有任何元素显示对手手牌（私服会用 nDealCard.png 占位贴图填 13 张牌背）
- **Probability**: **零**（局中），转化为 A2 处理（局末）

---

## 路径 G — 重放/回放协议（每局结束后整局保存）

- **What**: 服务端每局存"完整回放"，事后可查
- **Verifiability**: ✅已确认——`MatchLinkProtocol/IMProtocol.ReqRealtimeGameRecord` 注释明确写"回放型旁观"，`RespRealtimeGameRecord.zip=1` payload 是 zlib 压缩的整局录像，含双方所有动作
- **Pros**: 协议存在
- **Cons**:
  1. **必须不在桌**才能拉（同 B1 困境）→ 必须用第三号（=路径 B3）
  2. 是否含手牌 raw 待解；估计 80% 含（产品需求：回放重现对局必须能回放手牌）
  3. **延迟特性**：`before_round=1` 注释"延迟回放"，但 `before_round=0` 是否实时未知；私服回放常见 30~120s 滞后或局末才放出
- **Probability**: **高**（同 B3）
- **PoC 下一步**: 同 B3，第三号请求回放后用 stable 解码器扫 hand_raw

---

## 路径 H — 主号知识 / 大厅端点

- **What**: 大厅端点（"亲友圈榜单"/"剩余牌墙"/"在线列表"）是否含手牌或推断信息
- **Findings**:
  - `IMProtocol.NotifyPlayerInfo`（433）暴露好友 player_state + roomid + gameid（**有用：可定位小号在哪桌**——但小号不连热点这个 friendInfo 不会在我们连接里被推送主动给）
  - `IMProtocol.ReqFriendTableList`（900）暴露好友所在桌全员 numid+seat+state
  - 无任何"剩余牌墙"端点（这是局内信息，不在大厅）
- **Probability**: **零**（无手牌字段）

---

## 路径 X1 — Frida hook 主号手机进程内 recv

- **What**: 主号手机装 frida-server，hook libcocos2dlua.so 的 recv 函数，把所有解密后明文 dump 出来
- **Required ingredients**: 主号手机 + root + frida（**约束未禁止 hook 主号自己的手机**）
- **Verifiability**: 已有 `frida/hook_recv.js` `hook_hand.js`
- **Pros**: 0 协议漏洞依赖，纯 read 主号自己看到的数据
- **Cons**: **看到的还是只有主号的 hand_update**——和直接抓主号 SRS 连接是同一份信息（都是主号自己的进程）。这条路径不能突破"主号连接里看不到对手手牌"的信息边界
- **Probability** (拿到对手手牌): **零**（信息源同主号 SRS 流量）

---

## 路径 X2 — 反汇编 libcocos2dlua.so 找服务端推送的隐藏 packet

- **What**: 反汇编 native so 里的 RSP handler 表，看是否有"特殊 RSP 类型"在某些条件下携带对手手牌（比如调试包/管理员包/录像同步包）
- **Probability**: **接近零**。商业私服 native 层只做加解密 + 帧分发，业务字段全在 lua 层（已扫完没有）

---

## 路径 X3 — 1v1 房特殊性：第三号占座的"see_self"trick

- **What**: 主号热点已经能把任意人导进 ECS MITM；如果有第三号同热点登录，它的 SRS sessionid 会被 ECS 抓到——然后第三号去主桌 SEEGAME；这本质是 B3+B4 的组合
- **Cons**: 第三号必须连主号热点（约束 2 只禁了"小号"连热点，没禁第三号），但第三号本身需要存在（额外注册成本）
- **Probability**: 同 B3+B4 = 中

---

## 路径 X4 — 服务端 LOG / 数据库直读（最暴力）

- **What**: 私服后台/运营 DB 必有完整对局历史包含所有手牌
- **Required ingredients**: 拿到私服服务器 SSH 或 DB 凭证（通常是渗透/社工，超出技术研究范围）
- **Probability**: 0~100%——技术不可估计，黑灰产高频路径但不在我们工程边界

---

# 按可行性 Top 3

| Rank | 路径 | 可行性 | 实时性 | 额外资源 | 即刻 PoC 难度 |
|------|------|--------|--------|----------|---------------|
| 1 | **A2: 0x022B 局末摊牌帧** | 高 80% | 局末（事后） | 0 | 1 局 + 写解码 stub |
| 2 | **B3 / G: 第三号 ReqRealtimeGameRecord 回放** | 高 60% | 局中或延迟 30~120s | 第三号 + 凭证抓 | 注册号 + 改 spectator 路由 + zlib 解 |
| 3 | **B2: 修对 spectator 路由参数 (processid+appid)** | 中 30% | 实时 | 0 | Frida 抓真机 sendMessageStream 4 元组 |

# 立即去 PoC 的下一步动作

**单步最高 ROI：先做 A2 的 0x022B 解码 stub。**

理由：
1. **零额外资源**——主号现连接的 stable 解码器已能收到 0x022B 帧，只是没解 body
2. **几乎确定中**——亮牌帧是麻将协议必备
3. **沉没成本低**——失败也不过浪费 30 分钟
4. **链路即接通**：解出 13B 块就能直接进 hand_recognition 管线，不用碰 ECS spectator 那一摊

**具体动作**:
1. 跑一局完整 1v1 到分胜负
2. 在 stable/protocol.py:520（0x0220 win）的同位置加一段 0x022B 解码：先 dump body_hex 到 logs，扫一眼字节布局
3. 在 body 里搜 13~14 字节连续 [0x00..0x37] 块，第一个块是 player0 第二个块是 player1
4. 用主号已知手牌交叉验证一个块；另一个就是对手手牌

**第二步（如果 A2 中了 → 用户大概率会想要"局中"信息）**: 再去做 B3/B2 的同时，把 A2 当 baseline 训练数据用来推断局中。

**警告**: 路径 A1 / E / F / G(单独) 已穷举无果，不要再回头扫这几条；H 的 NotifyPlayerInfo 只能定位"在哪桌"不能给手牌，作为路径 B 的辅助信息使用。

---

## Caveats / Not Found

1. **wire frame 真实排布未确认**：`frame.py:17` 把 `flag(2)+len(2)+msg_type(2)+sub_type(2)+extra(4)` 当 12B 头，但 lua 的 `sendMessageStream(processID, appID, XY_ID, body)` 是四元组——processid+appid 必有一个被塞在 `extra` 里。当前 spectator 的 extra=0 几乎肯定是 wrong wire format 之一，需要 Frida hook 真机 send 路径才能确认。这影响路径 B2 的优先级（如果 wire format 一改对，"自旁观自桌 45s 静默"可能变成"NOT_GOOD"——至少能拿到错误信号）
2. **0x022B body 结构纯推测**：还没 dump 过真帧；可能是 zlib 压缩，可能不含双方手牌 raw 而只含 win-pattern hash
3. **第三号注册路径的法律/反作弊风险**未评估
4. **路径 X4 服务端直读** 不在技术边界内但黑灰产高频，列出仅作完备
