# Auth Protocol Research

## 握手序列（Handshake Flow）

基于 pcap 样本（`data/stable_reader/raw_20260517_*.pcap`）的实测逆向结果。

### 阶段 0：连接前准备（C->S）

连接建立后，客户端先发送两条 `0x000F` 消息（unknown_0f），然后服务端返回两条 `0x0010`（room_state）：

```
C->S 0x000F (16 bytes) – 设备/版本 init，payload 不变
C->S 0x000F (16 bytes) – 同上（两次）
S->C 0x0010 (66 bytes) – room_state（当前房间状态）
S->C 0x0010 (58 bytes) – room_state（空状态/重置）
```

### 阶段 1：登录握手（C->S 0x0001）

```
C->S 0x0001 handshake (19 bytes)
  hdr: 01 80 [pay_len LE] 01 00 [sub LE] [extra 4B]
  payload: 19 bytes 加密数据（所有 pcap 相同，固定不变）
  示例: c92eae92aa6bfea336590fc1392644343d9eba

  也观察到 23 bytes 变体:
  payload: c92eae92823c0395d075bc74cbc7c4913c1949ada984c9
```

服务端**不立即响应**，而是继续收发 keepalive（0x0002）。

之后服务端主动推送游戏信息：
```
S->C 0x0007 room_info (46 bytes) – 包含后端服务器 IP:Port（如 10.145.1.26:9000）
S->C 0x000A player_info (16 bytes) – 当前玩家信息（protobuf 编码）
S->C 0x2BC0 game_event ... – 开始正常游戏事件流
```

### 阶段 2：认证令牌交换（延迟触发）

在连接建立数百帧之后，服务端触发一次认证校验序列：

```
C->S 0x0003 heartbeat_req (17 bytes)
  payload: f1ef6b65532a4c97d075bc4c393680f925 (固定，所有 pcap 相同)

C->S 0x0006 (16 bytes) – 客户端发送认证令牌
  payload: [4 bytes 变量前缀] + [12 bytes 固定后缀]
  示例:  4e6e4af9 | 7ad8c993c1b08b44392e4014
         27494af9 | 7ad8c993c1b08b44392e4014
         572e4af9 | 7ad8c993c1b08b44392e4014
  -> 后 12 bytes 是用户特定的 session token（不随连接变化）
  -> 前 4 bytes 高两位固定为 0xf94a，低两位是会话计数或随机数

S->C 0x0004 handshake_rsp (14 bytes) – 服务端确认
  payload: 08c965100418c53720c0ed012801
  解析为 protobuf:
    field 1 (varint): 13001 = 0x32c9 (session id?)
    field 2 (varint): 4
    field 3 (varint): 7109 = 0x1bc5 (user id?)
    field 4 (varint): 30400 = 0x76c0
    field 5 (varint): 1
```

### 阶段 3：重认证（可选，会话中期）

在 `raw_20260517_211722.pcap` 中唯一一次观察到，出现在连接末尾：

```
C->S 0x0005 (9 bytes) – 客户端发起重认证
  payload: c92eae92b2aad956f7 (不可解码为 protobuf，加密 opaque)

S->C 0x0006 (33 bytes) – 服务端返回认证信息
  payload: 100418c537221a08c0ed0110af041a05080110cb021a04080210751a040803106f
  解析为 protobuf:
    field 2 (varint): 4
    field 3 (varint): 7109 = 0x1bc5 (user id)
    field 4 (bytes, 26B): 嵌套 protobuf，包含玩家积分/排名等数据

C->S 0x001C (8 bytes) – 客户端确认
  payload: c12eae92b2660292
```

---

## 帧格式

### 帧头（12 bytes，两个方向）

```
Offset  Size  含义
0       1     方向标志: 0x01=C->S，0x00=S->C
1       1     帧类型: 0x40（普通帧）或 0x80（大包/分段）
2       2     payload 长度，LE uint16
4       2     msg_type，LE uint16
6       2     sub_type（用途未全部确认），LE uint16
8       4     extra（通常是会话 token 后4字节或全0）
```

**帧识别**：`MJProtocol._looks_like_frame()` 检查 `buf[1] in (0x40, 0x80)` 且 `pay_len <= 65535`，**不检查 buf[0]**，因此 C->S 和 S->C 帧使用同一套解析逻辑。

### 方向区分

`MJProtocol.process_packet()` 通过 src_port 判断方向：
- `src_port == server_port (7777)` → `S->C`
- 否则 → `C->S`

### 主动发包时帧头构造

云端客户端主动发包（如 handshake、heartbeat）时需自行构造帧头：

```python
import struct

def build_frame(msg_type: int, payload: bytes, sub_type: int = 0, extra: bytes = b'\x00\x00\x00\x00') -> bytes:
    hdr = bytes([0x01, 0x40])  # C->S 方向标志
    hdr += struct.pack('<H', len(payload))   # pay_len
    hdr += struct.pack('<H', msg_type)        # msg_type
    hdr += struct.pack('<H', sub_type)        # sub_type
    hdr += extra[:4].ljust(4, b'\x00')       # extra 4 bytes
    return hdr + payload
```

实测 sub_type 规律（C->S）：
- `0x0001`, `0x0003`, `0x0005` 等控制消息：sub_type = `0x047b`，extra = `38564c05`
- `0x0006` auth token：sub_type = `0x0093`，extra = `00000000`
- `0x000F` init 消息：sub_type = `0x0054`

---

## auth_req / auth_rsp 结构

### MSG_TYPES 命名修正（与代码中的名称对照）

代码中 `stable/protocol.py` 的 MSG_TYPES 命名**部分有误**，基于 pcap 方向实测的更准确命名：

| msg_type | 代码名称       | 实测方向 | 实际用途                               |
|----------|---------------|---------|---------------------------------------|
| 0x0001   | handshake     | C->S    | 客户端登录 blob（加密，19 bytes 固定）   |
| 0x0003   | heartbeat_req | C->S    | 客户端心跳（17 bytes 固定，可能加密）    |
| 0x0004   | handshake_rsp | S->C    | 服务端确认认证（14 bytes protobuf）      |
| 0x0005   | auth_req      | C->S    | 客户端重认证请求（9 bytes opaque）       |
| 0x0006   | auth_rsp      | **双向** | C->S: 认证令牌(16B opaque); S->C: 认证信息(33B protobuf) |
| 0x000F   | unknown_0f    | C->S    | 连接初始化（两次），16 bytes            |
| 0x0010   | room_state    | S->C    | 当前房间/会话状态（服务端主动推送）       |
| 0x001C   | (未定义)      | C->S    | 重认证确认（8 bytes）                   |
| 0x2BC0   | game_event    | S->C    | 游戏事件（主要数据流）                   |
| 0x2BC1   | (未定义)      | C->S    | 游戏事件请求/轮询（客户端发给服务端）      |

### 0x0006 C->S（认证令牌，16 bytes）payload 分析

```
字节 0-3:  变量前缀（每次连接不同，但共享 0xf94a 高16位特征）
字节 4-15: 固定用户 token（12 bytes，用户身份标识，跨会话不变）
```

此 token 不是明文用户名/密码，是**预置会话密钥**（从游戏 App 内部获取）。云端客户端需要：
1. 先从游戏 App 或抓包中提取 bytes 4-15（12 bytes user token）
2. 每次发送时，bytes 0-3 需要生成（机制未知，可尝试随机数或计数器）

---

## 可复用代码评估

### MJProtocol

- **当前角色**：被动解码器，从 pcap 流（`process_packet`）读取字节，输出 `ProtocolMessage`。
- **主动连接可用性**：`_decode_frame` 和 `_decode_game_event` 完全可复用。但 `process_packet` 依赖 pcap dict（含 `src_port`, `dst_port`, `payload`, `seq`），**需包装适配器**。
- **改造建议**：添加 `decode_from_socket(data: bytes, direction: str) -> list[ProtocolMessage]` 方法，绕过 pcap dict 格式，直接解析 bytes 流。

### PacketStateTracker

- **复用性**：完全在应用层，接收 `ProtocolMessage` 输入，无任何网络/pcap 依赖。**可直接复用，零改造**。
- `apply(message)` 方法处理所有游戏事件，`to_battle_state()` 输出 `BattleState`。

### MappingStore

- **依赖文件**：读取 `data/stable_reader/mappings.yaml`（通过 `utils.paths.data_path`）。
- **云端使用**：云服务器需要部署此 YAML 文件或内联映射表。
- **初始化**：`MappingStore(path=None)` 在文件不存在时静默返回空映射（不报错）。
- 内置 tile 解码逻辑（`_builtin_tile`）可处理 `stable`/`instance`/`linear`/`nibble` 四种编码，**不依赖 YAML 也可运行**，但遇到 unknown 会标记需人工确认。

---

## 认证凭证格式

### 认证令牌（0x0006 C->S）

```
[4 bytes session prefix][12 bytes user token]
```

- **不是明文用户名/密码**。
- **不是标准 JWT/OAuth token**（不是 UTF-8 可打印文本）。
- 可能是游戏 SDK 内部生成的二进制会话凭证（类似 cookie/refresh token）。
- **获取方式（未知，需运行时抓包验证）**：目前只能通过抓真实客户端会话获取此 12 bytes token。

### 无测试数据限制

- `tests/` 目录中没有 auth 包样本。
- 现有 pcap 文件（49 个）包含真实会话，但 0x0006 token 是用户私有数据。
- 重认证（0x0005）仅在一个 pcap 文件中出现，样本量极少。

---

## 心跳机制

- **连接中的心跳（双向 keepalive）**：
  - `0x0002` （pay_len=0，hdr: `014000000200000000000000`）双方均周期性发送，与游戏帧交替。
  - 观测频率：每秒若干次，双方对称。
  - **云端客户端必须响应服务端的 0x0002**，否则连接可能断开。

- **认证心跳**：
  - `0x0003 heartbeat_req`（C->S，17 bytes）在认证阶段前发送。
  - payload 固定：`f1ef6b65532a4c97d075bc4c393680f925`（加密内容，所有 pcap 相同）。
  - 疑似周期性触发，间隔约数百游戏帧（数十秒）。

---

## 实现建议

基于以上调查，云端客户端连接实现建议：

### 1. TCP 连接层

```python
import asyncio, struct

SERVER_IP = "47.96.0.227"  # 从 pcap 中提取，可能会变
SERVER_PORT = 7777

async def connect():
    reader, writer = await asyncio.open_connection(SERVER_IP, SERVER_PORT)
    return reader, writer
```

### 2. 帧编解码层（对 MJProtocol 的轻量包装）

```python
def build_frame(msg_type: int, payload: bytes, sub_type: int = 0x047b, extra: bytes = b'\x38\x56\x4c\x05') -> bytes:
    hdr = bytes([0x01, 0x40])
    hdr += struct.pack('<H', len(payload))
    hdr += struct.pack('<H', msg_type)
    hdr += struct.pack('<H', sub_type)
    hdr += extra
    return hdr + payload

class SocketMJDecoder:
    """从 TCP socket 接收数据并解码 ProtocolMessage，不依赖 pcap。"""
    
    def __init__(self):
        self._buf = b''
        from stable.protocol import MJProtocol
        self._proto = MJProtocol(server_port=7777)
    
    def feed(self, data: bytes, direction: str = 'S->C') -> list:
        """direction: 'S->C' or 'C->S'"""
        self._buf += data
        messages = []
        HDR_LEN = 12
        while len(self._buf) >= HDR_LEN:
            if self._buf[1] not in (0x40, 0x80):
                self._buf = self._buf[1:]
                continue
            pay_len = struct.unpack('<H', self._buf[2:4])[0]
            total = HDR_LEN + pay_len
            if len(self._buf) < total:
                break
            frame = self._buf[:total]
            self._buf = self._buf[total:]
            msg = self._proto._decode_frame(frame, direction, 0)
            if msg:
                messages.append(msg)
        return messages
```

### 3. 握手序列

```python
async def do_handshake(reader, writer, handshake_blob: bytes, auth_token_12b: bytes):
    """
    handshake_blob: 从游戏客户端抓包的 0x0001 payload（19 bytes）
    auth_token_12b: 用户 token，从 0x0006 C->S payload bytes 4-15 提取
    """
    # 阶段 1: 发 0x000F x2（具体 payload 从 pcap 复制，暂用固定值）
    INIT_0F_1 = bytes.fromhex('ceee43931edbc993c0b08b443d2e4014')
    INIT_0F_2 = bytes.fromhex('f1ee43931edbc993c0b08b443d2e4014')
    writer.write(build_frame(0x000F, INIT_0F_1, sub_type=0x0054, extra=b'\x00'*4))
    writer.write(build_frame(0x000F, INIT_0F_2, sub_type=0x0054, extra=b'\x38\x56\x4c\x05'))
    await writer.drain()
    
    # 阶段 2: 等待 0x0010 room_state（可选），然后发 handshake
    writer.write(build_frame(0x0001, handshake_blob))
    await writer.drain()
    
    # 阶段 3: 周期性发 keepalive 直到触发认证
    # 认证由服务端决定时机，客户端只需在收到信号时发送：
    # - 0x0003 heartbeat_req（固定 payload）
    # - 0x0006 auth token（prefix + auth_token_12b）

async def send_auth_token(writer, auth_token_12b: bytes, session_prefix: bytes = None):
    """发送认证令牌 0x0006 C->S"""
    import os
    prefix = session_prefix or os.urandom(3) + b'\xf9'  # 模拟前缀
    payload = prefix + auth_token_12b
    writer.write(build_frame(0x0006, payload, sub_type=0x0093, extra=b'\x00'*4))
    await writer.drain()
```

### 4. PacketStateTracker 集成

```python
from stable.tracker import PacketStateTracker
from stable.mapping import MappingStore

mapping = MappingStore()  # 自动加载 data/stable_reader/mappings.yaml
tracker = PacketStateTracker(mapping_store=mapping)

# 收到 ProtocolMessage 后直接 apply：
for msg in decoder.feed(raw_bytes, 'S->C'):
    tracker.apply(msg)

# 当 tracker.should_analyze() 为 True 时触发分析
if tracker.should_analyze():
    battle_state = tracker.to_battle_state()
    # 交给 game/evaluator.py 分析
```

---

## 未知 / 需运行时验证

1. **auth_token 生成规则**：前 4 bytes 的规律未确认（0xf9 结尾 + 变量），建议尝试随机值或递增计数器。
2. **0x0001 handshake blob 是否固定**：两个 pcap 中观察到 19 bytes 和 23 bytes 两种。可能与账号/版本有关，需要实际账号登录时抓包获取。
3. **0x000F init 消息 payload 规律**：部分字节在不同文件间有微小变化，但主体相同，可能是设备标识符。
4. **服务器 IP 是否固定**：当前观测 IP 为 47.96.0.227，可能是阿里云实例，可能因区域/版本变化。
5. **0x0002 keepalive 响应规则**：是否需要在收到 S->C 0x0002 后立即回复 C->S 0x0002？需实测连接保持。
6. **连接是否支持无 pcap 的直连模式**：`MJProtocol` 和 `PacketStateTracker` 不依赖 pcap，但需验证 TCP 直连与被动嗅探的行为一致性。
