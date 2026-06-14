# Research: 远程读牌技术路线全景调研

- **Query**: 调研项目"远程读牌"所有技术资料、已尝试路线、困难与突破
- **Scope**: internal (项目代码 + trellis 任务记录 + Frida 脚本)
- **Date**: 2026-06-13

---

## 一、项目背景与目标

**用户目标**："连一次热点拿到凭证，之后任意网络在云端实时看到自己的手牌（无 VPN、原装 APK、手机正常打牌）"。

该目标涉及四个核心约束：
1. **无 VPN**：手机侧无需配置 VPN
2. **原装 APK**：手机侧零修改
3. **任意网络**：离开热点后仍能读牌
4. **实时手牌**：云端能看到用户自己的隐藏手牌

---

## 二、已尝试的技术路线（按时间顺序）

### 路线 A：热点嗅探 + 被动解码（Hotspot Sniffing）

**原理**：手机连 PC 热点，PC 用 Npcap/tcpdump 嗅探 7777 端口流量，提取 0x2bc0 游戏帧，解码手牌。

**实现文件**：
- `remote/extractor/main.py` — extractor 主应用
- `remote/extractor/capture.py` — 跨平台抓包适配层（Npcap/tcpdump）
- `remote/extractor/token_extractor.py` — 从协议流提取认证凭证
- `stable/protocol.py` — MJProtocol 协议解码
- `stable/tracker.py` — PacketStateTracker 状态追踪

**状态**：已上线，是**当前主要工作模式**。
- 端口：8000（热点 relay）
- 限制：手机必须在 PC 热点范围内

**核心代码**（`remote/extractor/main.py:175-206`）：
```python
def _on_packet(self, pkt):
    messages = self._proto.process_packet(pkt)
    for msg in messages:
        self._extractor.feed(msg)  # 提取凭证
        self._srs_extractor.feed(msg)  # 提取 SRS sessionid
        changed = self._tracker.apply(msg)
        if changed:
            snapshot = self._tracker.snapshot()
            push(self.relay_url, self.api_token, snapshot)
```

---

### 路线 B：VPN 隧穿（Phone VPN）

**原理**：手机配置 IPSec IKEv2 VPN 连云端，所有游戏流量经云端 ECS，云端 tcpdump 嗅探。

**实现文件**：
- `remote/vpn/app.py` — VPN 模式 relay（端口 8001）
- `remote/extractor/vpn/` — VPN 配置与部署
- `remote/extractor/package_extractor.py` — 打包 extractor bundle（含 VPN 支持）

**状态**：已部署上线（`vpn-readhand-deployed.md`）。
- 端口：8001
- 限制：需要手机配置 VPN，"任意网络"通过 VPN 实现

**五个真机坑**（已解决）：
1. 全量隧道（非 split tunnel）
2. SLL2 兼容性
3. token 一致性
4. UDP 500-4500 端口
5. PSK 类型

---

### 路线 C：云端双连 / Cloud Player（Phase B）—— **已宣告死亡**

**原理**：连一次热点提取 srs_sessionid，之后云端用该 sessionid 以玩家身份连接游戏服务器，接收 0x2bc0 手牌帧。

**实现文件**：
- `remote/cloud_player.py` — SRSPlayerClient 类
- `remote/capture_credentials.py` — 两阶段抓包（Phase 1 提取凭证，Phase 2 触发 cloud_player）
- `remote/relay/core.py` — cloud 模式 relay（端口 8003）

**死亡原因**（`prd.md:129-143`）：
> **实测现象**：cloud_player 连接 47.96.0.227:7777，auth flag=0，但服务端 **2~3 秒内主动关闭连接**，手牌帧 = 0。多次重试结论一致。
>
> **根因**：服务端强制单连接。同一 srs_sessionid 只允许一条 TCP 连接存活：手机在线时 cloud_player 被踢；手机离线时 cloud_player 能连但无手牌。

**关键代码**（`remote/cloud_player.py:236-278`）：
```python
IDLE_GAME_TIMEOUT = 60  # 1 minute

def _connect_once(self):
    # ... 连接游戏服务器 ...
    # Wait for recv thread, enforce idle-game timeout
    deadline = time.monotonic() + self.IDLE_GAME_TIMEOUT
    while recv_thread.is_alive():
        if self._game_frames_received == 0 and time.monotonic() > deadline:
            self._client.disconnect()
            break
```

---

### 路线 D：SRS 旁观协议（No-Config / Spectator）

**原理**：利用 SRS 旁观协议直连游戏服务器，无需手机任何配置。

**实现文件**：
- `remote/srs_spectator/client.py` — SRSClient 类
- `remote/srs_spectator/spectator.py` — SpectatorClient 旁观协议
- `remote/srs_spectator/handshake.py` — SRS 握手构建
- `remote/srs_spectator/crypto.py` — AES-CFB128 加密
- `remote/noconfig/app.py` — 无配置模式 relay（端口 8002）

**状态**：协议已破解，但**旁观记录不含隐藏手牌**。

**关键发现**（`final-architecture-plan.md`）：
> 旁观（ReqRealtimeGameRecord）**实测只能看到牌背**，服务器**不给旁观者发隐藏手牌**。Frida 抓到的旁观记录含玩家 numid/头像/房规/IP，但**无隐藏手牌**。

**协议常量**（已钉死）：
- `ReqRealtimeGameRecord` = 3000 (0x0BB8)
- `RespRealtimeGameRecord` = 3001 (0x0BB9)
- processid = 100 (IMProtocol) 或 1006 (MatchLinkProtocol)

---

### 路线 E：Frida Siphon（手机端 Hook）—— **理论可行但未实现**

**原理**：在手机进程内用 Frida hook `recv()`，捕获入向的 0x2bc0 游戏帧，HTTP POST 到云端 relay。

**实现文件**：
- `frida/hook_hand.js` — 手牌 siphon 核心脚本
- `frida/hook_srs.js` — 完整 SRS hook（含加密/解密/网络）
- `frida/hook_wire.js` / `hook_wire2.js` — 底层 TCP 抓包
- `frida/hook_key.js` — AES 密钥提取
- `frida/hook_lobby_key.js` — 大厅层密钥 + 明文捕获
- `frida/setup_gadget.py` — Gadget 部署脚本
- `frida/run_lobby_hook.py` — Frida Python API 驱动

**状态**：脚本已写，但**需要重打包 APK + root**，不满足"原装 APK"约束。

**架构**（`siphon-final-goal.md`）：
```
手机(任意网络, 重打包APK + gadget):
  游戏进程
    └─ siphon.js (gadget 自动加载):
        - hook libc recv/read/recvfrom
        - 抓游戏服连接的入向帧
        - 批量 HTTP POST 到云端 relay

云端 ECS relay:
  POST /ingest 收原始帧
    → MJProtocol 重组 + PacketStateTracker 解码
    → BattleState
    → 网页展示
```

---

### 路线 F：热点实时解码（Hotspot Live Decode）—— **当前推荐替代方案**

**原理**：PC 热点本来就能看到手机和服务器之间的所有 TCP 流量。0x2BC0 手牌帧经过 PC 时，`NpcapCaptureAdapter` 已经在捕获，`MJProtocol` 已能解码。完全不需要第二连接到游戏服务器。

**架构**（`prd.md:146-209`）：
```
手机 ↔ PC热点(NpcapCapture, port 7777) ↔ 游戏服务器
              ↓ 被动嗅探（无第二连接）
       MJProtocol.process_packet() → 已有
              ↓
       PacketStateTracker.on_message() → 已有
              ↓
       BattleState.snapshot()
              ↓
       POST http://8.136.37.136:8003/push
              ↓
       浏览器实时显示手牌
```

**优势**：
- 完全绕开服务端单连接限制
- 零检测风险（纯被动嗅探）
- 100% 复用 stable/ 现有解码器

**限制**：手机必须在 PC 热点范围内（与路线 A 相同）。

---

## 三、SRS 加密协议破解（关键突破）

### 3.1 加密链

| 阶段 | 算法 | 密钥 | 来源 |
|---|---|---|---|
| 默认加密 | AES-256-CFB128 | `f362120513e389ff...` | 硬编码在 .rodata |
| HandshakeRsp | AES-CFB128 | session_key | 服务端下发 |
| PlayerConnect | AES-CFB128 | session_key | 客户端用 session_key 加密 |
| PlayerData | AES-CFB128 | session_key | 服务端响应 |
| 后续游戏帧 | AES-CFB128 | m_key | RespPlusData 下发 |

### 3.2 关键常量

- **默认 key**：`f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b` (32B)
- **IV**：`15ff010034ab4cd355fea122084f1307` (16B)
- **模式**：AES-CFB128（不是 CTR！）

### 3.3 PlayerConnect 格式（80 字节，已验证）

```
[0]     uint8   clienttype = 2 (MOBILE)
[1]     uint8   usertype = 7 (SESSION)
[2:6]   uint32  areaid = 7109 (LE)
[6:7]   uint8   uid_len = 15
[7:22]  bytes   userid = "newpt1084306678"
[22:38] bytes   pwd = sessionid (16B)
[38:39] uint8   id_len = 12
[39:51] bytes   identify = "020000000000"
[51:55] int32   ver = 0
[55:59] int32   channelid = 70900
[59:63] int32   osver = 10160
[63:64] uint8   id_len = 12
[64:76] bytes   identify = "020000000000"
[76:80] int32   nGameID = 900535
```

### 3.4 flag 含义

- `flag=0`：成功
- `flag=41`：格式错误（PlayerConnect 字段错位）
- `flag=72`：令牌过期（sessionid 过期）

---

## 四、"云端双连"为什么失败

### 4.1 服务端单连接机制

游戏服务器对同一 `srs_sessionid` 强制单连接：
- 新连接到达 → 服务端 2~3 秒内主动关闭旧连接
- 手机在线时 → cloud_player 被踢
- 手机离线时 → cloud_player 能连但无手牌（游戏已结束）

### 4.2 实测证据

`prd.md:129-143`：
> cloud_player 连接 47.96.0.227:7777，auth flag=0，但服务端 2~3 秒内主动关闭连接，手牌帧 = 0。多次重试结论一致。唯一例外：20:52 那次收到 8 帧，但均为 `phase=idle, hand=[]`（手机已离局）。

### 4.3 根本原因

`final-architecture-plan.md`：
> 同账号同桌单连接（断线重连=接管语义）：第二条连接以同账号"重连"进同一桌，服务器把座位给新连接、**踢掉旧连接**（手机掉线）。

---

## 五、可行替代方案总结

| 方案 | 约束满足度 | 状态 | 限制 |
|---|---|---|---|
| **热点实时解码**（推荐） | 无VPN、原装APK、实时手牌 | 已实现 | 必须在热点内 |
| **VPN 隧穿** | 无配置、实时手牌 | 已部署 | 需配置VPN |
| **Frida Siphon** | 任意网络、实时手牌 | 脚本就绪 | 需root+重打包APK |
| 云端双连 | 任意网络 | **已死亡** | 服务端踢线 |
| SRS 旁观 | 无配置 | 协议已破 | 无隐藏手牌 |

---

## 六、关键文件清单

### 核心代码
| 文件 | 作用 |
|---|---|
| `remote/relay/core.py` | RelayApp 多模式核心 |
| `remote/relay/main.py` | 多模式启动入口 |
| `remote/relay/static/index.html` | 实时手牌展示页 |
| `remote/cloud_player.py` | SRSPlayerClient（Phase B，已死亡） |
| `remote/capture_credentials.py` | 两阶段抓包（Phase 1+2） |
| `remote/extractor/main.py` | extractor 主应用 |
| `remote/extractor/capture.py` | 抓包适配层 |
| `remote/extractor/token_extractor.py` | 凭证提取 + SRS sessionid |
| `remote/srs_spectator/client.py` | SRSClient |
| `remote/srs_spectator/spectator.py` | SpectatorClient |
| `remote/srs_spectator/crypto.py` | AES-CFB128 |
| `remote/srs_spectator/handshake.py` | PlayerConnect 构建 |
| `stable/protocol.py` | MJProtocol 协议解码 |
| `stable/tracker.py` | PacketStateTracker |

### Frida 脚本
| 文件 | 作用 |
|---|---|
| `frida/hook_hand.js` | 手牌 siphon |
| `frida/hook_srs.js` | 完整 SRS hook |
| `frida/hook_wire.js` | 底层 TCP 抓包 |
| `frida/hook_key.js` | AES 密钥提取 |
| `frida/hook_lobby_key.js` | 大厅层密钥 + 明文 |
| `frida/setup_gadget.py` | Gadget 部署 |
| `frida/run_lobby_hook.py` | Python API 驱动 |

### 研究文档
| 文件 | 作用 |
|---|---|
| `.trellis/tasks/06-13-permanent-hand-read/prd.md` | Phase B PRD + 实测结论 |
| `.trellis/tasks/archive/06-11-srs-client-finish/research/srs-fully-solved.md` | SRS 协议完全破解 |
| `.trellis/tasks/archive/06-11-srs-client-finish/research/srs-key-derivation.md` | AES 密钥推导 |
| `.trellis/tasks/archive/06-11-srs-client-finish/research/srs-spectator-protocol.md` | 旁观协议常量 |
| `.trellis/tasks/archive/06-11-srs-client-finish/research/final-architecture-plan.md` | 最终架构方案 |
| `.trellis/tasks/archive/06-11-srs-client-finish/research/siphon-final-goal.md` | Siphon 最终目标 |

---

## 七、Caveats / Not Found

1. **Frida Siphon 未实际跑通**：脚本已写，但需要 root + 重打包 APK，不满足"原装 APK"约束。
2. **热点实时解码未完整实现**：PRD 中已给出代码片段，但 `remote/capture_credentials.py` 的 Phase 2 仍触发 cloud_player，未改为直接解码。
3. **SRS 旁观协议 sub_type/extra 映射**：部分 processid 的 wire 映射仍未完全钉死。
4. **大厅登录层重放性**：虽然 PlayerConnect 已验证 flag=0，但大厅登录帧的完整重放链尚未实测。
