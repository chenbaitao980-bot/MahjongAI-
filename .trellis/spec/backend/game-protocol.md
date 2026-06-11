# Game Wire Protocol Spec

> 台州麻将游戏服务器 TCP 协议（port 7777）的可执行契约。  
> 来源：`stable/protocol.py` + 49 个真实 pcap 文件逆向（2026-06）

---

## 1. Frame Format

所有帧（C->S 和 S->C）共用同一个 12-byte 帧头：

```
Offset  Size  Field        Note
0       1     direction    0x01=C->S, 0x00=S->C（被动嗅探时从 src_port 判断）
1       1     frame_type   0x40=普通, 0x80=大包/分段
2       2     pay_len      LE uint16，payload 字节数
4       2     msg_type     LE uint16，消息类型
6       2     sub_type     LE uint16（见下方各类型规律）
8       4     extra        4 bytes（见下方各类型规律）
```

**帧识别**：`buf[1] in (0x40, 0x80)` 且 `pay_len <= 65535`，不检查 `buf[0]`。

### sub_type / extra 规律（C->S 主动发包）

| 消息类型       | sub_type | extra（hex） |
|---------------|----------|-------------|
| 0x000F init   | 0x0054   | 00000000    |
| 0x0001 handshake | 0x047b | 38564c05  |
| 0x0003 heartbeat | 0x047b | 38564c05  |
| 0x0005 reauth | 0x047b   | 38564c05    |
| 0x0006 auth token | 0x0093 | 00000000 |
| 0x0002 keepalive | 0x0000 | 00000000  |

### 帧构造函数

```python
import struct

def build_frame(msg_type: int, payload: bytes,
                sub_type: int = 0x047b,
                extra: bytes = b'\x38\x56\x4c\x05') -> bytes:
    hdr = bytes([0x01, 0x40])
    hdr += struct.pack('<H', len(payload))
    hdr += struct.pack('<H', msg_type)
    hdr += struct.pack('<H', sub_type)
    hdr += extra[:4].ljust(4, b'\x00')
    return hdr + payload
```

---

## 2. Handshake Sequence（主动客户端必须完整执行）

```
C->S  0x000F  init #1   payload=ceee43931edbc993c0b08b443d2e4014 (16B fixed)
C->S  0x000F  init #2   payload=f1ee43931edbc993c0b08b443d2e4014 (16B fixed)
S->C  0x0010  room_state  (服务端自动推送，客户端无需触发)
C->S  0x0001  handshake   payload=handshake_blob (账号绑定, 19~23B)
  ── 进入游戏事件流 + keepalive 循环 ──
C->S  0x0003  heartbeat_req  payload=f1ef6b65532a4c97d075bc4c393680f925 (17B fixed)
C->S  0x0006  auth token     payload=[4B prefix][12B user_token]
S->C  0x0004  handshake_rsp  (服务端确认，14B protobuf)
  ── 认证完成，正常游戏事件 ──
```

> **Gotcha**：认证触发时机由服务端决定（连接后数十秒到数分钟不等），客户端不能主动触发，只能在维持 keepalive 循环的过程中等待服务端发来 0x0004。当收到 0x0004 响应时即可认为认证完成。实现上可以在建立连接后立即发送 0x0003 + 0x0006，服务端会在合适时机响应 0x0004。

> **Common Mistake: 等待 S→C 0x0006 做触发信号导致死锁**
>
> 不要等收到 S→C 0x0006 之后再发 C→S 0x0006。
> - S→C 0x0006 是**认证结果**（33B protobuf），不是触发信号
> - 服务端也在等你的 C→S 0x0006 token → **死锁**
> - 正确做法：0x0003（心跳）发出后**立即**发 0x0006（token），然后等待 S→C 0x0004 (handshake_rsp) 或 S→C 0x0006 (认证结果) 做确认
>
> 详见 `remote/relay/game_client.py` `_run_once()` 的阶段4 实现。

---

## 3. Auth Token Structure

```
0x0006 C->S payload（16 bytes）：
  bytes 0-3:  session prefix（每次连接不同，前两字节固定为 0x?? 0xf9 规律，可用 os.urandom(3) + b'\xf9' 生成）
  bytes 4-15: user_token（12B，用户特定，跨会话不变）
```

### 提取方法（被动嗅探）

```python
def extract_auth_token(message: ProtocolMessage) -> bytes | None:
    """从 0x0006 C->S 包提取 12B user token"""
    if message.msg_type == 0x0006 and message.direction == 'C->S':
        if len(message.payload) == 16:
            return message.payload[4:16]  # bytes 4-15，不是 0-12！
    return None
```

> **Common Mistake**：`payload[0:12]` 取到的是 session prefix + token 前8字节，不是纯 user token。必须用 `payload[4:16]`。

### 获取方式

- `handshake_blob`（0x0001 C->S payload）和 `user_token`（0x0006 C->S bytes 4-15）只能通过嗅探真实游戏客户端会话获取
- 两者均为**账号绑定**，提取一次后可长期使用（token 不随会话轮转）
- 不是明文用户名/密码，不是标准 JWT，是游戏 SDK 内部二进制凭证

---

## 4. Keepalive

```
0x0002 双向 keepalive（payload = 空）：
  - 服务端和客户端均周期性发送
  - 主动客户端必须响应：收到 S->C 0x0002 → 立即发 C->S 0x0002
  - 不响应可能导致服务端断开连接
```

```python
KEEPALIVE_FRAME = build_frame(0x0002, b'', sub_type=0x0000, extra=b'\x00\x00\x00\x00')

# 在接收循环中：
if msg.msg_type == 0x0002:
    writer.write(KEEPALIVE_FRAME)
    await writer.drain()
```

---

## 5. MSG_TYPES 修正表

`stable/protocol.py` 中的命名与实测有出入：

| msg_type | 代码名称       | 实际方向 | 实际用途 |
|----------|---------------|---------|---------|
| 0x0001   | handshake     | C->S    | 登录 blob（账号绑定，固定） |
| 0x0003   | heartbeat_req | C->S    | 认证阶段心跳（固定 payload） |
| 0x0004   | handshake_rsp | S->C    | 服务端认证确认（protobuf） |
| 0x0005   | auth_req      | C->S    | 重认证请求（非初始登录） |
| 0x0006   | auth_rsp      | **双向** | C->S=认证令牌(16B); S->C=认证信息(33B protobuf) |
| 0x000F   | unknown_0f    | C->S    | 连接初始化（两次） |
| 0x0010   | room_state    | S->C    | 房间状态（服务端主动推送） |
| 0x2BC0   | game_event    | S->C    | 游戏事件主数据流 |
| 0x2BC1   | (未定义)       | C->S    | 游戏事件轮询 |

---

## 6. 从 Socket 解码（SocketMJDecoder）

`MJProtocol` 设计为被动嗅探（输入 pcap dict），主动连接模式需包装适配器：

```python
class SocketMJDecoder:
    """增量解码 TCP socket 字节流，返回 ProtocolMessage 列表。"""
    HDR_LEN = 12

    def __init__(self, server_port: int = 7777):
        self._buf = b''
        from stable.protocol import MJProtocol
        self._proto = MJProtocol(server_port=server_port)

    def feed(self, data: bytes, direction: str = 'S->C') -> list:
        self._buf += data
        messages = []
        while len(self._buf) >= self.HDR_LEN:
            if self._buf[1] not in (0x40, 0x80):
                self._buf = self._buf[1:]   # 跳过无效字节，重新同步
                continue
            pay_len = struct.unpack('<H', self._buf[2:4])[0]
            total = self.HDR_LEN + pay_len
            if len(self._buf) < total:
                break  # 等待更多数据
            frame = self._buf[:total]
            self._buf = self._buf[total:]
            msg = self._proto._decode_frame(frame, direction, 0.0)
            if msg:
                messages.append(msg)
        return messages
```

> **Gotcha**：`_decode_frame` 签名为 `(self, frame: bytes, direction: str, ts: float)`，第三个参数是时间戳，必须传 float（不能省略）。

---

## 7. 双端在线验证

已实测：游戏服务器**允许同一账号同时双端在线**。云端主动客户端连接时不会踢掉游戏机的真实客户端。

---

## 8. SRS 旁观协议（ReqRealtimeGameRecord）

> 来源：`apk_research/decrypted-lua/` 反编译 Lua（2026-06）。完整逆向证据见
> `.trellis/tasks/06-11-srs-client-finish/research/srs-spectator-protocol.md`。
> Python 实现：`remote/srs_spectator/`。

### 旁观 msgid 真值表（XY_ID，十进制）

| 消息 | msgid | hex | 证据 |
|------|-------|-----|------|
| ReqRealtimeGameRecord  | 3000 | 0x0BB8 | `IMProtocol.lua:73` |
| RespRealtimeGameRecord | 3001 | 0x0BB9 | `IMProtocol.lua:74` |
| ReqUnwatch  | 3002 | 0x0BBA | `IMProtocol.lua:75` |
| RespUnwatch | 3003 | 0x0BBB | `IMProtocol.lua:76` |

> **Gotcha：同名 XY_ID 靠 processid 区分**。IMProtocol 与 MatchLinkProtocol 用**相同**的
> 3000/3001 数值，靠 `processid` 区分：**IM=100**，**MatchLink=1006**（watch1006 模式）。
> 旁观 Watch 流程实际走哪套由 `lobby/Modules/Watch/Module.lua` 决定。

> **Common Mistake**：`remote/srs_spectator/spectator.py` 曾用占位猜测值 `0x2F1E/0x2F1D`
> （来自 `stable/protocol.py` 无依据命名）。真值是十进制 3000/3001，常量定义在 `frame.py`。

### 请求/响应体布局（已与 Lua 核对，wire payload 加密前）

```
ReqRealtimeGameRecord  payload: struct("<iiii", askid, roomid, offset, before_round)
                       （仅 roomid 上 wire；gameid 仅客户端本地用）
RespRealtimeGameRecord header: 32B = struct("<8i", askid, flag, room_id, max_offset,
                                            current, total, zip, payload_size) + payload
  - flag==1 (NOT_GOOD) → 数据不完整，丢弃
  - zip!=1            → 非回放数据，不做 zlib 解压，丢弃（勿塞进分片缓冲）
  - total==0          → 无回放数据
  - 分片按 current/total（1-based）合并后再 zlib.decompress
```

### RespJoinTable（通道B 抓 roomid/gameid 的根基）

```
RoomProtocol RespJoinTable  msg_type=14（processid=84），S->C
  payload 偏移：roomid @ +17，gameid @ +21（均 LE int32）
  证据：RoomProtocol.lua:8,242,268-303
```

> `remote/extractor/token_extractor.py:_extract_room_from_sc` 按此偏移解析，已实测正确。
> 注意 `msg_type=14` 在 `frame.py` 里与 SRS 的 `MSG_SRS_ADDR=14` 撞号——靠 processid/方向区分。

### 两个目标要分清：被动解密（可行）vs 主动连接（不必要）

| 目标 | 需要什么 | 状态 |
|------|---------|------|
| **被动解密**：嗅热点流量 → 解密 → 读数据（用户真正要的） | 只需 **AES key**（见 §9） | ✅ **key 已逆出**，差一条真实样本闭环 |
| **主动连接**：云端纯 Python 当旁观者连服务器 | identify(RC4) + sub_type/extra↔processid 映射 + 反篡改 | ⛔ 仍卡 native，**且没必要** |

> **历史教训（2026-06，本会话曾误判）**：一度以为"纯 Python 无法复现 SRS 认证层、与场景B 同墙、
> key 拿不到"——**错**。把"主动连接"的难点错套到了"被动解密"上。被动解密**根本不需要** identify /
> sub_type 映射 / 反篡改 bypass，只需 AES key，而 key 是**静态可逆 + 线缆可读**的（§9）。

主动连接路（若将来真要）才卡这三项 native：`identify`=设备硬件码经 RC4（`SRSProtocol.lua:67` 仅调用）；
wire 帧 `sub_type`/`extra`↔processid 映射未逆出；`handshake.py` 假设的 EncryptVer(1)/ReqKey(3)/
HandshakeRsp(4) 握手序列在 Lua 里不存在（native 层 msgid）。这些**仅主动连接需要**，被动读牌不碰。

### 旁观帧取证（仅"主动连接"路才需要）

`token_extractor.py` 对 msgid 3000-3003 双向 dump 完整明文帧头（msg_type/sub_type/extra/
pay_len/direction）+ payload hex 到 `spectator_forensic.jsonl`；`config.yaml`
`spectator_forensic_all_heads: true` 时额外 dump 每一帧帧头（不含 payload）。**仅当将来要走
"主动连接"路、需要逆 `sub_type/extra↔processid` 映射时才用**；被动解密读牌不需要它。

---

## 9. SRS 加密（AES-256-CFB128）— key 已逆出

> 来源：`apk_research/native/libcocos2dlua.so` 反汇编（符号未 strip）。完整证据见
> `.trellis/tasks/06-11-srs-client-finish/research/srs-key-derivation.md`。
> Python 实现：`remote/srs_spectator/crypto.py` + 验证工具 `decrypt_validate.py`。

| 项 | 真值 | 证据 |
|----|------|------|
| **模式** | **AES-CFB128**（OpenSSL `AES_cfb128_encrypt`，**不是 CTR**） | `encrypt` 内 GOT 重定位 |
| **默认 key** | 32B AES-256 `f362120513e389ff2311d73601231007 05a210007acc023c3901da2ecb12448b` | `setDefaultAesKey` @.rodata 0x11f660c，写 len=0x20 |
| **IV** | 固定 `15ff010034ab4cd355fea122084f1307` | @0x11f662c |
| **会话 key** | 服务端 `RespKey` 报文直接下发：payload = `len`(1B) + `key`(len B)，`onRespKey` **原样拷给** `setAesKey` 覆盖默认 key，**无 KDF/XOR/变换** | `onRespKey` 反汇编 `ldrb len`+`add key ptr`→`setAesKey` |

> **Common Mistake（本会话踩过）**：Frida hook `setAesKey` 在打了 gadget 的 APK 上读到"24字节全零
> key"——**假的**，是反篡改库（libapkpatch/libpanglearmor）检测改包后把 crypto 清零的结果。真 key
> 一直静态躺在 .so 里。**别用动态 hook 的全零值，用静态默认 key + 线缆上的 RespKey 会话 key。**

**被动解密链路**：嗅热点 → 初始帧用默认 key（CFB128, IV 15ff…）解 → 找到 `RespKey` 读出会话 key →
`set_key(会话key)` → 后续业务帧用会话 key 解。无需 root / 反篡改 bypass / identify。

**两个待真实样本敲定的点**（静态到顶）：① `RespKey` 在线缆字节里的精确 offset（C++ 模板序列化吞了
布局）；② `transformStr`(hex 编码) 作用在 AES **之前还是之后**（`encrypt` 体内不调 transformStr，二者独立）。
抓一条 RespKey + 紧随的已知明文密文，喂 `decrypt_validate.py`（它自动试 hex-before/after × 默认/会话
key 各组合，命中 0x4001 帧头即判对），三点齐即闭环。
