# PRD: MITM 代理手牌修复

## 问题

MITM 热更代理已上线（NetConf 改写 + RespSRSAddr 动态端口劫持），手机通过 ECS 代理连入大厅和游服成功，但存在三个阻塞问题：

### P1: 0x2bc0 手牌数据不显示

**现象**：动态端口代理（ECS:5700~5723）收到手机连接，连接保持正常，但 GameTapDecoder 无任何解码输出，relay 无手牌数据推送。

**根因**：SRS 游服流量是**加密的**（会话密钥 AES-CFB128），代理的 `on_bytes` 拿到的是加密帧流。`MJProtocol` 直接处理加密帧无法解出 0x2bc0 手牌内容——帧头能识别但 payload 是密文。

**需做**：在 `DynamicGameProxyManager` 的游服代理中实现 SRS 密钥学习：
- 从游服握手流（EncryptVer→ReqKey→HandshakeRsp）中学到会话密钥
- 用会话密钥解密 S→C 帧的 payload，再喂给 MJProtocol
- 参考大厅代理的 `LobbyS2CRewriter` 已有密钥学习逻辑

### P2: 移动网络进游戏卡在校验资源

**现象**：手机连自己 4G/WiFi 时打开游戏，卡在"校验资源"阶段；连 ECS 热点时不卡。

**可能原因**：
- 热更下载器 DNS 解析问题（手机自己的 DNS 可能解析不到 ECS）
- 热更文件下载被运营商 CDN 缓存干扰
- NetConf 覆盖不生效（清缓存/重装后丢失）

**需排查**：手机在自己网络下打开游戏时，DNS 解析到哪了、热更请求走哪了。

### P3: 金币局手牌显示

**现象**：当前只验证了友尽局（创建房间），金币局是否走相同协议未确认。

**需验证**：金币局的游服地址是否也在 RespSRSAddr 列表中、端口范围是否相同。

---

## 现有资源

### 代码
- `remote/noconfig/hijack/tcp_proxy.py` — ECS 代理主文件，含 LobbyS2CRewriter、DynamicGameProxyManager、GameTapDecoder
- `remote/srs_spectator/crypto.py` — SRS 加解密实现（SRSCrypto），含默认密钥、会话密钥设置、CFB 加解密
- `remote/srs_spectator/frame.py` — SRS 帧解析（pack_frame/unpack_frame/read_frame_from_stream）
- `remote/srs_spectator/handshake.py` — SRS 握手消息构建/解析
- `stable/protocol.py` — MJProtocol，TCP 流重组 + 帧解码 + 0x2bc0 解析
- `stable/tracker.py` — PacketStateTracker，ProtocolMessage → BattleState

### ECS 服务
- `mahjong-tcp-proxy.service` — 代理主服务（PID 84250），5748/5749/7777 + 动态 5700~5723
- `mahjong-relay-noconfig.service` — :8002 relay，接收 /push 展示手牌
- 安全组已放行 5700-5799

### 关键技术事实
- SRS CFB = 每帧 fresh-from-IV（非连续流），见记忆 srs-cfb-and-string-prefix-fix
- SRS 握手：EncryptVer(msgid=1, 默认密钥加密) → ReqKey(msgid=3) → HandshakeRsp(msgid=4, 默认密钥加密含会话密钥) → PlayerConnect(msgid=5, 会话密钥加密) → PlayerData(msgid=6, 会话密钥加密)
- m_key 不下发（keylen=0），加密始终用会话密钥
- lobby 代理已实现密钥学习：`LobbyS2CRewriter` 从 HandshakeRsp 学会话密钥后改写 RespSRSAddr

---

## 方案

### P1: SRS 密钥学习 + 解密旁路

在 `DynamicGameProxyManager` 创建的每个游服代理中：

1. S→C 方向：拦截 HandshakeRsp(msgid=4)，用默认密钥解出会话密钥
2. 之后所有 S→C 帧：用会话密钥解密 payload → 明文 → 喂给 MJProtocol
3. C→S 方向：原样透传（不解密不解码）

关键：每个游服代理需要自己的 `LobbyS2CRewriter`-like 密钥学习器，但不是改写帧，而是解密后喂给 GameTapDecoder。

### P2: 移动网络校验

排查 DNS + 热更下载链路。可能需要在 ECS 上加 DNS 服务或改热更下载器配置。

### P3: 金币局

真机测试确认即可，预计和友尽局走相同路径。

---

## 验证标准

- [ ] 手机用自己网络进游戏 → ECS 网页显示实时手牌（含增量更新）
- [ ] 金币局手牌正常显示
- [ ] 友尽局手牌正常显示
- [ ] 手牌变化（摸牌/出牌）实时刷新到网页
