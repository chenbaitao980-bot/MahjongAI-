# 云端以玩家身份读取手牌（Path C 实现）

## Goal

**用户目标**："连一次热点拿到凭证，之后任意网络在云端实时看到自己的手牌（无 VPN、原装 APK、手机正常打牌）"。

实现路径：云端用玩家本人的 srs_sessionid 以玩家身份连接游戏服，持续接收 0x2bc0 手牌帧，解码后展示在网页。

---

## 核心假设（待实测验证）

**假设：服务端允许同账号双连接共存，不踢手机**。

- 现有研究结论是"重连=接管"，但该结论来自同一座位重连场景
- 本方案用不同 usertype / 连接方式，需要 live 实测验证是否真的踢线
- **如果踢线**：退回到"连热点期间短暂双连"或其他方案，本 PRD 需要修订

---

## 方案架构

```
Phase A — 凭证提取（连一次热点，约1分钟）:
  手机连 PC 热点
    → ECS 被动嗅 7777 + SRS 握手包
    → 提取 srs_sessionid（SRS 握手中明文或可解密）
    → 提取当前桌号 / room_id（PlayerConnect 帧）
    → 存入云端 credential store

Phase B — 云端双连（断开热点，任意网络）:
  ECS 用存储的 srs_sessionid
    → SRS 握手（auth_token_12b + handshake_blob，已知推导方式）
    → PlayerConnect（usertype=7，flag 目标=0）
    → 进入同一牌桌
    → 接收 0x2bc0 手牌帧
    → stable/MJProtocol + PacketStateTracker 解码
    → BattleState → 网页展示

Phase C — 凭证刷新:
  srs_sessionid 4h+ 有效
  → 过期后再连一次热点重新提取
```

---

## 里程碑

| # | 里程碑 | 交付 | 验收 |
|---|--------|------|------|
| M1 | 凭证提取自动化 | 热点连接时自动抓 srs_sessionid + room_id 存云端 | 控制台打印 `sessionid=xxx room=yyy` |
| M2 | 云端 PlayerConnect flag=0 | 用存储凭证完成 SRS 握手，flag=0 | 日志显示 `flag=0 connected` |
| M3 | 双连不踢手机（实测）| 云端连线后手机继续收到游戏帧 | 手机正常出牌，无断线提示 |
| M4 | 实时手牌接收 | 云端收到 0x2bc0 帧并解码 BattleState | 打印出本人手牌 |
| M5 | 网页展示 | relay `/ingest` + 网页更新 | 浏览器实时显示手牌 + AI 建议 |
| M6 | 稳健性 | 断线重连、凭证过期提示 | 断网 30s 后自动重连，过期时网页提示"请重连热点" |

---

## 约束

- **无 VPN**：Phase B 不依赖任何 VPN
- **原装 APK**：手机侧零修改
- **Phase A 代价**：每隔 4h 连一次热点（可接受）

---

## 关键技术点

### 凭证提取（Phase A）

现有能力：
- ECS 已在热点网络下能嗅 7777 明文帧（VPN 上线时已验证）
- SRS 握手加密已破（AES-256-CFB128 + 静态 default key + 会话 key 线缆下发）
- `srs_sessionid` 在 SRS 握手中由服务器下发，可从解密后的包中提取

需验证：srs_sessionid 在哪个 SRS 消息中出现（PlayerConnect response 还是 SessionInit？）

### 云端 SRS 认证（Phase B）

已有：
- `auth_token_12b` 推导方式（已实现，见 srs-key-derivation.md）
- `handshake_blob` 构造方式
- `PlayerConnect usertype=7` 已验证 flag=0（凭证新鲜时）

缺失：
- srs_sessionid 从 pcap 中自动提取的解析器
- 云端 SRS client（Python，复用现有握手逻辑）

### 双连不踢验证（M3 关键）

策略：
1. 先用 PC Frida server 手动测试：手机在牌局中，PC 同时以相同账号 PlayerConnect
2. 观察手机是否掉线
3. 如果踢线：测试不同 usertype（只读/观战身份但带手牌权限？）或 连接时序优化

---

## Open Questions

1. **srs_sessionid 精确位置**：在 SRS 握手哪条消息中？格式？（需 pcap 分析）
2. **双连是否踢手机**：必须 live 实测才知道（M3）
3. **room_id 来源**：从 PlayerConnect 请求帧提取，还是有专门的房间信息帧？

---

## 已有可复用资产

| 资产 | 位置 | 用途 |
|------|------|------|
| SRS 握手破解 | `srs-key-derivation.md`, `srs-fully-solved.md` | Phase B 认证 |
| stable 解码器 | `stable/protocol.py`, `stable/tracker.py` | 解码手牌帧 |
| relay + 网页 | `remote/relay/` | 网页展示 |
| pcap 解密工具 | `srs-pcap-decrypt-attempt.md` | Phase A 凭证提取 |
| Npcap 嗅探 | `stable/capture.py` | 热点嗅探 |

---

## Out of Scope

- 旁观模式（死路，协议层无手牌）
- Frida Siphon / APK 修改
- VPN 方案

---

## 实测结论（2026-06-13）

### Phase B（云端双连）已宣告死亡

**实测现象**：
- cloud_player 连接 47.96.0.227:7777，auth flag=0 ✅
- 服务端 **2~3 秒内主动关闭连接**，手牌帧 = 0
- 多次重试，结论一致
- 唯一例外：20:52 那次收到 8 帧，但均为 `phase=idle, hand=[]`（手机已离局）

**根因**：服务端强制单连接。同一 srs_sessionid 只允许一条 TCP 连接存活：
- 手机在线 → cloud_player 被踢（2~3s 内关闭）
- 手机离线 → cloud_player 能连但无手牌（游戏已结束）
- 下局手机重连 → cloud_player 再次被踢

**M3 假设已证伪**：服务端踢新连接（不踢手机），Phase B 架构根本无法运行。

---

## 新方案：热点实时解码（Hotspot Live Decode）

### 核心洞察

PC 热点本来就能看到手机和游戏服务器之间的所有 TCP 流量。0x2BC0 手牌帧经过 PC，`NpcapCaptureAdapter` 已经在捕获，`MJProtocol` 已能解码，`PacketStateTracker` 已能转成手牌列表。

**完全不需要第二条连接到游戏服务器。**

### 新架构

```
手机 ↔ PC热点(NpcapCapture, port 7777) ↔ 游戏服务器
              ↓ 被动嗅探（无第二连接）
       MJProtocol.process_packet()  → 已有
              ↓
       PacketStateTracker.on_message() → 已有
              ↓
       BattleState.snapshot()
              ↓
       POST http://8.136.37.136:8003/push
              ↓
       浏览器实时显示手牌 ✅
```

### 优势

| 对比项 | Phase B（云端双连）| 热点实时解码 |
|--------|------------------|-------------|
| 服务端单连接限制 | 致命阻塞 | 完全绕开（被动嗅探）|
| 检测风险 | 有（异地 IP 连接同账号）| 零（纯被动）|
| 代码复用 | 需要新建 cloud_player | 100% 复用 stable/ 现有解码器 |
| 约束 | 任意网络（但被服务端踢）| 手机必须在 PC 热点 |

### 实现要点

仅需修改 `remote/capture_credentials.py` 的 Phase 2：

```python
# Phase 2: 从热点流量直接解码手牌（无需 cloud_player）
from stable.tracker import PacketStateTracker
from stable.mapping import MappingStore

self._tracker = PacketStateTracker(MappingStore())  # init时

# _on_packet Phase 2 block:
changed = self._tracker.on_message(msg)
if changed and self._has_hand_tiles():
    self._push_state_to_relay()  # POST /push 到 ECS
```

### 新里程碑

| # | 里程碑 | 验收 |
|---|--------|------|
| M1 ✅ | 凭证提取 + 云端上传 | 已完成 |
| M2 ✅ | flag=0 认证 | 已完成（但 Phase B 死路）|
| M3 ❌ | 双连不踢 | **已证伪，Phase B 放弃**|
| M4-new | 热点实时解码 → POST /push | 浏览器显示手牌 |
| M5 | 网页展示（relay 已有 /push）| 已有，无需改 |

### 约束更新

- **必须保持热点连接**：手机打牌期间需连着 PC 热点（已是现有前提）
- **Phase B 删除**：cloud_player 不再用于手牌接收（凭证上传仍保留）
