# Research: 无配置模式（noconfig / SRS spectator）完整实现调研

- **Query**: 调研项目"无配置模式"（noconfig / SRS spectator）的完整实现，包括数据流、sessionid 提取机制、有效期、软路由常驻可行性
- **Scope**: internal (项目代码 + trellis 任务记录)
- **Date**: 2026-06-13

---

## 一、项目背景与目标

**用户目标**："连一次热点拿到凭证，之后不管手机在什么网络，云端都能持续读到手牌（无 VPN、原装 APK、手机正常打牌）"。

当前实现涉及**四种模式**的 relay 架构：
- **热点模式 (hotspot)** :8000 — 手机连 PC 热点，PC 抓包推送
- **VPN 模式 (vpn)** :8001 — 手机配置 IPSec VPN 连云端
- **无配置模式 (noconfig)** :8002 — SRS 旁观协议直连游戏服务器
- **云端玩家模式 (cloud)** :8003 — 连一次热点抓凭证，云端以玩家身份接收手牌

---

## 二、核心文件清单

### 2.1 Extractor（凭证提取端）

| 文件 | 作用 |
|------|------|
| `remote/extractor/main.py` | extractor 主应用，抓包 + 凭证提取 + 推送到 relay |
| `remote/extractor/capture.py` | 跨平台抓包适配层（Npcap/tcpdump） |
| `remote/extractor/token_extractor.py` | TokenExtractor（提取 handshake_blob/auth_token_12b）+ SRSSessionExtractor（提取 srs_sessionid） |
| `remote/extractor/uploader.py` | HTTP 客户端，向 relay 推送数据（register/push/register_room） |
| `remote/extractor/package_extractor.py` | 打包 extractor bundle（软路由部署用） |

### 2.2 SRS Spectator（云端旁观客户端）

| 文件 | 作用 |
|------|------|
| `remote/srs_spectator/main.py` | SRS Spectator 服务（FastAPI），监听 :8003，接收 roomid/gameid 开始旁观 |
| `remote/srs_spectator/client.py` | SRSClient 类，TCP 连接游戏服务器，完成 SRS 握手 |
| `remote/srs_spectator/spectator.py` | SpectatorClient，处理 ReqRealtimeGameRecord 旁观协议 |
| `remote/srs_spectator/handshake.py` | 构建/解析 SRS 握手消息（PlayerConnect 等） |
| `remote/srs_spectator/player_connect.py` | build_player_connect_raw()，PlayerConnect 二进制格式（80 字节） |
| `remote/srs_spectator/crypto.py` | AES-CFB128 加密/解密（默认 key + session key） |
| `remote/srs_spectator/frame.py` | SRS wire frame 格式（12 字节 header） |

### 2.3 Relay（云端中继）

| 文件 | 作用 |
|------|------|
| `remote/relay/main.py` | relay 多模式入口，支持 hotspot/vpn/noconfig/cloud 四模式 |
| `remote/relay/core.py` | RelayApp 类，每个模式独立的 FastAPI 实例 + StateStore |
| `remote/relay/state_store.py` | 内存状态存储，管理 extractor 在线/离线切换 |
| `remote/noconfig/main.py` | 无配置模式独立入口（端口 8002） |
| `remote/noconfig/app.py` | 无配置模式 FastAPI app + SRS spectator 子进程管理 |

### 2.4 Cloud Player（已宣告死亡）

| 文件 | 作用 |
|------|------|
| `remote/cloud_player.py` | SRSPlayerClient，以玩家身份连接游戏服务器（Phase B，已死亡） |
| `remote/capture_credentials.py` | 两阶段抓包（Phase 1 提取凭证，Phase 2 触发 cloud_player） |

---

## 三、SRS Spectator 工作原理

### 3.1 协议栈

```
手机(任意网络) ↔ 游戏服务器(47.96.0.227:7777)
    ↓
PC热点(被动嗅探) / VPN(全量隧道)
    ↓
extractor → POST /register (handshake_blob + auth_token_12b + srs_sessionid)
    ↓
relay (:8000/:8001/:8002)
    ↓
srs_spectator 子进程 (:8003) → TCP 直连游戏服务器
    ↓
SRS 握手 → PlayerConnect (usertype=7, pwd=srs_sessionid) → flag=0
    ↓
ReqRealtimeGameRecord (msgid=3000) → 旁观数据
```

### 3.2 SRS 握手流程（client.py）

```
1. TCP connect to 47.96.0.227:7777
2. C→S: EncryptVer (msgid=1, AES-CFB128 加密 b'\x01\x00\x00\x00')
3. S→C: EncryptVer echo
4. C→S: ReqKey (msgid=3)
5. S→C: HandshakeRsp (msgid=4, AES 解密得 session_key)
6. C→S: PlayerConnect (msgid=5, session_key 加密)
   - clienttype=2 (MOBILE), usertype=7 (SESSION)
   - areaid=7109
   - userid="newpt1084306678"
   - pwd=srs_sessionid (16B)
   - identify="020000000000"
7. S→C: PlayerData (msgid=6)
   - flag=0: 成功，返回新 sessionid + nickname + protecturl
   - flag=41: 格式错误（PlayerConnect 字段错位）
   - flag=72: 令牌过期（sessionid 过期）
8. C→S: ReqPlayerPlusData (msgid=23)
9. S→C: RespPlayerPlusData (msgid=24) → 返回 m_key
10. 后续游戏帧用 m_key 加密
```

### 3.3 加密链

| 阶段 | 算法 | 密钥 | 来源 |
|---|---|---|---|
| 默认加密 | AES-256-CFB128 | `f362120513e389ff...` | 硬编码在 .rodata |
| HandshakeRsp | AES-CFB128 | session_key | 服务端下发（1B len + key） |
| PlayerConnect | AES-CFB128 | session_key | 客户端用 session_key 加密 |
| PlayerData | AES-CFB128 | session_key | 服务端响应 |
| 后续游戏帧 | AES-CFB128 | m_key | RespPlusData 下发 |

**关键常量**（已钉死）：
- 默认 key：`f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b` (32B)
- IV：`15ff010034ab4cd355fea122084f1307` (16B)
- 模式：AES-CFB128（不是 CTR！）

---

## 四、sessionid 提取机制

### 4.1 提取位置

`srs_sessionid` 从 **SRS 握手流程**中提取，而非 MJ 协议帧。

**提取流程**（`remote/extractor/token_extractor.py:343-446`）：

```python
class SRSSessionExtractor:
    """从 SRS 协议流中提取 sessionid（用作 PlayerConnect 的 pwd）。"""
    
    # 1. 捕获 HandshakeRsp (S→C, msg=4) → AES 解密得 session_key
    # 2. 捕获 PlayerConnect (C→S, msg=5) → AES 解密得 pwd
    # 3. pwd 即为跨会话可复用的 SRS sessionid
```

具体步骤：
1. **HandshakeRsp (msg=4, S→C)**：用默认 key AES 解密 payload，第 1 字节是 key_len，后面 key_len 字节是 session_key
2. **PlayerConnect (msg=5, C→S)**：用 session_key AES 解密 payload，解析出 pwd 字段（16B）
3. pwd 就是 `srs_sessionid`

### 4.2 提取时机

- **触发条件**：手机连 PC 热点，打开游戏 App，完成 SRS 握手时
- **Extractor 自动提取**：`remote/extractor/main.py:108-136`
  - `TokenExtractor` 提取 handshake_blob + auth_token_12b
  - `SRSSessionExtractor` 提取 srs_sessionid
  - 两个都提取到后，通过 `on_registered` 回调 POST 到 relay `/register`

### 4.3 提取代码（关键路径）

```python
# remote/extractor/main.py:101-109
self._extractor = TokenExtractor(
    on_registered=self._on_token_registered,
    on_room_info=self._on_room_info,
    capture_all_heads=self._capture_all_heads,
)
self._srs_extractor = SRSSessionExtractor(
    on_sessionid=self._on_srs_sessionid
)

def _on_srs_sessionid(self, sessionid):
    """SRS sessionid 提取到时的回调"""
    _LOGGER.info("SRS sessionid 已提取: %s", sessionid.hex())
    # 如果 MJ 凭证也已就绪，立即注册
    if self._extractor.is_complete:
        ok = register(self.relay_url, self.api_token,
                     self._extractor.handshake_blob,
                     self._extractor.auth_token_12b,
                     sessionid)
```

---

## 五、sessionid 有效期

### 5.1 官方声明

**用户说"不会过期"，但代码和实测记录显示会过期。**

### 5.2 代码证据

1. **`remote/capture_credentials.py:40`**
   ```python
   DEFAULT_TIMEOUT = 14400   # 4 hours (srs_sessionid validity)
   ```
   明确标注 srs_sessionid 有效期为 **4 小时**。

2. **`.trellis/tasks/archive/2026-06/06-13-noconfig-permanent-read/prd.md:13`**
   > `srs_sessionid` | SRS PlayerData(msg=6) 成功后服务器返回的 16B token | **短期（session 级，连接断开/过期返 flag=72）**

3. **`remote/srs_spectator/client.py:220`**
   ```python
   logger.warning(f"Auth warning: flag={flag} (non-zero, may still work for spectator)")
   ```
   flag=72 时连接仍然可以工作（for spectator），但 sessionid 已过期。

4. **`.trellis/tasks/archive/06-11-srs-client-finish/research/srs-fully-solved.md:88`**
   > flag=72 = INVALID_SESSIONID (令牌错误) — SRSProtocol.lua:199. Pure token error.

### 5.3 实测结论

- **flag=72**：sessionid 过期/无效，服务端拒绝认证
- **有效期**：至少 4 小时（`capture_credentials.py` 默认值，实测可能更长）
- **续期方式**：需要重新连热点提取新的 srs_sessionid
- **保活测试**：`scripts/test_keepalive.py` 验证假设 B（保持连接不断则 session 不过期），但结论未知

### 5.4 用户说法验证

用户说"sessionid 不会过期"，但：
- 代码明确写了 `DEFAULT_TIMEOUT = 14400` (4h)
- PRD 文档明确标注"短期（session 级，连接断开/过期返 flag=72）"
- `flag=72` 是已知的 INVALID_SESSIONID 错误码

**结论：sessionid 会过期，用户说法不正确。**

---

## 六、noconfig 模式完整数据流

### 6.1 正常流程（extractor 在线）

```
手机 → PC热点 → extractor (Npcap/tcpdump 嗅探 7777)
    ↓
MJProtocol.process_packet() → ProtocolMessage
    ↓
TokenExtractor.feed() → 提取 handshake_blob + auth_token_12b
SRSSessionExtractor.feed() → 提取 srs_sessionid
    ↓
POST /register → relay (:8000/:8001/:8002)
    ↓
持久化到 config.yaml
    ↓
PacketStateTracker.apply() → 状态变化
    ↓
POST /push → relay
    ↓
浏览器实时显示手牌
```

### 6.2 切换流程（extractor 离线 → spectator 接管）

```
extractor 停止推送 → StateStore.should_use_game_client() 返回 True
    ↓
RelayApp._ensure_spectator_running() 启动 SRS spectator 子进程
    ↓
srs_spectator/main.py (:8003) → TCP 直连 47.96.0.227:7777
    ↓
SRS 握手 → PlayerConnect (srs_sessionid) → flag=0
    ↓
收到 roomid/gameid 后 → POST /watch → 开始旁观
    ↓
ReqRealtimeGameRecord (msgid=3000) → 接收旁观数据
    ↓
POST /push → relay
    ↓
浏览器实时显示手牌
```

### 6.3 关键切换逻辑

```python
# remote/relay/core.py:298-338
def _ensure_spectator_running(self):
    """无配置模式：extractor 离线时启动 SRS spectator"""
    if not self._state_store.should_use_game_client():
        return  # extractor 在线，不需要 spectator
    
    handshake_hex = self._cfg.get("handshake_blob", "")
    srs_sid = self._cfg.get("srs_sessionid", "")
    
    if not handshake_hex or not srs_sid:
        return  # 缺少凭证，无法启动
    
    # 启动 SRS spectator 子进程
    self._start_srs_spectator(handshake_hex, srs_sid)
```

---

## 七、"软路由常驻"方案可行性分析

### 7.1 方案定义

用户说的"软路由常驻"方案：在软路由（OpenWRT/Linux）上永久运行 extractor，实现"一次配置、永久在线"。

### 7.2 当前 extractor 已支持软路由部署

**`remote/extractor/package_extractor.py`** 已实现 bundle 打包：

```
mahjong-extractor-bundle.tar.gz
├── remote/extractor/*.py
├── stable/{__init__,protocol,tracker,mapping}.py
├── battle/{__init__,state}.py
├── game/** (整个包)
├── utils/{__init__,paths}.py
├── install_linux.sh
├── install_openwrt.sh
├── selfcheck_capture.sh
└── DEPLOY.md
```

### 7.3 软路由部署步骤

1. **打包 bundle**：`python remote/extractor/package_extractor.py`
2. **上传到软路由**：`scp mahjong-extractor-bundle.tar.gz root@router:/tmp/`
3. **解压安装**：`tar -xzf mahjong-extractor-bundle.tar.gz && cd mahjong-extractor && bash install_openwrt.sh`
4. **配置 config.yaml**：设置 relay_url、api_token、game_port
5. **启动服务**：`python run.py`

### 7.4 软路由常驻的关键问题

#### 问题 1：sessionid 过期

- **现状**：srs_sessionid 至少 4 小时过期（实测可能更长）
- **影响**：spectator 无法自动续期，过期后 flag=72 断连
- **解决**：需要手机重新连热点提取新 sessionid

#### 问题 2：凭证提取依赖手机连热点

- **现状**：handshake_blob 和 auth_token_12b 只有在手机连热点时才能提取
- **影响**：手机离开热点后，无法获取新的 srs_sessionid
- **解决**：
  - 方案 A：手机定期回热点"充电"（提取新 sessionid）
  - 方案 B：研究用 auth_token_12b 直接认证（假设 A，未验证）
  - 方案 C：完整重放大厅登录帧序列（假设 C，未实现）

#### 问题 3：extractor 离线后 spectator 接管

- **现状**：`StateStore.should_use_game_client()` 判断 extractor 离线（10 秒无推送）
- **影响**：软路由上 extractor 一直在线，spectator 不会启动
- **解决**：软路由上不需要 spectator，extractor 直接推送即可

### 7.5 软路由常驻的可行路径

#### 路径 A：纯热点模式（已完全可行）

```
手机 → 软路由热点 → 软路由上运行 extractor
    ↓
Npcap/tcpdump 嗅探 7777
    ↓
MJProtocol + PacketStateTracker 解码
    ↓
POST /push → 云端 relay
    ↓
浏览器显示手牌
```

**限制**：手机必须在软路由热点范围内（与当前 PC 热点模式相同）。

**不需要改任何代码**，现有 extractor 已完全支持。

#### 路径 B：无配置模式 + 软路由（需要解决 sessionid 过期）

```
软路由上运行 extractor（仅提取凭证阶段）
    ↓
手机连软路由热点，打开游戏
    ↓
提取 handshake_blob + auth_token_12b + srs_sessionid
    ↓
上传到云端 relay
    ↓
手机离开热点，任意网络
    ↓
云端 srs_spectator 用 srs_sessionid 连接游戏服务器
    ↓
旁观协议获取公开信息
```

**限制**：
1. sessionid 4 小时过期，需要重新连热点提取
2. 旁观模式**看不到隐藏手牌**（只能看到牌背）
3. 云端双连（以玩家身份连接）会踢掉手机

### 7.6 结论

| 方案 | 可行性 | 需要改什么 | 限制 |
|---|---|---|---|
| **软路由纯热点模式** | **完全可行** | 不需要改代码 | 手机必须在热点内 |
| 软路由 + 无配置模式 | 部分可行 | 需要解决 sessionid 过期 | 至少 4h 需重新连热点；旁观无隐藏手牌 |
| 软路由 + 云端双连 | **不可行** | 服务端强制单连接 | 会踢掉手机 |

**"软路由常驻"方案如果指"手机一直连软路由热点"，则完全可行，不需要改任何代码。**

**如果指"手机离开热点后仍能读牌"，则不可行（sessionid 过期 + 旁观无隐藏手牌 + 云端双连踢手机）。**

---

## 八、关键发现总结

### 8.1 SRS Spectator 现状

1. **协议已完全破解**：AES-256-CFB128 加密链、PlayerConnect 格式（80 字节）、flag 含义
2. **flag=0 认证通过**：PlayerConnect 用 srs_sessionid 作为 pwd，flag=0 实测成功
3. **服务端 idle timeout = 120s**：不是保活问题，是服务端主动断开空闲连接
4. **自动重连已实现**：断线后延迟 2s 自动重连（`RECONNECT_DELAY = 2.0`）

### 8.2 sessionid 有效期

- **会过期**：至少 4 小时（`DEFAULT_TIMEOUT = 14400`，实测可能更长）
- **过期标志**：flag=72 (INVALID_SESSIONID)
- **用户说法不正确**：sessionid 不是永久的

### 8.3 无配置模式数据流

- **extractor 在线时**：被动嗅探 → MJProtocol 解码 → POST /push → 浏览器显示
- **extractor 离线时**：spectator 接管 → TCP 直连游戏服务器 → SRS 握手 → 旁观协议 → POST /push
- **切换逻辑**：`StateStore.should_use_game_client()` 判断 10 秒无推送即切换

### 8.4 软路由常驻

- **纯热点模式**：完全可行，不需要改代码
- **无配置模式**：需要解决 sessionid 过期问题（目前无自动续期方案）
- **云端双连**：不可行（服务端踢手机）

---

## 九、Caveats / Not Found

1. **sessionid 自动续期未实现**：三条假设（A/B/C）均未验证通过，无自动续期方案
2. **旁观模式无隐藏手牌**：ReqRealtimeGameRecord 只能看到牌背，无法获取隐藏手牌
3. **保活测试结果未知**：`scripts/test_keepalive.py` 未看到运行结果
4. **软路由 extractor 未实际部署**：package_extractor.py 已写好，但未在真实软路由上测试
5. **cloud_player 已宣告死亡**：云端双连方案因服务端单连接限制被放弃
