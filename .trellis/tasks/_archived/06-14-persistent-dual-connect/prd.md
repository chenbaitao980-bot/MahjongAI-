# 持久双连：手机不卡 + 云端持续读牌

## 模式定位：无配置模式（No-Config）的增强

本任务属于 **无配置模式** 的增强实现，与现有的 VPN 模式和热点模式**完全独立**。

### 现有模式架构

| 模式 | 端口 | 入口 | 数据来源 | 手机要求 |
|------|------|------|----------|----------|
| hotspot | 8000 | `remote/hotspot/` | PC 热点抓包 extractor 推送 | 连 PC 热点 |
| vpn | 8001 | `remote/vpn/` | 云端 ECS VPN 接口抓包 | 配置 IPSec VPN |
| noconfig | 8002 | `remote/noconfig/` | SRS spectator 直连游服 | 无（但需手动抓凭证） |
| cloud | 8003 | `remote/cloud_player.py` | cloud_player 以玩家身份连游服 | 无（需 sessionid） |

### 代码隔离约束（铁律）

1. **不修改 `remote/vpn/` 下任何文件** — VPN 模式已上线，不能动
2. **不修改 `remote/hotspot/` 下任何文件** — 热点模式已上线，不能动
3. **不修改 `remote/relay/core.py` 的现有端点逻辑** — core.py 是四种模式共享的 relay 核心，只允许新增端点/方法
4. **不修改 `remote/cloud_player.py` 的现有接口** — cloud_player 是独立 CLI 工具，只允许新增参数/回调
5. **不修改 `config/settings.yaml`** — 主配置不动，新配置放在 `remote/relay/config_noconfig.yaml` 或新配置文件
6. **新增代码放在 `remote/noconfig/` 或新建 `remote/tcp_proxy/`** — 与现有模式物理隔离
7. **复用而非修改**：需要 stable/protocol.py、stable/tracker.py 等共享模块时，通过 import 复用，不修改其源码

---

## 已验证的事实（2026-06-14 实测）

### 服务器行为模型

1. **同一 sessionid 只允许一条活跃连接**（抢占模式，非共存模式）
2. 后连入的一方占位，先在的一方被踢（Connection closed by server）
3. ECS flag=0 说明服务器认证通过，**但只有独占 session 时才推 0x2BC0 游戏帧**
4. 防火墙封手机 5s 期间：ECS 成功收到完整 0x2BC0 帧（含 314B/329B 大包 = 手牌状态）
5. 封锁解除后手机重连 → ECS 被踢 → 之后再无游戏帧

### 朋友软路由的效果

- 手机完全不卡，正常打牌
- 云端持续读牌
- 手机没装任何东西

### 关键推论

朋友的软路由不是简单地"RST + 等手机重连"。它实现了某种**代理/中继**：
- ECS 连接游服收游戏帧 ✅
- 手机通过软路由继续"打牌" ✅
- 但手机并不直连游服（否则会踢 ECS）

最可能的方案：**软路由做了 TCP 层面的 MITM 代理**。

---

## 方案 A：TCP 代理（MITM relay）— 推荐方案

### 原理

```
手机 ←→ PC 热点 (TCP proxy on port 7777) ←→ 游服 47.96.0.227:7777
                    ↓ (镜像)
                 ECS cloud_player
```

PC 热点作为 NAT 网关，**劫持手机到 47.96.0.227:7777 的连接**：
1. 用 WinDivert/iptables 把手机→47.96.0.227:7777 的流量 DNAT 到 PC 本地 proxy
2. PC proxy 和游服建立真正的 TCP 连接
3. 手机←→proxy←→游服 双向透传全部流量（手机无感知）
4. proxy 同时把游服→手机方向的帧复制一份，发给 ECS

### 优势

- **手机完全不卡**（TCP 透传，延迟 < 1ms）
- **无需 RST 注入**
- **无需防火墙封锁**
- **ECS 不需要连接游服**（直接从 proxy 接收镜像帧）
- 最接近朋友软路由的真实实现

### 实现复杂度

**高**：
- Windows 上 TCP 透明代理需要 WinDivert 或 netsh portproxy（但 netsh portproxy 不支持源 IP 保持）
- 需要正确处理 SRS 加密层（session_key 已知，可解密后转发给 ECS）
- 双向 TCP 流拼接 + SRS 帧边界对齐
- 或者不解密，直接镜像原始 TCP payload 给 ECS（但 ECS 需要同步 session_key）

### 代码组织（遵循隔离约束）

```
remote/
├── tcp_proxy/              ← 新增目录，与 vpn/ hotspot/ noconfig/ 平级
│   ├── __init__.py
│   ├── proxy.py            ← TCP 透明代理核心（WinDivert + 双向透传 + 帧镜像）
│   ├── mirror.py           ← 帧镜像逻辑：SRS 帧边界对齐 → 推送到 relay
│   ├── divert.py           ← WinDivert 流量劫持配置（DNAT 规则管理）
│   └── main.py             ← 独立入口：启动 proxy + divert + 镜像推送
├── vpn/                    ← 不动
├── hotspot/                ← 不动
├── noconfig/               ← 不动（但可能新增调用 tcp_proxy 的入口）
├── relay/
│   ├── core.py             ← 不改现有端点，可新增 /mirror-push 端点
│   └── config_noconfig.yaml ← 可新增 tcp_proxy 相关配置项
└── cloud_player.py         ← 不改现有接口
```

### 关键文件（复用，不修改）

- `stable/protocol.py` — MJProtocol 帧解析（import 复用）
- `stable/tracker.py` — PacketStateTracker 状态重建（import 复用）
- `stable/mapping.py` — MappingStore 字节映射（import 复用）
- `remote/relay/state_store.py` — StateStore 状态存储（import 复用）
- `remote/extractor/capture.py` — Npcap 抓包基础（参考，不修改）

### 技术调研待办

- [ ] Windows 透明 TCP 代理方案：WinDivert vs netsh portproxy vs Npcap + raw socket
- [ ] 朋友的软路由是 OpenWrt 还是 Linux 定制？iptables REDIRECT 直接可用
- [ ] SRS 帧镜像：是否需要解密？还是直接复制加密帧？
- [ ] ECS 接收镜像帧的协议：WebSocket push vs TCP 直连 vs HTTP SSE

---

## 方案 B：持续封锁 + 帧回注（手机走 ECS 代理）— 备选

### 原理

```
手机 → PC 热点 ──(封锁 47.96.0.227:7777)──╳

ECS cloud_player ←→ 游服 47.96.0.227:7777
       ↓ (下行帧)
PC 热点 → 伪装游服回包 → 手机
       ↑ (上行操作)
手机 → PC 热点 → 转发到 ECS → ECS 代发给游服
```

1. **持续封锁**手机→47.96.0.227 的直连（防火墙不解除）
2. ECS 独占游服连接，持续收 0x2BC0 ✅
3. PC 热点**伪装成游服**，把 ECS 收到的帧回注给手机
4. 手机出牌操作被 PC 捕获，转发给 ECS，ECS 代发给游服

### 优势

- **ECS 独占游服连接**，保证持续收帧（已验证可行）
- 无 TCP 代理的复杂性（不需要维护双向 TCP 流状态）

### 实现复杂度

**极高**：
- 需要完全理解并重放 SRS 协议的上下行全部消息类型
- 手机→PC→ECS→游服 的上行链路延迟会显著增加（手机操作会卡）
- 需要在 PC 上运行一个伪游服（accept 手机连接，回放 ECS 帧）
- 帧同步和时序问题（手机收到的帧有延迟，可能导致 UI 错位）

### 评估

比方案 A 复杂得多，且手机体验会有明显延迟。**不推荐优先实现**。

---

## 方案对比

| 维度 | 方案 A：TCP 代理 | 方案 B：封锁+回注 |
|------|-----------------|-------------------|
| 手机体验 | 几乎无感 (< 1ms 延迟) | 明显延迟 (ECS 中继) |
| 实现复杂度 | 高 | 极高 |
| 核心难点 | Windows 透明代理 | 伪游服 + 帧同步 |
| 与朋友软路由相似度 | 很高 | 低 |
| ECS 依赖 | 低（只收镜像帧） | 高（全链路中继） |
| 代码隔离 | 新目录 tcp_proxy/ | 需改多处 |
| **推荐优先级** | **★★★ 优先** | ★ 备选 |

## 推荐路线

**方案 A 优先**，但先做技术调研：
1. 确认 Windows 透明 TCP 代理的可行方案
2. 确认 SRS 帧镜像是否可以不解密直接转发
3. 原型验证：手动用 socat/ncat 搭 TCP proxy，确认手机不卡 + ECS 能收帧

## 验收标准

- [ ] 手机通过 PC 热点打牌，完全不卡（与直连体验一致）
- [ ] ECS 网页持续显示完整手牌
- [ ] 整局手牌持续更新（每次摸牌/出牌/碰吃杠）
- [ ] 手机无需安装任何东西
- [ ] 只需两步操作：连热点 + 运行 bat
- [ ] VPN 模式（:8001）功能不受影响
- [ ] 热点模式（:8000）功能不受影响
- [ ] 无配置模式（:8002）现有功能不受影响
- [ ] cloud_player.py CLI 现有参数行为不变

## Out of Scope

- Linux/OpenWrt 移植（先 Windows）
- 多账号同时监控
- 自动重抓凭证（sessionid 过期后）
- 修改 VPN/热点模式的任何代码
- 修改 settings.yaml 主配置
