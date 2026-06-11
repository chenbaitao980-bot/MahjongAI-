# zero-touch: 远程读牌无感连接

## Goal

手机零配置、零 VPN、零 app，云端独立旁观牌局。通过热点端 extractor 捕获 roomid/gameid，云端 SRS 旁观客户端直连游戏服务器获取实时牌局数据。

## 架构：双通道并行

```
┌─ 通道 A（现有，不动）────────────────────────────┐
│ 手机 VPN → ECS strongSwan → extractor → relay :8000 │
│ （原场景 C，已交付，保持不变）                     │
└────────────────────────────────────────────────────┘

┌─ 通道 B（新增，零配置目标）────────────────────────┐
│                                                    │
│  手机 ──WiFi热点──▶ 本机/软路由                     │
│  (正常打牌)         │ extractor 嗅探                │
│                     │ 提取 handshake_blob            │
│                     │ 提取 auth_token_12b            │
│                     │ 提取 roomid + gameid           │
│                     │ POST /register → cloud relay   │
│                     │                                │
│              云服务器 ECS (8.136.37.136)              │
│              ├─ relay :8000   (通道 A + B 共用)      │
│              └─ srs_spectator (新增)                 │
│                   │ TCP 连 47.96.0.227:7777         │
│                   │ SRS 握手 + 旁观协议              │
│                   │ zlib 解压牌局 → POST /push       │
│                                                    │
└────────────────────────────────────────────────────┘
```

**通道 A**：手机出门用 VPN → 云端被动嗅探 → 已有，不动。

**通道 B**：手机在家连热点 → 本机 extractor 捕获 roomid/gameid → 发送给云端 → 云端 SRS 客户端**主动旁观**获取牌局。手机无 VPN。

## Decision (ADR-lite)

**Context**: 手机零配置为最终目标。已确认：
- Android 无 VPN 自动配路径（12 条路线全部排除）
- 屏幕抓取 <100% 准确率 + 需每局手动
- WireGuard QR 需装 app（不接受）
- 旁观协议需 roomid/gameid（无法从云端获取）

**Decision**: 混合架构——热点端提取 roomid/gameid + 云端 SRS 旁观。热点端用现有 extractor 能力（已成熟），云端新增 SRS 旁观服务。roomid/gameid 来自热点端捕获的手机初始握手流量。

**Consequences**:
- 本机/软路由需常开（手机在家打牌场景）
- 云端 SRS 客户端需独立部署（不碰现有 relay）
- 两种通道并行：VPN（出门） + SRS 旁观（在家）

## Requirements

* [x] 静态反汇编 `libcocos2dlua.so`，确认加密算法和帧格式
* [x] 真机抓包，拿到 SRS 握手完整序列
* [ ] Python 实现 AES-256-CTR + SRS 握手客户端
* [ ] 云端部署 srs_spectator 服务（新端口，不碰现有 relay:8000）
* [ ] 热点端 extractor 捕获并上报 roomid/gameid 到 relay
* [ ] SRS 旁观客户端获取 roomid/gameid 后调用 ReqRealtimeGameRecord
* [ ] 解析 zlib 压缩牌局数据 → snapshot → POST /push
* [ ] 手机端体验验证（开热点→开游戏→云端立即看到手牌，零 VPN）

## Acceptance Criteria

* [ ] 手机连本机热点开游戏打牌，云端 10 秒内显示实时手牌
* [ ] 手机不需要任何 VPN/代理配置
* [ ] 现有 VPN 通道（通道 A）不受影响，独立运行
* [ ] srs_spectator 服务独立部署，不修改 relay 核心代码

## Out of Scope

* 通道 A（VPN 嗅探）的修改 🗑️——已有，不动
* Android VPN 自动配、软路由 captive portal、屏幕抓取等 🗑️——已完整调研排除
* 软路由部署（先在本机验证，后续迁移）

## Technical Notes

### 已确认的技术细节

**加密**: AES-256-CTR 模式
- 默认 Key: `f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b`
- 默认 IV: `15ff010034ab4cd355fea122084f1307`
- 库: BoringSSL (`CRYPTO_ctr128_encrypt`)

**SRS 握手序列**（真机抓包确认）:
```
1. C→S msgid=1 payload=fa60a522 (EncryptVer)
2. S→C msgid=1 (响应)
3. C→S msgid=3 payload=空 (ReqKey)
4. S→C msgid=4 payload=25B (handshake_rsp)
5. C→S msgid=5 payload=80B加密 (PlayerConnect)
6. S→C msgid=6 (PlayerData, 含 sessionid)
7. C→S msgid=23 payload=空 (ReqPlayerPlusData)
8. S→C msgid=24 (RespPlayerPlusData, 含 m_key)
```

**帧格式**: 12 字节头 `[flag:2B][payload_len:2B LE][msg_type:2B LE][sub_type:2B][extra:4B]`

**旁观协议**: `ReqRealtimeGameRecord(roomid, offset, gameid)` → zlib 压缩分片推送

**roomid/gameid 来源**: 热点端 extractor 捕获手机登录后的首次 room enter 消息

### 部署目标

| 组件 | 位置 | 端口 |
|------|------|------|
| relay | 云 ECS (8.136.37.136) | 8000 (不动) |
| srs_spectator | 云 ECS (8.136.37.136) | 8001 (新增) |
| extractor (热点) | 本机 Windows → 后续软路由 | 本地 |
