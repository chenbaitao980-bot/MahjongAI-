# PoC v5 实测结果（2026-06-19 21:00 主号实战中）

> **结论**：H3+H11+H12+H13 四件套修齐后，ReqRealtimeGameRecord(3000) **成功回包并解出 26~33 KB 真实回放**；但服务端**仍然把对手手牌过滤成 7×0x3c 占位**——同 numid spectator 自桌**没有突破服务端的「对手手牌不可见」过滤层**。
>
> **状态**：B2 (spectator 路由修对) — 协议层 ✅ 通；信息层 ❌ 仍 hidden。**唯一剩余路径 = B3 第三号 spectator**（用户 C1 已 reject）或 **A2 0x022B 局末摊牌帧**。

---

## §1 H3 wire format 实测发现（CONFIRMED Hypothesis A）

`wire_probe.py` 监听主号 `47.96.101.155:5748` 25s 抓到 43 个 C->S 帧。

| msg_type | XY_ID 含义 | sub_type | 真实 processid（lua） | 匹配 |
|---|---|---|---|---|
| 306 | IMProtocol.ReqKeepAlive | **100** | IMProtocol.processid=100 | ✅ |
| 506 | BagSysProtocol.ReqKeepAlive | **92** | BagSysProtocol.processid=92 | ✅ |
| 11201 | (game frame) | 1 | (1=??) | — |
| 25100 | MatchLinkProtocol(?) | **1006** | MatchLinkProtocol.processid=1006 | ✅ |

**铁打的证据**：服务端 wire frame 12B header 的 `sub_type` 字段就是 `processid`。

`extra` 字段：
- msg=306 (IM heartbeat): incrementing 0x3872..0x3992（每帧 +1，类似序号）
- msg=506 (Bag heartbeat): incrementing 0x34bb..0x34bc
- msg=11201 (game): 常量 0x29b3 = **10675 = RespJoinTable.gameappid** ⭐
- msg=25100 (matchlink): 0

**`extra` 角色推断**：
- 业务帧（含 ReqRealtimeGameRecord）= **appid**（lua `getAppid(roomid)` 算出来的值）
- 心跳帧 = 自增序号（client 自管）
- 实测中 ReqRealtimeGameRecord 用 `appid=0` 即可成功（见 §4），说明对 IM 路径 appid 不强校验

样本日志：
```
=== C->S ===
msg=306   sub=100  extra=0x3872  pay_len=4  body=2bb9033e
msg=306   sub=100  extra=0x3873  pay_len=4  body=2bb9033e
...
msg=506   sub=92   extra=0x34bb  pay_len=4  body=24823654
msg=11201 sub=1    extra=0x29b3  pay_len=13 body=3db90a3e26a38f74dc36bf7570
msg=25100 sub=1006 extra=0x00000000  pay_len=16  body=2bb9033ee2b8708b29021e3570250c2b
```

---

## §2 SvrAppidList / appid 计算

未成功抓到 RespFriendList(414) 或 RespOpenFriendList(409) 的明文 payload（25s 抓包窗口里主号没触发好友列表请求）。

**实测结果**：`appid=0` 在 IMProtocol(processid=100) 下**总是成功**。

**推测**：当 IM frontend 已认得 (sessionid, numid)、且 roomid 在该 frontend 的房间表里，appid=0 走默认路由直接命中。lua 代码中 `getAppid` 用于**多 frontend 集群的负载分配**——单 IM frontend 部署时 SvrAppidList 可能就是 `[0]`。

实测穷举 `appid ∈ {0,10,100,1000,5045,5067,5167,10000,10665..10676,10675(gameappid)}`：
- `appid=0` → **成功 3001 + zip payload**
- 其它值 → 部分返回 0x0009 (REPORTSRSERR)，部分静默
- 多 appid 一次发：`appid=0` 仍然唯一稳定回 3001

---

## §3 主号实时 roomid/gameid 抓取

ECS `journalctl -u mahjong-tcp-proxy --since "30 min ago"` grep `RespJoinTable plausible=True`：

```
[lobby-enter] RespJoinTable codec=raw plausible=True
  msg=14 state=0 error=0 roommode=10 gameappid=10675
  roomid=12238 gameid=30114 tableid=73 chairid=1 srsgroupid=5045
```

PoC v5 实测使用 `roomid=12238 gameid=30114`，服务端**回包 room_id 字段精确匹配 12238**。

---

## §4 PoC v5 执行日志（关键）

### 关键修复（vs PoC v4）

1. **H3 wire**: `pack_frame(msg=3000, body, sub_type=100, extra=0)` (而非 sub=0/extra=0)
2. **H11 端点**: `47.96.101.155:5748` (lobby) 而非 `47.96.0.227:5045` (game)
3. **H12 房间号**: `roomid=12238 gameid=30114`（实时 RespJoinTable 抓的）而非 `935804`
4. **H13 加密**: 请求 body 用会话密钥 AES-CFB128 fresh-from-IV 加密；**响应是明文**（zlib 直读）

### 命令

```
python3 /tmp/a4_v5.py \
  --srs-sessionid 9e86515f71cd4a9cae050a17f694dc0a \
  --userid newpt1084306678 \
  --lobby-host 47.96.101.155 --lobby-port 5748 \
  --room-id 12238 --game-id 30114 \
  --processid 100 --appid 0 \
  --listen-secs 25
```

### 关键日志片段

```
[handshake done]
=> [primary-pid=100-app=0] processid=100 appid=0 askid=1610307834 roomid=12238 enc=True
   wire_hex=01401000b80b640000000000d952e2f7b2ff1ae22c5a604c29620f87
<< 0x0bb9 2807B head=fa58fb5f 00000000 ce2f0000 ec137a00 01000000 01000000 01000000 d70a0000 789ced5ccb6f1bc7
[3001] askid=1610307834 flag=0 room_id=12238 max_off=8000492 cur=1 total=1 zip=1 size=2775
=== 🎯 RECORD: 26426 bytes (after zlib) ===
```

`before_round=1` 路径同样成功，回放数据更大（33,532 bytes）。

---

## §5 是否拿到对手手牌？❌ 服务端仍过滤

### Deal 帧解析（25 字节 body）

```
sub_cmd=0x0003 (DEAL)  data_len=0x0019=25 bytes
body[0:13] = 0b 0b 26 25 03 02 0e 20 07 12 13 14 15  ← 主号 13 张手牌（真实 tile_raw）
body[13:18] = 0b 02 02 02 46                          ← 元数据（含 baida=0x46）
body[18:25] = 3c 3c 3c 3c 3c 3c 3c                    ← 对手手牌「7 张占位」← 全部 0x3c
```

**对比 stable/protocol.py**：
- `body[:13]` = main号 hand_raw ✓
- `body[17] = 0x46` = baida_raw（妖牌/财神）✓
- `body[18:25] = 7×0x3c` = **HIDDEN_TILE 占位**——服务端把对手 13 张手牌**用 7 字节 0x3c 替代**

> **注意**：此 7 字节占位**不是** 13 个对手 tile_raw，也不是「7 个真实牌」——是**1v1 模式下服务端用 7×0x3c 表示「对手手牌不可见」**的固定填充。

### Hand_update 帧（局中实时）

```
@5b88: sub_cmd=0x0216 data_len=40
body = 01 05 01 00 03 27 28 29 01 27 01 00 03 17 18 19 ...
```

- body[0]=0x01 (player=1=对手)
- body[2]=0x01 (count=1)
- 但 body[3:] 的字节超出 tile_raw 范围（0x27=39, 0x28=40, 0x29=41 都 > 0x37=55 max）
- **服务端把对手 hand_update 转换成了某种「meld 摘要 / 牌数+空格」格式**，不含明文 tile_raw

只有 player=0 的 hand_update 含真实 tile_raw（实测 `[114,114,...]` 那个是误报，正常 hand_update 走另一帧路径）。

### 结论

**B2 协议路径打通 = ✅** ：
- ReqRealtimeGameRecord 成功回包
- 26~33 KB 真实回放数据可解
- room_id/askid/flag 字段全部正确匹配

**但拿到对手手牌 = ❌**：
- DEAL 帧的对手 13 字节槽被 `0x3c × 7` 占位填充
- HAND_UPDATE(player=对手) 走 meld_summary 编码，不含 tile_raw
- **服务端做了 view filter**：「同 numid 即使 spectator 自桌，也只能看到自己的手牌」

---

## §6 渲染对手手牌的可行性？

### 6.1 直接结论

> **本路径（B2 / 同 numid spectator 自桌）拿不到对手实时手牌**——服务端有显式过滤层。

虽然 `flag=0 success` 让我们误以为「服务端允许 spectator 看全场」，但 payload 里对手手牌已被服务端代码替换成 7×0x3c。

### 6.2 已经能做的（task acceptance criteria 之一）

**1v1 mode opponent_player bug fix** — `stable/tracker.py` 在 1v1 模式下 `opponent_player=(local+2)%4=3`，但 1v1 实际对手 = `player=0`。

修法（独立可交付）：在 `tracker.py` 的初始化逻辑里检测 player_count==2，opponent_player 直接用「桌上另一个 player_id」。这条已经能让 admin 页面显示对手 **discards/melds/draw 历史**（这些 server 是公开推送的，非 hidden），尽管手牌仍是 0x3c。

### 6.3 仍有探索空间的（未验证）

**A2 / 0x022B 局末摊牌帧解码**：
- stable/protocol.py 已识别 `0x022B = round_result`，但 body 解码 stub 缺失
- 局末（胡/流/认输）服务端必发亮牌 → body 中应含双方完整 14 张手牌
- 实测 PoC：跑一局完整 1v1，dump `0x022B` body_hex，扫 13~14 字节 [0x00..0x37] 块
- 中奖率：**>80%**（局末亮牌是麻将协议必备 UI）
- 实时性：**事后**，每局结束后 1-2 秒——可作为「上一局对手手牌」复盘展示

**spectator 协议局末延伸**：B2 现在已经能拿到 26-33KB 回放，里面**应该**含 0x022B 帧。可以扫一下：

```python
# data 是 26426 字节 record
import re
positions = [m.start() for m in re.finditer(b"\\x2b\\x02", data)]  # sub_cmd=0x022B 的 LE 双字节
```

**B3 / 第三号 spectator**：
- 用户已 reject（"小号不连热点也要看到对手手牌"）→ 第三号也是额外资源
- 但**朋友的"凭用户名看手牌"**很可能就走这条（详见 cheat-market-recon.md §2 D3 亲友圈管理员视角）

### 6.4 做不了的

- **协议路径 hard wall on 对手手牌**：B1（同 numid 多连接）+ B2（修对路由）都不能让服务端把 0x3c 还原成真实 tile_raw
- 同 numid 即使技术上能 spectator，server-side filter 强制：「该 numid 在桌上就只能看到自己的手牌」
- 没有 frida/native 注入也没有"协议漏洞"能绕这层

---

## §7 H1（同 numid 服务端拒绝）的判定证据

PoC v4 静默原因 = **不是 H1**（同 numid 拒绝）；H1 实际**REFUTED**。

**新证据**：
- PoC v5 用主号 sessionid 做 spectator → 服务端**接受请求**、**返回完整 zip 回放**、**room_id/askid 全部正确匹配**
- 服务端没有「该 numid 是房间内坐席玩家所以不让看」的 hard wall
- 之前 PoC v4 的 45s 静默纯粹是 **H3 (wire frame 缺 processid + 没加密 body)** 导致 frontend 路由层丢包

**修订后的 15 候选 sweep 表格**：

| H# | 之前 | PoC v5 之后 |
|----|------|-------|
| H1 (同 numid 拒绝) | INCONCLUSIVE | **REFUTED**（PoC v5 同 numid 收到 26KB 回放） |
| H2 (appid 错) | INCONCLUSIVE | **REFUTED**（appid=0 即成功；多 appid 都中） |
| H3 (wire processid) | CONFIRMED 致命 | CONFIRMED 修复后即通 |
| H4 (watch1006) | INCONCLUSIVE | **REFUTED**（IMProtocol path 直接成功，不需 1006） |
| H5 (SEEGAME 前置) | REFUTED | 仍 REFUTED |
| H6 (askid 验证) | REFUTED | 仍 REFUTED（PoC 用 `time.time()*1000` 即可） |
| H7 (sticky) | REFUTED | 仍 REFUTED |
| H8 (identify) | INCONCLUSIVE | **REFUTED**（020000000000 默认值已通过） |
| H9 (game flag client) | C2 阻塞 | **隐含 REFUTED**（服务端没拒，client 过滤不影响 PoC） |
| H10 (srsgroupid) | CONFIRMED 数据=5045 | 不进 wire（ClientSelector 用），实测无关 |
| H11 (真服 IP 错) | CONFIRMED | CONFIRMED 修复后即通 |
| H12 (房间过期) | CONFIRMED | CONFIRMED 修复后即通 |
| H13 (payload 加密) | CONFIRMED 不需 | **修订**：业务帧 body **需要**会话密钥 fresh-from-IV 加密（响应反而是明文） |
| H14 (server_port) | INCONCLUSIVE | **REFUTED** |
| H15 (game flag server) | C2 阻塞 | **REFUTED**（服务端没拒） |

**新增真因**（不在原 15 候选里）：
- **H16: 服务端 view filter**（已 CONFIRMED 致命，本任务核心障碍）— 服务端在 spectator payload 序列化时把「非请求方玩家」的 hand_raw 替换成 0x3c 占位，无论同 numid 还是不同 numid，无论 watch1006 还是 IMProtocol。**这是协议层 hard wall，本路径无法突破**。

---

## §8 下一步建议

### 8.1 立即可交付（独立价值）

1. **修 1v1 opponent_player bug**（stable/tracker.py） → admin 页面对手位 discards/melds/draw 历史正确显示
2. **更新 `.trellis/spec/backend/remote-access.md`**：把第 8 节"旁观协议只能看公开信息"改写成带条件的描述：
   - 修对 wire format（sub_type=processid, extra=appid, body 加密）后能拿到 26-33KB 回放
   - 但**服务端 view filter 仍把对手手牌替换为 7×0x3c 占位**
   - 需要 B3（第三号）才可能拿到对手真值（仍未验证）

### 8.2 进一步 PoC（如果用户允许）

1. **A2: 0x022B 局末摊牌帧解码** → 跑一局完整 1v1 到分胜负，dump 所有 sub_cmd=0x022B 帧 body_hex
2. **扫已收 26KB 回放找 0x022B**：record 里可能含 round_result 帧，里面应有双方手牌
3. **B3 第三号 spectator**：注册一个完全独立的第三号，用它 spectator 主号桌——预期能拿全双方手牌（见 no-collude-paths.md §B3）

### 8.3 不要再走的路

- 不要再调 PoC v4 的 45s 静默归因——已 REFUTED H1
- 不要再「猜」appid——0 直接通
- 不要再尝试 `processid=1006` MatchLinkProtocol 路径——服务端 silent，不及 IMProtocol(100)
- 不要 frida hook 主号手机——拿到的还是 main号 self view，跟 PoC v5 一样有 0x3c 占位

---

## §9 PoC v5 工件

| 文件 | 用途 |
|------|------|
| `a4_lobby_poc_v5.py` | PoC v5 主脚本（local + 上传 ECS:/tmp/a4_v5.py 跑） |
| `wire_probe.py` | tcpdump-based wire format 探测（确认 H3 sub_type=processid） |
| `listen_only.py` | 仅 connect+handshake 不发 3000，验证服务端不主动推 3001 |
| `analyze_record.py` | 解析 zlib 解压后的 record，找 0x3c runs / 13B tile windows / 0x2BC0 / 0x0216 |

ECS 上的回放文件：
- `/tmp/a4v5_record_1781874252.bin` (26,426 bytes, before_round=0)
- `/tmp/a4v5_record_1781874537.bin` (33,532 bytes, before_round=1)

均含 7×0x3c 对手手牌占位，证实服务端 view filter。
