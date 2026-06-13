# noconfig-permanent-read — SRS session续期 + 永久云端读牌

## Goal

用户只需要**连一次热点**（提取凭证），之后不管手机在什么网络，云端都能持续读到手牌。当前"无配置模式"（:8002 relay + SRS spectator）依赖一个有生命周期的 `srs_sessionid`，过期后就返回 `flag=72` 断连。本任务研究如何让云端在不需要用户介入的情况下自动续期 session，实现"一次热点、永久在线"。

## 本轮已 banked 的技术成果（连一次热点能抓到什么）

| 凭证 | 来源帧 | 生命周期 | 内容 |
|------|--------|---------|------|
| `handshake_blob` | `0x0001 sub=0x047b` C→S | 长期（设备指纹+账号，不随 session 变化） | 大厅登录明文（设备信息+identify+osver+pkg+channel+头像URL）用会话密钥加密后的密文；明文已稳定可重建 |
| `auth_token_12b` | `0x0006 sub=0x0093` S→C payload[4:16] | 中长期（账号级，不随连接变化） | 12字节认证令牌，服务端给客户端的账号凭证 |
| `srs_sessionid` | SRS PlayerData(msg=6) 成功后服务器返回的 16B token | 短期（session 级，连接断开/过期返 flag=72） | 旁观连接的身份令牌，发给 PlayerConnect.pwd |

**加密链（全破）：**
- SRS层：AES-256-CFB128，默认 key `f362120513e389ff…`，固定 IV，HandshakeRsp 下发 session_key
- 大厅登录帧（0x0001 sub=0x047b）：**同一把 session_key** 加密（Frida 实测），明文 = 稳定设备字段（无 server nonce）
- PlayerConnect（msg=5）：session_key 加密，pwd=16B srs_sessionid，flag=0 实测通过

**旁观协议关键约束（已知死路）：**
- 旁观模式（ReqRealtimeGameRecord, msgid=3000, sub_type=100）：**只能看到牌背，无法获取隐藏手牌**（实机用户确认）
- 重连到同桌：服务器接管语义，踢掉旧连接（手机掉线）
- 牌局数据帧（0x2bc0）在 7777 端口上**明文传输**，只流向"在桌的那条会话"

## 核心研究问题

**Q：当 `srs_sessionid` 过期（flag=72）时，云端能否用 `handshake_blob`/`auth_token_12b` 自动获取新 session，无需用户重新连热点？**

### 待验证的三条假设（按实现难度排序）

**假设 B（保活）：srs_sessionid 绑定到 TCP 连接，保持连接不断则 session 不过期**
- 测法：SRS 握手成功后，定期发 heartbeat（msg_type=0x0003），观察连接存活时长
- 成本：最低，只需改 client.py 加心跳逻辑
- 如果成立：永久维持一条长连接 = 永久有效 session，零续期复杂度

**假设 A（auth_token_12b 直接认证）：PlayerConnect 的 pwd 用 auth_token_12b（12B+4B零填充），服务器接受并返回 flag=0**
- 测法：建新连接，PlayerConnect.pwd = auth_token_12b[:12] + b"\x00"*4
- 成本：低，只改 SRSClient 构造参数
- 如果成立：任何时候都能用 12B token 重新登录，无需 srs_sessionid

**假设 C（重放大厅登录）：完整重放大厅登录帧序列（0x0001 明文+0x0006 响应），服务器给新 srs_sessionid**
- 测法：SRS 握手成功后，发大厅登录明文（用新 session_key 重新加密），观察服务器响应
- 成本：中，需实现大厅登录帧构建（明文已由 Frida 抓到，字段稳定）
- 如果成立：能完整模拟登录流程，获取新 session，可无限续期

## 待澄清的关键设计决策

### 决策 D1：目标手牌类型？（影响整个方案方向）

- **选项 D1-A（旁观视角）**：只要公开信息（打出的牌、弃牌、鸣牌），手机正常玩，云端旁观
  - 可行路径：解决 srs_sessionid 续期即可（假设 A/B/C 任意一条）
  - 约束：看不到自己的手牌，只能看到公开信息

- **选项 D1-B（完整手牌，包括隐藏牌）**：云端当玩家本人，拿到隐藏手牌
  - 可行路径：只有两条 → VPN 被动嗅探（已上线）或云端当玩家（踢手机）
  - 约束：如走云端当玩家，手机无法同时打牌

→ **当前 `noconfig` 模式是旁观视角，无法看隐藏手牌。** 如果目标是看隐藏手牌，则本任务的研究方向需要转向。

## Requirements（暂定，待 D1 澄清）

*假设目标是「旁观视角 + session 自动续期」：*

* 热点模式连一次后，提取 handshake_blob + auth_token_12b 并持久化到 relay config
* 云端 srs_spectator 建立 SRS 连接，当 flag=72 时自动触发续期流程
* 续期成功后重新发旁观请求（ReqRealtimeGameRecord），无需用户介入
* 续期机制在 ECS 云端全自动运行（systemd 守护，断线重连）

## Acceptance Criteria（暂定）

* [ ] 手机完全离线后，云端仍能维持旁观连接 ≥ 24h
* [ ] srs_sessionid 过期（flag=72）后自动续期，续期耗时 < 30s
* [ ] 续期后 `/state` 重新返回 `watching=true`
* [ ] 无需用户任何操作（全自动）

## Definition of Done

* 续期逻辑实现并在 ECS 持续运行 > 24h 验证
* relay `:8002` `/state` 在手机离线时仍正常返回旁观状态

## Technical Notes

**关键文件：**
- `remote/srs_spectator/client.py` — SRSClient，PlayerConnect 在 `_handle_frame` 里构建
- `remote/srs_spectator/player_connect.py` — PlayerConnect 格式，`usertype=7` 时 pwd=16B session
- `remote/srs_spectator/handshake.py` — build_req_key, parse_player_data (flag, sessionid)
- `remote/srs_spectator/main.py` — WatchState, SRS_SESSIONID 环境变量
- `remote/extractor/token_extractor.py` — 从 0x0001/0x0006 帧提取 handshake_blob/auth_token_12b

**游戏服务器：** `47.96.0.227:7777`（TCP，SRS 协议）

**诊断脚本（已有）：**
- `scripts/diag_srs_live.py` — 建 SRS 连接并实测 PlayerConnect
- `scripts/diag_srs_watch.py` — 实测旁观请求
- `scripts/capture_srs_sessionid.py` — 从热点流量提取 srs_sessionid

**研究参考（已归档）：**
- `.trellis/tasks/archive/06-11-srs-client-finish/research/srs-fully-solved.md` — AES 链全破记录
- `.trellis/tasks/archive/06-11-srs-client-finish/research/srs-spectator-protocol.md` — 大厅登录明文（Frida 抓）+ processid 映射
- `.trellis/tasks/archive/06-11-srs-client-finish/research/final-architecture-plan.md` — 三条路排除逻辑

## Open Questions

1. **D1：目标手牌类型是旁观公开视角还是完整手牌？** ← 当前 blocker

## Out of Scope（明确排除）

* 手机端 Frida siphon（另一条路，不在本任务）
* VPN 模式改进（已有独立方案）
* 视觉模式（截图识别）
