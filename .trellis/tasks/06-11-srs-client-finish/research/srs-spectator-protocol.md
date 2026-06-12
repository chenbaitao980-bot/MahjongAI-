# Research: SRS 旁观客户端协议常量与字段布局钉死

- **Query**: 从 `apk_research/decrypted-lua/` 把 `remote/srs_spectator/` 的占位/猜测常量钉死为真值
- **Scope**: internal (Lua 反编译源 + 现有 Python 实现交叉核对)
- **Date**: 2026-06-11

---

## ★ 2026-06-12 更新：§0 与 §7 的两大未知点已被实测推翻/解决

> 这两条改变实现方向，先读。证据：本 session 的 live 实连 + `spectator_forensic.jsonl` 帧头取证。

### (1) §0「纯 Python 跑不通 SRS 握手」——**已推翻**
`scripts/diag_srs_live.py` / `diag_srs_watch.py` 实连 `47.96.0.227:7777`，纯 Python 走通
EncryptVer→ReqKey→HandshakeRsp→PlayerConnect→**PlayerData flag=0 SUCCESS**→ReqPlusData→
RespPlusData(m_key)。加密=AES-256-CFB128+静态默认key+会话key线缆下发（见 [srs-fully-solved.md]）。
**SRS 层（processid=0）可纯 Python 独立驱动。** §0、§5(c)、Caveat 1 的「放弃纯 Python」结论作废。

### (2) §7「sub_type/extra↔processid 映射未逆出」——**已解决：sub_type = processid**
拿 `spectator_forensic.jsonl` 里已知 processid 的真实帧反推，钉死：

| wire `sub_type` | = processid | 协议层 | 证据 msg_type |
|---|---|---|---|
| `0x0000` | 0 | SRS 握手层 | 1,3,4,5,6（EncryptVer..PlusData） |
| `0x0054` | 84 | RoomProtocol/GameProcess | 0x000f,0x0010,0x0018,0x0019 |
| `0x0001` | 1 | GameProcess 牌局帧 | 0x2bc0/0x2bc1（游戏事件主流） |
| `0x047b` | 1147 | **大厅登录层** | 0x0001(真握手),0x0002,0x0007,0x000a |
| `0x03ee` | 1006 | MatchLinkProtocol | 0x620c/0x620d |
| `0x003e` | 62 | （未命名） | 0x2f1d/0x2f1e |
| `0x0074` | 116 | （未命名） | 0x06a7/0x06a8/0x06ea |
| `0x0093` | 147 | （auth 层） | C->S 0x0006（auth_token_12b！） |

→ **`pack_frame` 要加 `sub_type=processid` 参数。旁观请求 IMProtocol(3000) 帧 = `sub_type=0x0064`(100)；MatchLink 用 `0x03ee`(1006)。**
→ `extra`(4B) = 登录后分配的会话/组 id（实测 `38564c05` 在登录后所有帧上恒定；SRS 握手帧 extra=0）；部分 S->C 帧 extra 带 askid/appid 回显。**旁观请求的 extra 取值待实测（疑似该会话的 srsgroupid）。**

### (3) 由此得到的真实分层（比 §0 认识更深一层）
`47.96.0.227:7777` 单条 TCP 上多层复用，靠 sub_type=processid 区分：
1. **SRS 层**(pid=0)：EncryptVer..PlusData → 已通(flag=0)。
2. **大厅登录层**(pid=1147,msg=0x0001 sub=0x047b)：用 extractor 抓的 `handshake_blob`(C->S 0x0001) + `auth_token_12b`(C->S 0x0006 sub=0x0093) → **可重放性待实测**（旧 [[gameclient-scenario-b-constraints]] 说不可重放，但那是把 SRS 握手误读成 nonce 质询，SRS 已证可重放；大厅层是否另有 nonce 未知）。
3. **房间/游戏层**(pid=84/1)：牌局帧 0x2bc0。
4. **旁观层**(pid=100/1006)：ReqRealtimeGameRecord(3000)。

**剩余真未知（按依赖排序）**：① 大厅登录层(pid=1147)能否用抓到的 blob 重放 ② 登录后服务器是否告知「你当前在 room X」(返回牌局机制，给 roomid) ③ 旁观记录(zlib payload)**是否含自己手牌**（最大风险，可能只公开视角）④ 重连(ReqJoinTable reconnect=1)会踢手机。

### ★★ 2026-06-12 终判：active 路阻断于大厅 auth 的 native 密钥墙 ★★

对 `data/phone_srs.pcap`/`phone_full.pcap` 做了穷尽实验（脚本逻辑见本 session）：

1. **加密模型 = 每帧 fresh-CFB-from-IV**（非连续流、非帧序计数器）。证据：连续解密时第2个 PlayerConnect 头16B乱码后 CFB 自同步回正确明文 → 即每帧独立从 IV 起；同明文→同密文（`c28b5b18…` 反复一致）→ 无序列计数器。
2. **SRS 层(pid=0) 全破**：PlayerConnect(0x0005)/PlayerData(0x0006)/PlusData(0x0018) 用 session_key fresh-from-IV 完美解出明文。
3. **RespPlusData(0x18) 实测 `keylen=0`**：按 SRSProtocol.lua:383 精确布局解析（5串+sex+8×int32+keylen），keylen 字节=0 → **服务端没下发 m_key**。`parse_resp_plus_data` 用 2字节长度前缀是错的（实际 1字节）。
4. **大厅 auth 帧(0x0001/0x0016 sub=0x047b, pid=1147)密钥候选全灭**：default / session_key / pwd(sessionid) / PlayerData尾16B —— fresh-from-IV 解全是乱码。密钥**只在 native .so 内存**。
5. **牌局数据帧 0x2bc0 是明文**（`02001000c07600000c21…` 结构化）→ stable 被动模式读的就是它；牌局本身不在加密墙后。

**结论**：云端独立连接能过 SRS 认证(flag=0)，但**过不了其上的大厅登录层**——其密钥 native 管理、被动抓包导不出。过不了大厅 = 进不了桌 = 收不到（明文的）牌局。**active「连一次热点之后任意网络云端读牌」被此墙阻断**，绕过只剩 Frida hook native（需手机跑游戏，违背初衷）。**满足目标的可行架构 = [[vpn-readhand-deployed]] VPN 隧穿**（手机 always-on VPN，流量经云端，被动嗅明文牌局）。

诊断脚本：`scripts/diag_srs_{sample,live,watch}.py` + `capture_srs_sessionid.py`（均 throwaway）。

---

## 0. 关键前置结论（先读这条，会改变实现方向）

> ⚠️ **`srs_spectator/handshake.py` 当前假设的 SRS 握手序列（EncryptVer→ReqKey→HandshakeRsp→PlayerConnect→PlayerData→ReqPlusData）在 Lua 源里根本不存在。**

证据链：
1. `app/Protocols/SRSProtocol.lua` 里**只有** `PlayerConnect(XY_ID=5)`、`PlayerData(6)`、`ReqSRSLoad(10)`、`RespSRSLoad(11)`、`ReqSRSAddr(14)`、`RespSRSAddr(15)`、`ReqPlayerPlusData(23)`、`RespPlayerPlusData(24)`。**没有 EncryptVer(1)、ReqKey(3)、HandshakeRsp(4)**。这三个是 Python 侧 `frame.py:55-58` 自己起的名字（`MSG_ENCRYPT_VER=1/MSG_REQ_KEY=3/MSG_HANDSHAKE_RSP=4`），Lua 里查无此物。
2. `app/Net/TcpConnection.lua` 整个连接层是对 native `un.network.TcpConnection` 的薄封装（`TcpConnection.lua:12` `un.network.TcpConnection.new()`）。**真正的加密、CTR/流式、transformStr、EncryptVer 握手全部在 C++ `libcocos2dlua.so` 里**，Lua 层完全看不到。
3. 本仓库 `remote/relay/game_client.py:1-16` 的 docstring 已经独立得出同一结论并明确写下：
   > "游戏连接的初始认证层（0x0001 sub=0x0000 SRS握手、0x0005 reauth 加密帧、m_key 协商）全部在 native libcocos2dlua.so 中实现。纯 Python 无法复现。GameClient 跳过了整个 SRS 认证层，直接发 0x000F 房间握手 → 服务端不认识 → 立即关闭连接（存活 0.0 秒）。"

**含义**：`srs_spectator` 想"自己当一个独立客户端，跑完 SRS 握手再发旁观请求"这条路，与 relay 团队已经证伪的 `GameClient` 是同一条死路。真正可行的形态是 **复用 channel-B 已经打通的 game 协议帧栈**（见 §6），而不是去补 PlayerConnect 的 AES 细节。下面每条结论都会同时给"协议真值"和"对实现的影响"。

---

## 1. 旁观请求/响应真实 msgid（钉死）

### 已确认真值

| 名称 | 真值 (dec) | 真值 (hex) | 证据 |
|---|---|---|---|
| `ReqRealtimeGameRecord.XY_ID` | **3000** | **0x0BB8** | `IMProtocol.lua:73` `CMDT_REQ_REALTIME_GAME_RECORD = 3000`；`IMProtocol.lua:1834`；`MatchLinkProtocol.lua:3` + `:517` |
| `RespRealtimeGameRecord.XY_ID` | **3001** | **0x0BB9** | `IMProtocol.lua:74` `CMDT_RESP_REALTIME_GAME_RECORD = 3001`；`IMProtocol.lua:1858`；`MatchLinkProtocol.lua:4` + `:541` |
| `ReqUnwatchRealtimeGameRecord.XY_ID` | **3002** | **0x0BBA** | `IMProtocol.lua:75`；`MatchLinkProtocol.lua:5` |
| `RespUnwatchRealtimeGameRecord.XY_ID` | **3003** | **0x0BBB** | `IMProtocol.lua:76`；`MatchLinkProtocol.lua:6` |

### 当前 Python（错误占位）

`spectator.py:18-19`:
```python
SPECTATOR_REQ_MSGID = 0x2F1E   # ← 错。真值 0x0BB8 (3000)
SPECTATOR_RESP_MSGID = 0x2F1D  # ← 错。真值 0x0BB9 (3001)
```
`client.py:196` 还有 `elif self._spectator and msg_type == 0x2F1D:` 同样要改成 `0x0BB9`。

`0x2F1D/0x2F1E` 这两个占位值来自 `stable/protocol.py:43-44` 的 `MSG_TYPES` 里把它们瞎标成 `match_req/match_rsp`——那本身就是没有依据的猜测，不是真值。

### 两套协议如何选（IMProtocol vs MatchLinkProtocol）

`lobby/Req/Watch/ReqRealtimeGameRecord.lua:41-57` 决定走哪套：
```lua
if lobbyJsonData and lobbyJsonData.watch1006 then
    -- 走 MatchLinkProtocol（processid=1006）
    XH.MatchLinkProtocol.ReqRealtimeGameRecord ...
    self:sendMsg(req, XH.MatchLinkProtocol.RespRealtimeGameRecord, srsGroupID, 0)  -- appID=0
    return
end
-- 否则走 IMProtocol（processid=100）
XH.IMProtocol.ReqRealtimeGameRecord ...
local appid = self:getAppid(roomid)
self:sendMsg(req, XH.IMProtocol.RespRealtimeGameRecord, srsGroupID, appid)  -- appID=getAppid(roomid)
```

**关键差异**：
- `IMProtocol.processid = 100`（`IMProtocol.lua:1941`），appID 由 `getAppid(roomid)` 算出（`ReqRealtimeGameRecord.lua:16-27`：`appid[(roomid % #appid) + 1]`）。
- `MatchLinkProtocol.processid = 1006`（`MatchLinkProtocol.lua:629`），appID 固定 0。
- **XY_ID（3000/3001）两套完全相同**——区分两套靠的是 frame 里的 **processid**（100 vs 1006），不是 msgid。

> **推测**：`watch1006` 是服务端下发的 lobby json 开关。哪套生效取决于目标服后台配置，无法从静态 Lua 100% 确定线上走哪套。**实现上两套 processid 都要支持，按响应里回的 processid 匹配**，或两套都试。

---

## 2. ReqRealtimeGameRecord 请求体字段布局（钉死）

### 已确认真值（两套布局完全一致）

`IMProtocol.lua:1847-1854` 和 `MatchLinkProtocol.lua:530-537` 的 `bostream` 完全相同：
```lua
bostream = function(self)
    bos:writeInt32(self.askid)        -- offset 0,  int32 LE
    bos:writeInt32(self.room_id)      -- offset 4,  int32 LE
    bos:writeInt32(self.offset)       -- offset 8,  int32 LE
    bos:writeInt32(self.before_round) -- offset 12, int32 LE
end
```

字段赋值来源 `ReqRealtimeGameRecord.lua:42-46`（1006）/`:51-55`（IM）：
- `askid = os.time()` （`ReqRealtimeGameRecord.lua:33`，秒级时间戳）
- `room_id = roomid`
- `offset = offset`（首次请求传 0，见 `Module.lua:40` start 调用 `offset` 入参，首发为 0）
- `before_round = isDelay and 1 or 0`

**总长 16 字节，无更多字段。没有 gameid/tableid/playerid。** gameid/playercount 只在客户端本地用于落盘和路由（`ReqRealtimeGameRecord.lua:36-37` 存 `self._gameid/_playercount`），**不进 wire payload**。

### 当前 Python（已正确）

`spectator.py:54`:
```python
payload = struct.pack("<iiii", askid, roomid, offset, before_round)  # ✅ 字段顺序/类型/字节序全对
```
**这一条 payload 布局是对的，无需改。** 只有外层 msgid（§1）和 processid（§6）要改。

---

## 3. RespRealtimeGameRecord 响应体布局（钉死）

### 已确认真值

`IMProtocol.lua:1880-1893` / `MatchLinkProtocol.lua:563-576` 的 `bistream` 完全相同：
```lua
self.askid        = bis:readInt32()  -- offset 0,  int32 LE
self.flag         = bis:readInt32()  -- offset 4,  int32 LE
self.room_id      = bis:readInt32()  -- offset 8,  int32 LE
self.max_offset   = bis:readInt32()  -- offset 12, int32 LE
self.current      = bis:readInt32()  -- offset 16, int32 LE
self.total        = bis:readInt32()  -- offset 20, int32 LE
self.zip          = bis:readInt32()  -- offset 24, int32 LE
self.payload_size = bis:readInt32()  -- offset 28, int32 LE
if self.payload_size > 0 then
    self.payload = bis:read(self.payload_size)  -- offset 32, 变长
end
```
→ **固定 32 字节头 + payload_size 字节 payload。当前 Python `spectator.py:71-92` 的 32 字节头解析完全正确。**

### 语义钉死（这些当前 Python 没正确处理或理解错了）

1. **`flag`**：`FLAG.NOT_GOOD = 1` 表示数据不完整（`IMProtocol.lua:1860-1862`）。`ReqRealtimeGameRecord.lua:65-69`：flag==NOT_GOOD 直接 fail。当前 Python 完全没检查 flag，应加 `if flag == 1: 数据不完整，丢弃`。

2. **`zip` 的真正语义 ⚠️**（当前 Python 理解反了）：
   - `ReqRealtimeGameRecord.lua:72` `-- zip不为1的时候，不是回放协议` → `if msgData.zip ~= 1 then return end`。
   - **`zip == 1` 才是真正的回放分片数据，要落盘+合并+解压**；`zip ~= 1` 的包要**直接丢弃**（不是回放协议，是别的推送）。
   - `Module.lua:70` `onRespRealtimeGameRecord` 里反过来：`if msgData.zip and msgData.zip == 1 then return end` —— 这是另一个监听器（实时推送通道），它丢弃 zip==1。**两个监听器分工：Req 流程只收 zip==1，Module 推送流程只收 zip~=1。**
   - 旁观回放数据走的是 Req 流程（`ReqRealtimeGameRecord:onMsgReceive`），所以 **`srs_spectator` 要的是 zip==1 的包**。当前 Python `spectator.py:119` `if frag.get("zip") == 1: zlib.decompress` 凑巧对了解压判断，但**没有先用 `zip==1` 过滤丢弃 zip~=1 的杂包**，会把非回放包也塞进分片缓冲。

3. **分片 `current`/`total` 语义**（`ReqRealtimeGameRecord.lua:76-105`）：
   - `total` = 总分片数；`current` = 当前分片**序号，从 1 开始**（`for i = 1, msgData.total`，落盘文件名用 `msgData.current`，下标 `self._fileStatus[msgData.current]`）。
   - 全部 `current ∈ [1, total]` 收齐后才 merge。
   - `total == 0` → 旁观数据不存在（`ReqRealtimeGameRecord.lua:81-87`），应 fail。
   - 当前 Python `spectator.py:96` `len(frag["parts"]) >= total` 用的是 1-based key，`_merge_and_deliver` `for i in range(1, total+1)` 也是 1-based —— **这一段分片合并逻辑是对的**。

4. **解压算法**（`ReqRealtimeGameRecord.lua:120-138`）：先把所有分片 `payload` 按序拼接成完整字节流，**再**对拼接后的整体做一次 `zlib.inflate()`。即 **zlib（带 header）解压，不是 raw deflate**。当前 Python `zlib.decompress(data)` 对（默认带 zlib header）。注意 Lua 是"先合并所有分片，再解压一次"，**不是每片单独解压** —— 当前 Python `_merge_and_deliver` 也是先 merge 再 decompress，对。

5. **`max_offset`**：用于下一次增量请求的 offset（`ReqRealtimeGameRecord.lua:99` `self.offset = msgData.max_offset`）。要持续旁观需把它回填到下次请求的 `offset`。当前 Python 存了 `frag["max_offset"]` 但没用于续拉。

---

## 4. RoomProtocol RespJoinTable (msgid=14) 布局（钉死）

### 已确认真值

- **msgid 14 确实是 RespJoinTable**：`RoomProtocol.lua:8` `CMDT_RESPONSE_JOIN_TABLE = 14`，`:242` `RespJoinTable.XY_ID = CMDT_RESPONSE_JOIN_TABLE`。✅
- **processid = 84**：`RoomProtocol.lua:614` `RoomProtocol.processid = 84`。

`RoomProtocol.lua:268-303` `bistream` 真实字段顺序：
```lua
self.state     = bis:readUInt8()   -- offset 0,  uint8  (1 byte)
self.errorcode = bis:readInt32()   -- offset 1,  int32 LE
self.askid     = bis:readInt32()   -- offset 5,  int32 LE
self.roommode  = bis:readInt32()   -- offset 9,  int32 LE
self.gameappid = bis:readInt32()   -- offset 13, int32 LE
self.roomid    = bis:readInt32()   -- offset 17, int32 LE  ← 房间号
self.gameid    = bis:readInt32()   -- offset 21, int32 LE  ← 玩法编号
self.tableid   = bis:readInt32()   -- offset 25, int32 LE
self.chairid   = bis:readUInt8()   -- offset 29, uint8
-- 仅当 errorcode == SHOW_MESSAGE(1) 时，这里插入变长 msgbox（8 个字段）
self.srsgroupid = bis:readInt32()  -- msgbox 之后
-- 之后可选 teaid/proxyid/tealevel/teaappid（各 int32，按剩余字节判断）
```

### 当前 extractor 实现核对（`token_extractor.py:154-161`）

```python
state     = payload[0]                          # uint8   ✅
errorcode = struct.unpack_from("<i", p, 1)      # int32   ✅
askid     = struct.unpack_from("<i", p, 5)      # int32   ✅
roommode  = struct.unpack_from("<i", p, 9)      # int32   ✅
gameappid = struct.unpack_from("<i", p, 13)     # int32   ✅
roomid    = struct.unpack_from("<i", p, 17)     # int32   ✅ 偏移正确
gameid    = struct.unpack_from("<i", p, 21)     # int32   ✅ 偏移正确
```
**roomid@17 / gameid@21 偏移完全正确。这一条无需改。**

### ⚠️ 一个潜在坑（需运行期验证，非阻塞）

`token_extractor.py:142` 用 `message.msg_type != 14` 过滤。Lua XY_ID=14（0x000E）。但 `stable/protocol.py:34-35` 的 `MSG_TYPES` 把 `0x0014`(=20) 标成 `join_req`、`0x0015`(=21) 标成 `join_rsp`——**这是另一套（GameProcess/房间内）协议的猜测命名，与 RoomProtocol XY_ID=14 不是一回事**。token_extractor 匹配的 `==14`（十进制 14 = 0x0E）才是 RoomProtocol。两者不冲突，但说明 `stable/protocol.py` 的 `MSG_TYPES` 注释多处是猜的，**不要拿它当真值来源**。

另外 `RespJoinTable` 要从 RoomProtocol(processid=84) 连接收到，而 channel-B extractor 抓的是 game 服(7777)的混合流。**需运行期确认抓到的 `msg_type==14` 包确实来自 lobby/room 流程**（理论上 lobby 与 game 可能是不同连接/不同 SRS group）。当前只靠 msg_type 过滤，若线上抓不到，要回头看 processid（在 sub_type/extra 里，见 §6）。

---

## 5. SRS 握手 & PlayerConnect(msgid=5) 字段

### (a) 握手序列是否准确 → **不准确，Lua 里不存在**

见 §0。`frame.py:55-63` 里的 `EncryptVer(1)/ReqKey(3)/HandshakeRsp(4)` 三个名字在 Lua 无任何对应。Lua 的 SRS 消息只有：
| Python 假设 | Lua 真值 | 证据 |
|---|---|---|
| `EncryptVer = 1` | ❌ 无 | SRSProtocol.lua 无 XY_ID=1 |
| `ReqKey = 3` | ❌ 无 | 无 XY_ID=3 |
| `HandshakeRsp = 4` | ❌ 无 | 无 XY_ID=4 |
| `PlayerConnect = 5` | ✅ `CMDT_PLAYERCONNECT = 5` | `SRSProtocol.lua:5,20` |
| `PlayerData = 6` | ✅ `CMDT_PLAYERDATA = 6` | `SRSProtocol.lua:6,135` |
| `SRSLoad = 10` | ✅ `ReqSRSLoad` | `SRSProtocol.lua:9,430` |
| `SRSAddr = 14` | ⚠️ `ReqSRSAddr=14` 但与 RoomProtocol RespJoinTable=14 **撞号**（不同 processid 区分） | `SRSProtocol.lua:12` |
| `ReqPlusData = 23` | ✅ `CMDT_REQPLAYERPLUSDATA = 23` | `SRSProtocol.lua:16,302` |
| `RespPlusData = 24` | ✅ `CMDT_RESPPLAYERPLUSDATA = 24` | `SRSProtocol.lua:17,322` |

> EncryptVer/ReqKey/HandshakeRsp 这套是 **native C++ 加密协商层**（`un.network.TcpConnection`），不在 Lua 协议表里。`frame.py:10` 的 `ENCRYPT_VER_PAYLOAD = fa60a522` 是 Frida/抓包猜的，无 Lua 佐证。

### (b) PlayerConnect 字段顺序核对（`SRSProtocol.lua:81-110`）

**真实 bostream（usertype==SESSION 分支，即 usertype=7）**：
```lua
bos:writeUInt8(self.clienttype)   -- 1B   (=2 MOBILE)
bos:writeUInt8(self.usertype)     -- 1B   (=7 SESSION)
bos:writeUInt32(self.areaid)      -- 4B   ← uint32, 不是 int32
bos:writeString(self.userid)      -- 变长 string
-- usertype==SESSION 分支：
bos:write(self.pwd, 16)           -- 16B 定长（sessionid 放在 pwd 字段！）
bos:writeString(self.identify)    -- 变长 string
bos:writeInt32(self.ver)          -- 4B
bos:writeInt32(self.channelid)    -- 4B
bos:writeInt32(self.osver)        -- 4B
bos:writeString(self.identify)    -- 变长 string（identify 重复写第二次）
bos:writeInt32(self.nGameID)      -- 4B
-- usertype==SESSION 时不进入末尾 isNew 分支（SRSProtocol.lua:104）
```

**枚举确认**（`SRSProtocol.lua:22-40`）：
- `USERTYPE.SESSION = 7` ✅（Python 用 7 对）
- `CLIENTTYPE.MOBILE = 2` ✅（Python 用 2 对）

**与 `handshake.py:39-62` 逐字段对比**：
| # | Lua 字段 | Lua 类型 | Python `build_player_connect` | 一致? |
|---|---|---|---|---|
| 1 | clienttype | uint8 | `bos.append(2)` | ✅ |
| 2 | usertype | uint8 | `bos.append(7)` | ✅ |
| 3 | areaid | **uint32** | `struct.pack("<I", areaid)` | ✅ (用了 `<I` uint32) |
| 4 | userid | string(变长) | `<H` len + bytes | ⚠️ 见下"字符串编码" |
| 5 | pwd(=sessionid) | **定长16B** | `sessionid[:16].ljust(16)` | ✅ |
| 6 | identify | string | `<H` len + bytes | ⚠️ |
| 7 | ver | int32 | `<i` | ✅ |
| 8 | channelid | int32 | `<i` | ✅ |
| 9 | osver | int32 | `<i` | ✅ |
| 10 | identify(重复) | string | `<H` len + bytes | ✅ 顺序对 |
| 11 | nGameID | int32 | `<i` | ✅ |

**字段顺序与 `handshake.py` 基本一致** ✅。唯一不确定项是 **`writeString` 的长度前缀编码**：
- Lua `writeString`/`readString` 是 native C++，源码看不到。
- **间接证据**：`SRSProtocol.lua:105` 在手动写变长数据时用 `bos:writeInt16(#self.pwd)` 再 `bos:write(self.pwd, #self.pwd)`，强烈暗示 **string = int16(LE) 长度前缀 + 原始字节**。
- Python `handshake.py:46` 用 `struct.pack("<H", len)` = uint16 LE 前缀，**与 int16 前缀在长度为正时字节相同**，**大概率正确**，但属"推测"（无法从 Lua 100% 钉死，需抓包验证一个真实 string 字段的前缀字节）。

### (c) 加密：按消息重置 CTR vs 整条流式 → **无法从 Lua 钉死，且方向有疑**

- Lua 层 `TcpConnection:sendMessage`（`TcpConnection.lua:57-59`）直接丢给 native `self._tcpConn:sendMessage(processid, appid, msgid, stream)`。**CTR 是否每条消息重置 IV、transformStr 作用在哪些消息上，全在 C++，Lua 零信息。**
- `crypto.py` 注释（来自 Frida）说 transformStr = hex encode、IV 固定、AES-192 全零 key。但 `crypto.py:30-35` 用**单个长生命周期 encryptor/decryptor**（流式连续 CTR），而 `transform_and_encrypt` 又用同一个 `self._encryptor.update`——**这暗示实现者认为是"整条连接连续流式 CTR"**。
- ⚠️ **这条只能靠 Frida 抓真机 captured frame 比对验证，静态 Lua 无法判定。** 标记为 **未确认/需 Frida 复核**。结合 §0，由于整个握手在 native 层，**建议放弃纯 Python 复现 PlayerConnect 这条路**。

### (d) `identify` 字段含义/来源（`SRSProtocol.lua:67`）

Lua 注释钉死：
```lua
identify = "", -- 硬件识别码(RC4加密,老的用的是协议的加密key, 其他都是用默认的key加密)
```
→ **`identify` = 设备硬件指纹（device fingerprint），且本身是 RC4 加密后的串**（不是明文设备号）。`RespPlayerPlusData.identify` 注释 `:350` 标 `-- 明文`，说明服务端回的是解密后明文，但**客户端发的 PlayerConnect.identify 是 RC4 密文**。当前 `handshake.py:28` 默认 `identify="test_device"` 是假数据，真机要用设备实际硬件码经 RC4 加密——**又一个 native 依赖**。

---

## 6. 旁观前是否需要前置 join/watch 请求 → **不需要独立 join，但有 unwatch 前置**

### 已确认（`Module.lua` + `RoomManager.lua`）

`lobby/Modules/Watch/Module.lua:30-43` `reqRealtimeGameRecord` 是入口：
```lua
local curWatchRoomid = ...:getWatchRoomId()
if 已在旁观别的房 and curWatchRoomid ~= 0 then
    self:reqUnwatchRealtimeGameRecord(curWatchRoomid)  -- 先发 3002 退订旧房
    -- unwatch 成功回调里(:121-128)再发 ReqRealtimeGameRecord
else
    self:startReq("ReqRealtimeGameRecord", ...)  -- 直接发 3000，无其他前置
end
```

→ **首次旁观一个房间：直接发 `ReqRealtimeGameRecord`(3000)，没有任何 join/进房前置请求。** 唯一的前置是：如果当前已在旁观另一个房间，要先发 `ReqUnwatchRealtimeGameRecord`(3002) 退订旧房，成功后再发 3000。

`RoomManager.lua:189-193` `watchStart` 是**收到回放数据之后**进游戏场景用的，不是发请求前的前置。

### 参数确认

`ReqRealtimeGameRecord:start(roomid, offset, gameid, ...)`（`ReqRealtimeGameRecord.lua:29`）入参，但**进 wire 的只有 roomid**（`room_id` 字段）。`gameid` 只本地用（落盘文件名 + 校验 `areaDic[self._gameid]`，`ReqRealtimeGameRecord.lua:108`）。**所以旁观请求只需要 roomid，不需要 tableid，gameid 仅供客户端本地路由。** ✅ 这与 `main.py:92` `client.request_spectator(roomid, gameid)` 把 gameid 也传进去是 OK 的（gameid 本地用）。

---

## 7. Wire 帧头 ↔ Lua processid/XY_ID 映射（钉死框架，但 sub_type/extra 语义未完全钉死）

`remote/relay/decoder.py:24-40` `build_frame` 是 channel-B 实测可用的帧构造：
```
flag(2)=0x4001 | pay_len(2,LE) | msg_type(2,LE) | sub_type(2,LE) | extra(4) | payload
```
- **`msg_type` 在 wire = Lua 的 XY_ID（msgid）**。证据：`token_extractor.py:142` 用 `msg_type==14` 匹配 RoomProtocol XY_ID=14；`stable/protocol.py:340` `msg_type = frame[4:6]`。
- **`processid`（84/100/1006/0）不在这 12 字节头的显式字段里**——它必然编码进 `sub_type`(2B) 或 `extra`(4B)。`relay/game_client.py` 实测的 sub_type 值（`0x047b`、`0x0054`、`0x0093`、`0x0000`）是按消息类型固定的"魔数"，**当前没有人逆出 sub_type 与 processid 的映射公式**。
- ⚠️ **这是最大的未钉死项**：要发 `ReqRealtimeGameRecord`(msgid=3000, processid=100 或 1006)，必须知道这条消息在 wire 上的 `sub_type`/`extra` 该填什么。Lua 不暴露，relay 抓包样本里也没有旁观帧（relay 只抓了 0x000F/0x0001/0x0003/0x0006/0x0002）。**需要一次真机旁观抓包，拿到 msg_type=0x0BB8 的帧，读出它的 sub_type/extra。**

---

## 对 Python 实现的具体修改清单

> 标 ✅ = 静态钉死可直接改；标 ⚠️ = 需运行期/抓包验证后再定。

### A. `remote/srs_spectator/spectator.py`
| 行 | 现状 | 改为 | 依据 |
|---|---|---|---|
| 18 | `SPECTATOR_REQ_MSGID = 0x2F1E` | `SPECTATOR_REQ_MSGID = 3000  # 0x0BB8` ✅ | §1 |
| 19 | `SPECTATOR_RESP_MSGID = 0x2F1D` | `SPECTATOR_RESP_MSGID = 3001  # 0x0BB9` ✅ | §1 |
| ~71 | 解析后未检查 flag | 加 `if flag == 1: return False  # FLAG.NOT_GOOD 数据不完整` ✅ | §3.1 |
| ~88 | 未过滤 zip | 加 `if zip_flag != 1: return False  # 非回放分片，丢弃` ✅ | §3.2 |
| ~96 | 收齐即合并 | 加 `if total == 0: 旁观数据不存在，丢弃` ✅ | §3 |
| — | 未用 max_offset | 续拉旁观时把 `frag["max_offset"]` 回填下次请求 offset ⚠️(增量旁观才需要) | §3.5 |
| 54 | `struct.pack("<iiii", askid, roomid, offset, before_round)` | **不动，已正确** ✅ | §2 |

### B. `remote/srs_spectator/client.py`
| 行 | 现状 | 改为 | 依据 |
|---|---|---|---|
| 196 | `elif ... msg_type == 0x2F1D:` | `elif ... msg_type == 3001:  # 0x0BB9` ✅ | §1 |
| 19-21,151-193 | 整套 EncryptVer/ReqKey/HandshakeRsp/PlayerConnect 握手状态机 | ⚠️ **架构性：这条路已被 relay 证伪（§0）。** 不要继续补 PlayerConnect 细节；改为复用 channel-B 帧栈或承认纯 Python 不可行 | §0,§5 |

### C. `remote/srs_spectator/frame.py`
| 行 | 现状 | 改为 | 依据 |
|---|---|---|---|
| 55-58 | `MSG_ENCRYPT_VER=1/MSG_REQ_KEY=3/MSG_HANDSHAKE_RSP=4` | ⚠️ 这三个 Lua 无对应，是 native 层名字。保留但注明"native，非 SRSProtocol XY_ID" | §5(a) |
| 61 | `MSG_SRS_ADDR = 14` | 注明：与 RoomProtocol RespJoinTable=14 撞号，靠 processid 区分 ✅ | §5(a) |
| — | 缺旁观 msgid 常量 | 加 `MSG_REQ_REALTIME_RECORD = 3000` / `MSG_RESP_REALTIME_RECORD = 3001` ✅ | §1 |
| 17-20 | `pack_frame` 只填 msg_type，sub_type/extra 默认 0 | ⚠️ 旁观帧的 sub_type/extra 魔数未知，需抓包确定（§7） | §7 |

### D. `remote/srs_spectator/handshake.py`
| 行 | 现状 | 评估 |
|---|---|---|
| 39-62 | `build_player_connect` 字段布局 | ✅ **字段顺序/类型与 SRSProtocol.lua:81-110 一致**（areaid 用了 uint32、sessionid 16B 定长、identify 写两次、末尾 nGameID）。唯一未钉死：`writeString` 长度前缀是否 int16-LE（推测是，§5b） |
| 28 | `identify="test_device"` | ⚠️ 真值应为设备硬件码经 RC4 加密的串（§5d），假数据连不上 |
| 49 | `sessionid[:16].ljust(16, b"\x00")` | ✅ 对应 `bos:write(self.pwd, 16)` 定长16 |

### E. `remote/extractor/token_extractor.py`
| 行 | 现状 | 评估 |
|---|---|---|
| 154-161 | RespJoinTable state/errorcode/askid/roommode/gameappid/roomid@17/gameid@21 | ✅ **偏移全部正确，不用改**（§4） |
| 142 | `msg_type != 14` | ✅ 14=RoomProtocol XY_ID 正确。⚠️ 运行期确认抓到的 14 号帧来自 lobby/room 连接而非其他（§4 坑） |

---

## Caveats / Not Found

1. **加密/握手层（CTR 重置 vs 流式、transformStr 作用范围、EncryptVer payload、identify 的 RC4）全部在 native `libcocos2dlua.so`，Lua 源零信息。** 这些只能靠 Frida 抓真机帧比对，本次研究无法从静态 Lua 钉死。结合 `relay/game_client.py` 已证伪的结论，**纯 Python 独立跑 SRS 握手大概率走不通**。
2. **wire frame 的 `sub_type`/`extra` 与 processid(84/100/1006/0) 的映射公式未逆出**（§7）。要发 3000 旁观请求，必须先抓一帧真实旁观包看 sub_type/extra。这是阻塞"能真正发出有效旁观请求"的最大未知。
3. **`writeString` 长度前缀**：强证据指向 int16-LE 前缀（`SRSProtocol.lua:105` 的 `writeInt16(#pwd)`），但未 100% 钉死，需一帧真实变长字段抓包确认。
4. **watch1006 走 IM(100) 还是 MatchLink(1006)** 取决于服务端下发的 lobby json，静态无法确定线上配置，实现需两套都支持。
5. 任务描述里的路径 `app/Req/Watch/ReqRealtimeGameRecord.lua` 实际在 **`lobby/Req/Watch/`** 下（不在 app/ 下）。

### Files Found（证据文件清单）

| 文件 | 关键行 | 内容 |
|---|---|---|
| `apk_research/decrypted-lua/app/Protocols/IMProtocol.lua` | 73-76, 1833-1933 | 旁观 msgid 3000/3001/3002/3003，processid=100，请求/响应布局 |
| `apk_research/decrypted-lua/app/Protocols/MatchLinkProtocol.lua` | 3-6, 516-616, 629 | 同上布局，processid=1006 |
| `apk_research/decrypted-lua/lobby/Req/Watch/ReqRealtimeGameRecord.lua` | 29-148 | 字段赋值、IM/MatchLink 选择、分片合并+zlib 解压 |
| `apk_research/decrypted-lua/lobby/Modules/Watch/Module.lua` | 30-128 | 旁观入口、unwatch 前置、zip 过滤双监听器 |
| `apk_research/decrypted-lua/app/Protocols/RoomProtocol.lua` | 8, 242, 268-303, 614 | RespJoinTable=14, processid=84, roomid@17/gameid@21 |
| `apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua` | 5-17, 19-132, 350 | PlayerConnect(5)/PlayerData(6)/PlusData(23/24)，identify=RC4 硬件码 |
| `apk_research/decrypted-lua/app/Net/TcpConnection.lua` | 12, 57-59 | 加密/握手在 native un.network.TcpConnection |
| `apk_research/decrypted-lua/app/Net/NetEngine.lua` | 92-126 | `processid.."_"..msgid` 事件键、sendMessageStream 传 processid/appid/XY_ID |
| `apk_research/decrypted-lua/app/Base/Req/ReqProtocol.lua` | 36-51 | sendMsg → sendProtocol(processid, appID, srsGroupID) |
| `remote/relay/decoder.py` | 24-40 | channel-B 帧头：flag/pay_len/msg_type/sub_type/extra |
| `remote/relay/game_client.py` | 1-16, 49-185 | native 握手不可纯 Python 复现的实证 + sub_type 魔数样本 |
| `stable/protocol.py` | 24-47, 336-365 | wire 帧解析，MSG_TYPES（多为猜测命名，勿当真值） |
