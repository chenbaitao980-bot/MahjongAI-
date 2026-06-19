# N6 Fuzz Strategy — Hidden Protocol Dictionary Scan

- **Query**: 给定 `xyid_closed_set.json`（155 个 [1, 5000] 已知 ID），制定 fuzz 战术，目标找服务端**已实现**但客户端**未声明**的隐藏协议。
- **Scope**: mixed — 静态闭集 + 网络扫描计划
- **Date**: 2026-06-19
- **Goal**: 突破 H16（服务端 view filter 把对手 hand_raw 替换 0x3c），找到不经 view filter 的 dump/admin/debug 协议直接读对手手牌。

---

## §1 Fuzz 范围与采样空间

| 项 | 值 |
|---|---|
| **总区间** | `[1, 5000]` (任务规格) |
| **已知（来自 lua dispatch）跳过列表** | 155 个（见 `xyid_closed_set.json`） |
| **真正待扫候选** | 5000 - 155 = **4845** unknown msg_type |
| **sub_type (processid) 矩阵** | `{0, 1, 84, 92, 100, 1006}`（6 个）— wire 实测见过的 |
| **拓展 sub_type（可选第 2 轮）** | `{3, 30, 62, 113, 116, 120, 140, 141, 147}`（lua 闭集中所有声明 processid，9 个） |
| **每 (msg_type, sub_type) 组合数（核心）** | 4845 × 6 = **29,070 帧** |
| **每 (msg_type, sub_type) 组合数（核心+拓展）** | 4845 × 15 = **72,675 帧** |
| **限速** | ≤10 帧/秒（接近主号 IM 心跳 100s/帧 的 1000× 上限，仍远低于 frontend per-conn rate limit） |
| **核心扫单跑预期时长** | 29,070 / 10 ≈ **2,907 秒 ≈ 48 min** |

**为什么 5000 够？**
1. lua 闭集中最大 ID 是 25201（MatchLinkProtocol RespNotifyTaskPercent），但 [25000, 25201] 是 MatchLink 段；除此之外 99% 的客户端 ID 落在 [1, 3003]。服务端隐藏协议大概率紧邻已知功能区。
2. >5000 的高编号通常是 game-loop in-band sub_cmd（0x2BC0/11201/12xxx），路由器层根本不当 XY_ID 看，fuzz 该段无意义。
3. Manfred 论 (DEFCON 25) 商业 MMO 实测：99% 的 dev 接口落在 base+[0..256] 邻域，主要 ID 不会跳到 8000+。

---

## §2 探测目标分级

### A 级（必扫，~600 ID）

依据：**与已知 admin/dump/debug 风格邻近**或**客户端空白带**。

#### A.1 lua 显著空白带

| 区间 | 已知数 | 优先级 | 理由 |
|---|---|---|---|
| **[1001, 3000]** | 0 | ★★★ | 完全空白；典型 game-server "internal/admin" 段 |
| **[3004, 5000]** | 0 | ★★★ | 紧邻 spectator(3000-3003)，dev/dump 协议高发邻域 |
| **[479, 500]** | 0 | ★★ | IMProtocol 478 之后到 BagSys 501 之前空白带；可能藏 IM 内部 admin |
| **[613, 1000]** | 0 | ★★ | BagSys 末尾到 1000 完全空白 |

#### A.2 已知功能区邻域 ±50

| 锚点 | 邻域 | 理由 |
|---|---|---|
| RoomProtocol.ReqJoinTable=13 ±50 | [1, 63] (减去已知) | join/start/dump-table 风格高发 |
| GameProtocol.TableInfo=11014（空白带外，跳过；但 in-band 11000-11074 不在 [1,5000]） | — | 跳过 |
| IMProtocol 478 (NotifyFriendListChange) ±50 | [479, 528] | IM 内部 admin |
| MatchLinkProtocol 25xxx 段 | 不在 [1,5000] | 跳过 |
| TeaHouse 591 (NotifyCardCount) ±100 | [479, 691] | tea-house "operation"/"audit" 高发 |
| spectator 3000-3003 ±100 | [2900, 3100] | record/dump/replay 高发邻域 ⭐ |

**A 级总计 ~600 个 (msg_type, sub_type=multiple)**：
- [1001, 3000] 全段（2000 IDs）× 6 sub_types = **12,000 帧**
- [3004, 5000] 全段（1996 IDs）× 6 sub_types = **11,976 帧**
- [479, 500] 区间（22 IDs）× 6 sub_types = **132 帧**

→ 实际 A 级 fuzz 帧数 ≈ **24,108 帧**，~ 40 min @ 10 fps

> **注意**：A.1 的两个大空白带（[1001,3000] + [3004,5000] = ~4000 IDs）已经覆盖了 [1,5000] 中绝大多数 unknown。所以 A 级 ≈ B 级 — 单跑 [1, 5000] × 6 sub_types 就够了。

### B 级（覆盖，~21,000 ID-pairs）

剩余 unknown ID 全扫一遍，作为兜底。
- **[1, 1000]** 中 unknown: 1000 - 155 = 845 IDs（去重已知）× 6 sub_types = ~5,070 帧

→ A + B 合计 ≈ **29,070 帧**（即第 1 节"核心扫单跑"）。

---

## §3 响应分类规则（Response Classifier）

每个 fuzz request 发出后，**等待 3 秒**（task 规格），按以下规则分类：

| 触发条件 | 分类 | 含义 | 后续动作 |
|---|---|---|---|
| 45s 完全无响应（连发多个无回） | `silent` | msg_type 路由不存在 | 排除 |
| 收到 `msg_type=9` (REPORTSRSERR) 回包，body 含 SRSNOROUTE/3 | `not-routed` | 服务端 frontend 不认（bag/im 没路由） | 排除 |
| 收到 `msg_type=9` 但错误码 != SRSNOROUTE | `acl-rejected` | **frontend 知道但拒绝** ⭐ | 标记 candidate (B+) |
| 收到 `msg_type=101` (PopupMsgBox) | `acl-popup` | 服务端用通用弹窗回复 | 标记 candidate (B) |
| 收到 `msg_type` 与发送一致（resp 通常 = req+1）| `echo-resp` | 标准 req/resp pair | **强 candidate** |
| 收到 `msg_type` ≠ 输入 | `translated` | 服务端 handler 改写了 msg_type | **强 candidate** ⭐⭐ |
| body 大小 > 100B | `payload-large` | 可能含真实数据 | **强 candidate** ⭐⭐⭐ |
| 连接被服务端断开 | `kill-conn` | 触发反 fuzz 防护 | **abort 整轮** |
| 连接被 RST | `tcp-rst` | 同上 | abort |

### 特别关注信号

**HIT 候选关键特征**（触发立即停下并人审）：
1. body 中含**长度像 7（hand_raw 大小）**或 **13（手牌大小）**或 **34（tile_id 全集）**的整段
2. body 头部 4-8 字节像 numid/userid（10 位数字范围）
3. zlib magic bytes (`78 9c` / `78 da`) — 大概率是 record/replay/dump
4. 长度字段说明 body > 256B — 远超普通 ack/error

---

## §4 加密 / Wire Format（沿用 PoC v5/v6）

### Frame layout (12B header + body)

```
+---------+---------+---------+---------+---------+
| FLAG    | LEN     | MSGTYPE | SUBTYPE | EXTRA   |
| u16 LE  | u16 LE  | u16 LE  | u16 LE  | u32 LE  |
| 0x4001  | len(body)        | =proc   | appid   |
+---------+---------+---------+---------+---------+
| body (LEN bytes, AES-CFB128 fresh-from-IV)      |
```

### Body 加密

- 每帧 **fresh CFB**（IV 重置，使用 session key），`SRSCrypto.reset_cfb()` + `encrypt_payload(body)`
- session key 来自 PlayerData 解密结果（PoC v5 的 H13 修对了)
- 响应 body 同样 CFB 加密 — 客户端 reset_cfb 后 decrypt
- **fuzz 时**：req body 加密；resp body 也尝试 decrypt；如果 decrypt 后是乱码但 raw 是结构化数据，可能服务端没加密（管理协议/admin 接口可能跳过加密）

### Body 矩阵（每个 msg_type 都试以下 4 种）

1. **空 body** (0 bytes) — 看服务端是否要求 askid+roomid
2. **4B 全零** `00 00 00 00` — 默认 i32 askid
3. **8B `<askid: i32, roomid: i32>`** — 标准 IM/Room 协议起手
4. **16B `<askid, roomid, offset, before>`** — 模仿 ReqRealtimeGameRecord 的 dump 风格

→ 单 (msg_type, sub_type) 实际 4 子帧，全 fuzz 量 = 4845 × 6 × 4 = **116,280 帧** ≈ **3.2 hr** @ 10 fps

**实战建议**：第 1 轮只跑空 body（快），命中后再做 body 变体扩展扫。

### sub_type 矩阵

```
SUB_TYPES = [
  100,   # IMProtocol (主战场，spectator/friend 协议在这；最可能藏 dump)
  84,    # RoomProtocol (room/table 类 admin)
  92,    # BagSysProtocol
  1006,  # MatchLinkProtocol
  1,     # AgBaseProtocol/GameProtocol (公共基础, 含 SRS error)
  0,     # SRSProtocol (登录路由)
]
```

可选第 2 轮加：`116, 113, 120, 30, 62, 140, 141, 147, 3` 共 9 个。

---

## §5 节流与隐蔽（Stealth）

### 速率限制

| 维度 | 上限 | 理由 |
|---|---|---|
| 单连接帧速率 | **≤ 10 帧/s** | 远低于真号 IM 100s 心跳 + 偶发 friend list 请求 |
| 单 IP 并发连接 | **1** | 真号正常用一条 IM 连接 |
| (msg_type, sub_type) 间 cooldown | 100 ms | 让响应有时间到 |
| 大段 fuzz 间隔（每 500 帧） | sleep 30s | 像玩家空闲 |
| 整轮 fuzz 间隔（multi-run） | ≥ 30 min | 避开 frontend per-account anomaly window |

### 行为伪装

- **保持心跳节奏**：fuzz 期间继续每 100s 发 IMProtocol.ReqKeepAlive(306) 和 BagSys.ReqKeepAlive(506) — 让 frontend 不会因长时间无心跳 kick
- **混入"正常"请求**：每 100 个 fuzz 帧后插一条 ReqOpenFriendList(408) 或 ReqGetInviteInfo(418) — 业务流量做掩护
- **avoid login storm**：单次握手后保持 long-lived session；不要 fuzz 完一段断连重连

### 多目标（lobby 5748 / game 5045）分离

- **lobby (47.96.101.155:5748)** — 主 fuzz 入口，sub_type ∈ {0, 1, 84, 92, 100} 全适用
- **game (47.96.0.227:5045)** — 仅 GameProtocol(processid=1) 路由有意义；XY_ID 闭集里 sub_type=1 的协议很少（只有 RespLeaveRoom 等几个）。**第 1 轮跳过 game 端**，只在 lobby 没结果再补
- 两路 fuzz **不并发**（避免账号双连被踢）

---

## §6 风险登记 (Risk Register)

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **服务端 IP ban** | 中 | 整 ECS 出口被禁，noconfig/VPN 全失效 | 用副号 + 副号 sessionid，**绝不**用主号 fuzz |
| **账号封停** | 中 | 副号被废 | 准备 3 个副号轮换；触发 acl-popup 频繁立即停 |
| **frontend 反 fuzz 触发** | 低 | conn 被 RST，重连 cooldown 长 | 检测到连续 RST/kill-conn 立即 abort |
| **hit 但回包带 honeypot** | 低 | 服务端故意诱导我们继续 → 反向追踪 | hit 后切副号验证，不在同号上深挖 |
| **fuzz 帧泄漏到主号** | 低 | 主号被关联标记 | 完全独立 ECS 出口（建议另起 VPS 不要复用 8.136.37.136）|
| **响应解密失败误判 silent** | 中 | 漏掉真 hit | 解密失败时 dump raw bytes，事后回看 |
| **业务流量被 fuzz 遮蔽** | 低 | 副号在线但行为反常 | 限制单连帧速率 ≤10/s |

### Abort 信号（脚本必须实现）

- 连续 5 次 RST/kill-conn → abort
- 收到 PopupMsgBox 5 次 → abort（服务端在投放阻断 popup）
- 单 sub_type 连续 200 帧全 silent → 切下一 sub_type，不浪费时间
- 用户键盘 Ctrl+C → 优雅断开（先发 LeaveIM/LeaveBox 清理）

---

## §7 命中后处理流程（Post-Hit Workflow）

1. **classifier 标 candidate** → 写 `fuzz_log.jsonl` 单条 with full req_hex + resp_hex + score
2. **本地人审**（不 auto-promote）
3. 判断是否真"破 H16"：
   - hit response body 含 hand_raw 13B 模式（`stable/protocol.py` 中的 deal 帧 body[0:13] 风格）→ ⭐⭐⭐ 直接破 H16
   - hit 是 admin 风格（`Req...Hand` / `Req...DumpRoom` 命名嫌疑） → 升级到下一阶段：副号身份发该 (msg_type, sub_type) + 主号 roomid，看 response 是否含**主号** hand_raw
   - hit 是 record/replay 类（zlib 大段） → 解 zlib 看是否为 view-filter-bypass 的完整局
4. **不在 fuzz 期间扩展攻击**：单条 hit 验证完毕，立即停 fuzz，整理报告 + 升级到 implement 阶段

---

## §8 总执行时长估算（合理保守）

| 阶段 | 帧数 | @10fps 时长 | 备注 |
|---|---|---|---|
| 第 1 轮（核心扫，空 body × 6 sub_types） | 29,070 | 48 min | 默认起手 |
| 第 2 轮（命中区域 body 变体 × 4） | ~600 | 1 min | 仅命中 sub_type 重扫 |
| 第 3 轮（拓展 sub_type ×9） | 43,605 | 73 min | 第 1 轮无果时启 |
| 第 4 轮（game 端 sub_type=1） | 4,845 | 8 min | 兜底 |

**全套预算**：~2.5 hr（极端保守，含 30s 段间停顿）。

---

## §9 完成条件

✅ A 级 + B 级核心扫完成（覆盖 [1, 5000] × 6 sub_types）
✅ 输出 `fuzz_log.jsonl`（每帧 1 行 JSON record）
✅ 自动 classifier 给出 candidate 列表
✅ 至少 0 false-positive 通过人审 + 命中实证（"破 H16" 或确认无）
✅ 全程不触发 abort（IP ban / 账号封停 / RST 风暴）
