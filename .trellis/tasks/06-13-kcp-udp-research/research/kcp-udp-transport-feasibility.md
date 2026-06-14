# Research: KCP/UDP传输层切换方案可行性分析

- **Query**: 游戏是否支持多传输协议(TCP/UDP/KCP)？能否用不同协议连接绕过单连接限制？
- **Scope**: internal (代码分析 + pcap分析 + 原生库符号分析)
- **Date**: 2026-06-13

---

## 一、核心结论

**KCP/UDP传输层切换方案不可行。**

游戏客户端仅支持**纯TCP连接**，服务端仅监听**TCP端口7777**，无任何UDP/KCP fallback机制。所有pcap抓包分析均证实：游戏数据流100%通过TCP传输，UDP流量仅限于IPSec VPN隧道(端口500/4500)和DNS等系统服务。

---

## 二、游戏当前使用的协议

### 2.1 传输层协议：纯TCP

**证据1：pcap抓包分析**

| pcap文件 | TCP包数 | UDP包数 | TCP 7777 | UDP 7777 |
|---------|--------|--------|---------|---------|
| phone_7777.pcap | 697 | 0 | 697 | 0 |
| phone_full.pcap | 67,477 | 19,320 | 3,056 | **0** |
| srs_capture.pcap | 10 | 0 | 10 | 0 |
| srs_capture_any.pcap | 19 | 0 | 10 | 0 |
| stable_reader/*.pcap (49个) | 2,680 | 0 | N/A | N/A |

**关键发现**：
- 所有pcap文件中**没有任何UDP包发往/来自端口7777**
- UDP流量仅存在于：
  - IPSec VPN隧道（端口500/4500）
  - DNS查询（端口53）
  - HTTP/HTTPS（端口80/443）

**证据2：Lua网络层代码**

文件：`apk_research/decrypted-lua/app/Net/TcpConnection.lua`
```lua
local nativeConn = un.network.TcpConnection.new()  -- 明确使用TcpConnection
nativeConn:setSRSType(self.srsType)
nativeConn:setConnectCallback(handler(self, self._onConnect))
nativeConn:setSetupCallback(handler(self, self._onSetup))
nativeConn:setCloseCallback(handler(self, self._onClose))
nativeConn:setMessageCallback(handler(self, self._onMsg))
```

文件：`apk_research/decrypted-lua/app/Net/NetEngine.lua`
```lua
local TCP_CONNECT_TIMEOUT = 10000

function NetEngine:startTcp(groupId, protocolData)
    local newTcp = require("app.Net.TcpConnection").new(groupId)
    -- ...
    newTcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), TCP_CONNECT_TIMEOUT)
end
```

网络引擎**只有TcpConnection**，没有UdpConnection/KcpConnection。

**证据3：服务器配置**

文件：`apk_research/decrypted-lua/app/Config/NetConf.lua`
```lua
XH.LOCAL_TCP_LIST = {
    [5001] = {
        {id = 7144, ip = "47.96.129.196", port = 5722 },
        {id = 9187, ip = "47.97.154.79", port = 5701 },
        -- ...
    },
    -- ...
    [7160] = {
        {id = 0, ip = "47.96.144.19", port = 7777},  -- 金币场
    },
}
```

配置中**只有TCP服务器列表**，没有UDP/KCP服务器配置。

### 2.2 应用层协议：SRS over TCP

游戏使用自研SRS（Session/Request/Response）协议，基于TCP流传输：

```
TCP Socket
  → SRS Frame (12字节header + payload)
    → AES-CFB128加密
      → 游戏消息(0x2BC0等)
```

关键文件：
- `remote/srs_spectator/client.py` — SRSClient实现
- `remote/srs_spectator/frame.py` — SRS帧格式
- `stable/protocol.py` — MJProtocol协议解码

---

## 三、KCP协议分析

### 3.1 什么是KCP

KCP（Kuai Control Protocol）是一个基于UDP的可靠传输协议，特点：
- **基于UDP**：底层使用UDP socket
- **可靠传输**：内置ARQ（自动重传）机制
- **低延迟**：比TCP更快的重传策略
- **多路复用**：支持多个KCP会话共享一个UDP端口
- **与TCP共存**：可以在同一应用中同时使用TCP和KCP

### 3.2 游戏是否支持KCP

**结论：不支持。**

**证据1：原生库符号分析**

对`libcocos2dlua.so`进行字符串分析：

| 关键词 | 出现次数 | 说明 |
|--------|---------|------|
| KCP/kcp | 130 | 但均为C++ mangled符号中的随机字符组合（如`kCpDpJpHpIpEpFp`），非实际KCP协议引用 |
| ikcp | 0 | 标准KCP库API前缀，**完全未出现** |
| TCP/tcp | 117 | 实际TCP相关符号 |
| UDP/udp | 20 | 仅libuv内部UDP API（`uv_udp_bind`等），非游戏协议使用 |
| socket | 281 | 通用socket API |

**证据2：网络类层次结构**

发现的网络类（通过符号分析）：
- `universe::network::TcpConnection` — TCP连接（唯一连接类）
- `universe::network::SRS::*` — SRS协议消息类（EncryptVer, ReqKey, RespKey等）
- `universe::network::GuoPengFei` — 网络管理器（setSRSType, sendMessage等）

**没有发现**：
- `KcpConnection`
- `UdpConnection`
- `KcpClient`
- `ikcp_*` API

**证据3：SRS类型枚举**

```
_ZN8universe7network10GuoPengFei10setSRSTypeEi
```

`setSRSType`接收一个`int`参数，用于设置SRS协议版本/类型，**不是**设置传输层协议。Lua代码中：
```lua
self.srsType = srsType or XH.SRS_TYPE.SRS33
```

这是SRS协议的子版本（如SRS33、SRS50），不是传输层切换。

---

## 四、UDP流量分析

### 4.1 pcap中的UDP流量来源

phone_full.pcap中的19,320个UDP包：

| 来源 | 数量 | 说明 |
|------|------|------|
| 4500↔随机端口 | ~13,764 | IPSec IKEv2 VPN隧道（NAT-T） |
| 500↔随机端口 | ~2,000 | IPSec IKE协商 |
| 80/443↔随机端口 | ~500 | HTTP/HTTPS（广告、更新等） |
| 53↔随机端口 | ~100 | DNS查询 |
| **7777** | **0** | **无游戏相关UDP** |

### 4.2 游戏服务器端口

```
游戏服务器: 47.96.0.227:7777 (TCP)
```

所有游戏数据（SRS握手、游戏帧、旁观请求）均通过**TCP 7777**传输。

---

## 五、其他协议可能性分析

### 5.1 WebSocket

**不可行。**

- 游戏使用原生TCP socket，不是WebSocket
- WebSocket需要HTTP升级握手，游戏协议中没有HTTP层
- 即使WebSocket可用，也无法绕过单连接限制（服务端仍按sessionid限制）

### 5.2 HTTP/2

**不可行。**

- HTTP/2基于TCP，多路复用但仍受单连接限制
- 游戏协议不是HTTP-based

### 5.3 QUIC

**不可行。**

- QUIC基于UDP，游戏没有UDP支持
- 需要服务端支持QUIC，当前服务端仅监听TCP 7777

### 5.4 多TCP连接

**不可行。**

- 服务端对同一`srs_sessionid`强制单连接
- 新连接到达 → 服务端2~3秒内主动关闭旧连接
- 详见`remote/cloud_player.py`死亡原因分析

---

## 六、服务端单连接限制

### 6.1 限制机制

游戏服务端实现：
1. 每个账号只允许**一个活跃TCP连接**
2. 新连接使用相同sessionid认证 → 服务端踢掉旧连接
3. 旧连接收到RST或FIN → 断开

### 6.2 实测证据

`remote/cloud_player.py`（Phase B，已宣告死亡）：
```python
# cloud_player连接游戏服务器：
# 1. TCP connect to 47.96.0.227:7777
# 2. SRS握手成功 (flag=0)
# 3. 服务端2~3秒内主动关闭连接
# 4. 手牌帧 = 0
```

### 6.3 根本原因

同账号同桌单连接（断线重连=接管语义）：第二条连接以同账号"重连"进同一桌，服务器把座位给新连接、**踢掉旧连接**（手机掉线）。

---

## 七、结论

### 7.1 KCP/UDP方案不可行

| 检查项 | 结果 |
|--------|------|
| 游戏客户端支持UDP | ❌ 否，只有TcpConnection |
| 游戏客户端支持KCP | ❌ 否，无ikcp API |
| 服务端监听UDP端口 | ❌ 否，仅TCP 7777 |
| pcap中有UDP游戏流量 | ❌ 否，0个UDP包在7777 |
| Lua代码有协议切换逻辑 | ❌ 否，只有TCP_CONNECT_TIMEOUT |

### 7.2 绕过单连接限制的唯一可行路径

当前项目中**已验证可行**的方案：

1. **热点实时解码**（推荐）：PC热点被动嗅探TCP流量，零第二连接
2. **VPN隧穿**：手机配置IPSec VPN，所有流量经云端
3. **Frida Siphon**：手机端hook recv，HTTP POST到云端（需root+重打包）

**不可行**：
- 云端双连（cloud_player）：服务端踢线
- SRS旁观：无隐藏手牌
- KCP/UDP切换：游戏不支持

---

## 八、关键文件清单

| 文件 | 作用 |
|------|------|
| `remote/srs_spectator/client.py` | SRSClient TCP实现 |
| `remote/cloud_player.py` | SRSPlayerClient（Phase B，已死亡） |
| `remote/extractor/token_extractor.py` | 凭证提取 + SRS sessionid |
| `apk_research/decrypted-lua/app/Net/TcpConnection.lua` | Lua TCP连接封装 |
| `apk_research/decrypted-lua/app/Net/NetEngine.lua` | 网络引擎（仅TCP） |
| `apk_research/decrypted-lua/app/Config/NetConf.lua` | TCP服务器配置 |
| `stable/protocol.py` | MJProtocol协议解码 |
| `apk_research/native/libcocos2dlua.so` | 原生库（含universe::network符号） |

---

## 九、Caveats / Not Found

1. **libuv UDP API存在但未被游戏使用**：`libcocos2dlua.so`中包含`uv_udp_*`符号（来自libuv库），但游戏网络层（universe::network）未调用这些API
2. **Cocos2d-x引擎支持WebSocket**：Lua代码中有WebSocket封装，但仅用于HTTP下载，不用于游戏主协议
3. **SRS_TYPE不是传输层类型**：`setSRSType`设置的是SRS协议子版本（33/50等），不是TCP/UDP切换
4. **无法排除服务端未来支持KCP的可能性**：当前版本（基于逆向分析）不支持，但未来版本可能添加
