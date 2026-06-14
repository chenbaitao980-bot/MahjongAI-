# 永久手牌读取：sessionid 长期有效性 + 双连接可行性深度调研

## Goal

基于用户实测发现 `srs_sessionid` 可能长期有效（超过 4 小时仍 flag=0），深入调研三种可行路径，验证能否实现"手机正常打牌时，云端同时持续读取手牌"的终极目标。

---

## 三模式代码隔离规范

> **黄金规则**：热点模式、VPN模式、无配置模式三者代码独立，互不干扰。

| 规则 | 说明 |
|------|------|
| **目录隔离** | 每个模式有独立目录：`remote/hotspot/`、`remote/vpn/`、`remote/noconfig/` |
| **不共享状态** | 各模式的 `_cfg`、`_state_store` 是模块级私有，无跨模式状态污染 |
| **不共享进程** | `relay/main.py --all` 使用 `multiprocessing.Process`，进程级隔离 |
| **新增文件限制** | 无配置模式的测试/实现文件必须放在 `remote/noconfig/` 下 |
| **修改范围限制** | 只修改 `remote/noconfig/` 和 `remote/srs_spectator/`（如需修改核心协议） |
| **禁止修改** | `remote/hotspot/`、`remote/vpn/`、`remote/relay/core.py`（除非修复 bug） |

**本任务遵守的隔离**：
- ✅ 测试脚本 `test_dual_session.py` 放在 `remote/noconfig/` 下
- ✅ 只导入 `remote/srs_spectator/client.py`（已有 SRS 协议实现）
- ❌ 不修改 `remote/hotspot/`、`remote/vpn/`、`remote/relay/core.py`

---

## Background

### 已知事实（已 banked）

| 事实 | 来源 | 细节 |
|------|------|------|
| `srs_sessionid` 4h+ 仍有效 | `remote-access.md:322` | 断线后重连，flag=0，3轮测试通过 |
| 服务端 idle timeout = 120s | 实测 | 不发数据则服务端主动断连 |
| 单连接限制 | 实测 | 同一 `srs_sessionid` 只允许一条 TCP 连接存活；新连接踢旧连接 |
| 自动重连已实现 | `remote-access.md:343` | on_disconnect → 2s 延迟 → 重新 SRS 握手 + PlayerConnect |
| `handshake_blob` + `auth_token_12b` 长期有效 | `token_extractor.py` | 账号绑定，不随 session 变化 |
| `flag=72` = INVALID_SESSIONID | `srs-fully-solved.md:91` | SRSProtocol.lua:199，令牌错误（非过期，而是被占用/不认识） |

### 用户新发现（待验证）

> "实测有效，sessionid 貌似不会过期"

用户声称 `srs_sessionid` 长期有效（超过文档记录的 4h），需要进一步验证：
- 超过 4h 后是否仍然 flag=0？
- 超过 24h 后是否仍然 flag=0？
- 手机重启/重新登录后，旧 sessionid 是否仍然有效？

---

## 核心研究问题

**Q1: `srs_sessionid` 的真实有效期是多少？**
**Q2: 如果单连接限制无法绕过，高频重连抢帧是否可行？**
**Q3: 抢帧方案对手机的影响有多大？**

---

## 调研路径（重点 + 备选）

### 重点方向 C：快速重连抢帧（时间窗口利用）

**状态**：✅ 测试脚本已就绪（`remote/noconfig/test_dual_session.py --mode rapid-reconnect`）

**核心假设**：服务端"踢连接"存在时间窗口（2-3秒），通过**高频重连**可以抢到几帧手牌数据。

**测试脚本**：
- `remote/noconfig/test_dual_session.py` — 方向 C 测试脚本
- 支持参数：
  - `--mode rapid-reconnect`：快速重连模式
  - `--reconnect-interval`：重连间隔（默认 2.0 秒）
  - `--duration`：总测试时长（默认 60 秒）

**用法**：
```bash
# 基础测试：60秒，每2秒重连一次
python remote/noconfig/test_dual_session.py --mode rapid-reconnect --sessionid <hex32>

# 激进测试：120秒，每1秒重连一次
python remote/noconfig/test_dual_session.py --mode rapid-reconnect \
    --sessionid <hex32> --duration 120 --reconnect-interval 1.0

# 保守测试：60秒，每3秒重连一次
python remote/noconfig/test_dual_session.py --mode rapid-reconnect \
    --sessionid <hex32> --duration 60 --reconnect-interval 3.0
```

**测试方法**：
1. 手机正常打牌，保持在线
2. 云端用同一 `srs_sessionid` 快速重连：
   - SRS 握手 → PlayerConnect → 收到几帧 → 被踢
   - 被踢后 X 秒内再次重连（X 可调：1.0/2.0/3.0）
   - 循环
3. 观察：
   - 每次能抢到多少帧？
   - 手牌数据（0x2bc0）是否完整？
   - 手机是否明显受影响（卡顿、断线提示）？
   - 服务端是否检测异常频率并封禁？

**预期结果（按优先级）**：
- ✅ 最佳：每次抢到 1-2 帧手牌，足够更新状态；手机无明显感知
- ⚠️ 中等：能抢到帧但手牌不完整；手机偶尔卡顿
- ❌ 最差：手机严重受影响；服务端封禁 IP

**关键指标**：
| 指标 | 目标 | 说明 |
|------|------|------|
| 抢到帧率 | >50% | 每次重连至少抢到1帧 |
| 平均每连接帧数 | ≥1 | 足够更新手牌状态 |
| 手机影响 | 无感知 | 无卡顿、无断线提示 |
| 服务端响应 | 不封禁 | 无 IP 限制、无账号封禁 |
| 重连间隔 | 2-3s | 平衡抢帧率和手机影响 |

**所需资源**：
- 一个有效的 `srs_sessionid`
- 手机正常打牌
- `remote/noconfig/test_dual_session.py`（已有）

---

### 备选方向 A：不同 sessionid 同时在线（待定）

**状态**：⏸️ 待定（需两台手机或历史 sessionid，当前资源不足）

**历史记录**：
- `game-protocol.md:186` 声称"已实测：游戏服务器允许同一账号同时双端在线"
- 但进一步调查发现，这是基于**已被证伪的 `game_client.py` 方案**（跳过 SRS 加密认证层）
- **没有"不同 sessionid 同时在线"的实测记录**

**测试脚本**：`remote/noconfig/test_dual_session.py` 已支持 `--mode different`

**触发条件**：当获取到第二个 sessionid 时，可立即启动测试。

---

### 备选方向 B：auth_token_12b 直接登录获取新 sessionid（待定）

**状态**：⏸️ 待定（需修改 PlayerConnect 构建逻辑，当前未验证）

**假设**：`auth_token_12b` 是账号级凭证，可能可以直接用于登录获取新的 `srs_sessionid`。

**测试方法**：
1. 使用已提取的 `handshake_blob` + `auth_token_12b`
2. 构建 PlayerConnect，pwd = `auth_token_12b`（12B + 4B 零填充 = 16B）
3. 发送 PlayerConnect，观察 flag

**触发条件**：当方向 C 不可行时，启动方向 B 测试。

---

### 备选方向 D：sessionid 真实有效期极限测试

**状态**：⏸️ 待定（需长时间运行，当前未安排）

**目标**：验证用户声称"sessionid 不会过期"的真实性。

**测试方法**：
1. 提取一个 `srs_sessionid`，记录时间戳
2. 每隔 4h 测试一次重连 flag
3. 持续测试直到 flag≠0
4. 记录真实有效期

**触发条件**：当方向 C 成功且需要评估长期稳定性时，启动方向 D 测试。

## Acceptance Criteria

| # | 验收标准 | 优先级 |
|---|---------|--------|
| 1 | 方向 C 完成实测，记录抢帧成功率、平均每连接帧数、手机影响 | P0 |
| 2 | 方向 C 找到最优重连间隔（1.0s/2.0s/3.0s 对比） | P0 |
| 3 | 方向 C 确认服务端是否封禁高频重连 | P0 |
| 4 | 方向 A/B/D 触发条件满足时启动测试 | P1 |
| 5 | 所有测试脚本/修改后的代码提交到仓库 | P2 |

---

## Out of Scope

- 手机端 Frida siphon（另一条路，不在本任务）
- VPN 模式改进（已有独立方案）
- 视觉模式（截图识别）
- 大厅登录帧重放（假设 C，已排除）

---

## Technical Notes

### 关键文件

| 文件 | 用途 |
|------|------|
| `remote/srs_spectator/client.py` | SRSClient，PlayerConnect 构建 |
| `remote/srs_spectator/player_connect.py` | PlayerConnect 格式，pwd 字段 |
| `remote/srs_spectator/handshake.py` | build_req_key, parse_player_data |
| `scripts/diag_srs_live.py` | 建 SRS 连接并实测 PlayerConnect |
| `scripts/diag_srs_watch.py` | 实测旁观请求 |
| `remote/extractor/token_extractor.py` | 从 0x0001/0x0006 帧提取凭证 |

### 游戏服务器

- `47.96.0.227:7777`（TCP，SRS 协议）

### 测试账号

- `newpt1084306678` / areaid=7109 / channelid=70900

---

## Open Questions

1. **用户实测的"sessionid 不会过期"具体是多长时间？** 是 8h、24h、还是更长？
2. **是否有第二台手机可以提取不同的 sessionid？**（方向 A 必需）
3. **auth_token_12b 是否曾用于非热点场景登录？**（方向 B 参考）
