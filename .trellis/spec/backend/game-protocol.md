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
