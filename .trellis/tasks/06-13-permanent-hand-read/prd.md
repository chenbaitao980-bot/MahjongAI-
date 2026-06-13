# 永久手牌读取：可行路径深度分析

## Goal

用户目标：**"连一次热点后，之后任何网络都可以在云端看到自己的手牌"**。

本任务在不写代码的前提下，把所有已知约束和可行路径梳理清楚，给出一条推荐路径，并回答两个核心问题：
1. 旁观模式能否实现这个目标？
2. 如果旁观不行，直接以玩家身份登录是否可行？

---

## 已证明的硬约束（不可绕过）

### 约束 1：手牌是"会话私有"的
服务端只向**该玩家本人的那条 TCP 会话**发送隐藏手牌。  
- 旁观（ReqRealtimeGameRecord, msgid=3000）：用户肉眼实机确认 → **只能看到牌背**，服务器不发隐藏手牌。
- 牌局帧（0x2bc0）在 7777 端口明文传输，但只流向"在桌的那条会话"。

### 约束 2：同账号同桌单连接（接管语义）
第二条连接以同账号"重连"进同一桌，服务器把座位给新连接、**踢掉旧连接**（手机掉线）。

### 约束 3：持续读牌需要持续数据通道
实时手牌每巡都变 → 需要**持续**的数据访问，一次性凭证不够。

### 逻辑推论
∴ **"连一次热点 + 之后任何端不挂任何东西 + 云端实时读手牌"在物理上不可能**——要持续手牌，必有一个持续数据通道。

---

## 问题一：旁观模式能否实现目标？

**结论：不能。**

旁观模式可以做到：
- ✅ 云端维持长期旁观连接（已实现 auto-reconnect，srs_sessionid 4h+ 有效）
- ✅ 看到公开信息（他家弃牌、鸣牌、剩余牌数、对局房间信息）
- ✅ 不需要用户连接任何东西（无配置模式）

旁观模式做不到：
- ❌ 自己的隐藏手牌（服务器设计决定，牌背是协议层面的限制，不可绕过）
- ❌ 摸到了什么牌（摸牌事件对旁观者不可见）

旁观模式适合的场景：辅助看别人打牌、记录对局公开信息，**不适合"看自己手牌给自己 AI 建议"这个核心场景**。

---

## 问题二：直接以玩家身份登录能否实现目标？

**结论：技术上能看到手牌，但会踢掉手机（手机无法同时打牌）。**

如果云端以用户的账号身份完成 SRS 握手 + PlayerConnect（usertype=7，flag=0），进入同一牌桌：
- ✅ 云端持有玩家本人的会话 → 天然接收到隐藏手牌（0x2bc0 帧）
- ✅ 本轮所有 SRS 加密破解成果可复用（flag=0 已实现）
- ❌ 服务端"重连=接管"语义 → 手机被踢出局、无法继续玩牌
- ❌ 用户体验断裂：必须选择"手机玩"或"云端AI看手牌"，不能同时

**适用条件**：云端彻底接管游戏会话（"在云端/网页上玩麻将"），手机只是显示/操作的输入终端。这是一个大架构重构，不是"辅助工具"而是"云端麻将客户端"。

---

## 三条可行路径对比

| 路径 | 手机能玩 | 任意网络 | "连一次"代价 | 工程量 | 状态 |
|------|--------|---------|------------|--------|------|
| **A. VPN 隧穿（已上线）** | ✅ 正常玩 | ✅（VPN always-on 透明） | 一次性装 VPN 配置 | 已完成 | **已上线** |
| **B. Frida Siphon（推荐下一步）** | ✅ 正常玩 | ✅（HTTP POST 用手机自身网络） | 一次性装重打包 APK | 中等 | 未开始 |
| **C. 云端当玩家** | ❌ 手机被踢 | ✅ | 一次性提取凭证 | 大 | 未开始 |

### 路径 A 现状与局限

**已上线（2026-06-13 真机验证通过）。**

- 手机装 IKEv2/IPSec PSK VPN，once configured，forever on
- 所有游戏流量经云端 → ECS 被动嗅 7777 明文帧 → stable 解码 → 手牌
- "任意网络"通过 always-on VPN 实现（4G/5G/WiFi 透明切换）
- 唯一用户代价：手机需保持 VPN 常连（Android 支持 always-on，丢失时自动重连）
- 局限：VPN 会把**全部手机流量**路由到云端（全量隧道，split tunnel 不支持）

**对用户来说**："连一次热点" → 改成 → "装一次 VPN" — 其实已经满足目标精神了，只是"连接方式"从热点改成了 VPN。

### 路径 B — Frida Siphon（最接近目标精神）

**真正做到：任意网络 + 手机正常玩 + 无 VPN 负担。**

架构：
```
手机（任意网络，正常玩，不踢线）:
  游戏进程（重打包 APK + Frida gadget[script 模式]）
    └─ siphon.js（gadget 自动加载）:
        - hook libc recv/read（抓游戏服连接的入向帧）
        - 识别 0x2bc0 牌局帧 → HTTP POST 到云端 relay
        - 走手机自己的 4G/WiFi → 对游戏服完全透明

云端 ECS:
    POST /ingest 收原始帧
      → stable 解码 MJProtocol/PacketStateTracker
      → BattleState（手牌/弃牌/建议）
      → 网页展示
```

"一次性代价"：用户安装一次重打包 APK（有 Frida gadget）。

**已有基础**：
- 重打包 APK 已有（gadget 内置）
- hook_hand.js 原型已有（能拿到入向帧）
- stable 解码器完整可用
- relay + 网页展示完整可用

**缺失**：
- siphon.js：在 hook 内发 HTTP POST（Frida Socket/NativeFunction）
- relay `/ingest` 端点：收帧 → 喂解码器（把 extractor 解码逻辑移入 relay）
- gadget script 模式自治：脱离 PC Frida server，游戏启动即自动加载 siphon.js
- live 手牌捕获验证（上次只到心跳，无活跃牌局）

### 路径 C — 云端当玩家（大工程，暂不考虑）

需要实现完整的云端麻将游戏客户端（大厅登录、游戏流程、操作回传），用户 UX 变成在网页上玩麻将，不是"手机原生玩 + AI 辅助"。工程量大，偏离原始场景，暂排除。

---

## 推荐路径

```
现在   ──────── 路径 A（VPN）已上线，满足大部分需求
                ↓ 如果用户不想挂 VPN
下一步 ──────── 路径 B（Frida Siphon）——唯一同时满足"任意网络+手机正常玩+看自己手牌+无VPN"
```

**路径 B 里程碑（参考 siphon-final-goal.md）**：
- M1：live 验证手牌捕获（hook_hand.js sticky game-fd，在活跃牌局抓 0x2bc0 → stable 解码 → 打印手牌）
- M2：siphon.js 自推（hook 内 HTTP POST 帧到云端 relay）
- M3：relay /ingest 解码 + 网页（云端收帧 → 解码 → 展示）
- M4：gadget 自治（script 模式，拔掉 PC，手机换网验证云端仍更新）
- M5：稳健性（断线重连、批量节流、隐私）

---

## 核心问题的答案（供用户决策）

**Q：旁观模式能否实现目标（看自己手牌）？**  
A：**不能。** 协议层面，旁观者只收到牌背，这是服务端设计决定的，无法绕过。

**Q：直接登录以玩家身份可以看手牌吗？**  
A：**技术上可以，但会踢掉手机，手机无法同时打牌。** 适用于"彻底改成云端玩麻将"的架构，不适合"手机原生玩+AI 辅助看手牌"的场景。

**Q：离"连一次即永久看手牌"还差多远？**  
A：
- 如果接受 VPN：**已经到了**（路径 A 已上线，always-on VPN 一次配置）
- 如果不要 VPN：**中等工程量**（路径 B，Frida siphon，约 4 个里程碑，需 1~2 周）

---

## Open Questions

1. **用户接受 VPN 方案吗？**（VPN always-on 对 4G 流量/电量有轻微影响）
2. **如果做 Frida siphon，优先做哪个里程碑（M1 验证 vs 直接 M2 推流）？**
3. **gadget 配置方式**：APK 内嵌 siphon.js（稳定但需重打包）vs /data/local/tmp 热更新（需 root 或 ADB 每次覆盖）

## Out of Scope

- 旁观模式的进一步研究（已证死路）
- 云端当玩家方案（工程量太大，偏离场景）
- 视觉模式（截图识别）

## Technical Notes

**已有可复用资产**：
- `frida/hook_wire.js`, `hook_wire2.js` — recv hook 框架
- `apk/` — 重打包 APK（含 gadget）
- `stable/` — MJProtocol + PacketStateTracker（完整解码器）
- `remote/relay/` — relay 服务 + 网页展示
- SRS 认证破解（flag=0 已实现，auth_token_12b + handshake_blob + srs_sessionid）

**关键研究档案**：
- `.trellis/tasks/archive/06-11-srs-client-finish/research/siphon-final-goal.md` — Frida siphon 完整方案设计
- `.trellis/tasks/archive/06-11-srs-client-finish/research/final-architecture-plan.md` — 三路径排除逻辑（证据级）
- `.trellis/spec/backend/remote-access.md` §1.6 — SRS 实测结论（idle timeout/reconnect/旁观局限）
