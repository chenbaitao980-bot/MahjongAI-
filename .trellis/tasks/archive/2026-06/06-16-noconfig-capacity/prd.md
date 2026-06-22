# noconfig 并发容量评估与优化（按需加载改造）

## Goal
**核心转变**：从"管理员打开 admin 页面就持续轮询所有用户"改为"按需加载"——点到哪个用户才看哪个用户的手牌，未被浏览的用户不消耗服务器资源。
- 评估并实施 noconfig 管理页面 (`http://8.136.37.136:8002/admin`) 的并发优化
- 离线用户超过 1 小时自动从列表消失（隐藏/清理）
- 被点开查看的用户必须数据准确实时
- 服务器（2 vCPU / 1.6GB RAM）零硬件升级前提下最大化并发

## What I already know

### 业务需求（用户最新）
1. **按需加载**：管理员/玩家在 `/admin` 列表里点击某用户 → 才拉取/订阅该用户的数据
2. **数据准确实时**：被点开的用户看到的就是游戏内最新手牌（不是缓存过的历史）
3. **1 小时下线清理**：用户离线 ≥ 1 小时 → 从 `/admin` 列表中消失
4. **在线可见性大前提（2026-06-17 明确）**：任何一个用户只要正在玩，`/admin` 在线状态必须展示出来
5. **中途进入大前提（2026-06-17 明确）**：管理员无论何时点进某个正在玩的用户，都必须能看到和用户手机上一样的实时手牌

### 关键资源限制
- 服务器 2 vCPU + 1.6GB RAM（无 swap）
- 当前 noconfig 进程 RSS ~44MB
- 每个 SRS spectator 子进程预计 ~40-50MB
- 单个游戏 TCP 长连接消耗：1 端口 + 1 文件描述符 + AES 解密 CPU

### 现状架构
- FastAPI + uvicorn 单 worker（无 workers 参数）
- `/admin` 页面每 **5 秒**轮询 `/api/users`
- iframe 手牌页每 **1.5 秒**轮询 `/state`
- `/api/users` 返回所有用户字典（O(N)）
- 用户数据纯内存（`user_store` 单例 + `RLock`）
- spectator 子进程是**默认** fallback 行为（extractor 离线即启）

### 关键发现
- 当前 0 个 spectator 进程在运行（因为 0 用户在线）
- 当前没有任何用户在做"按需加载"——所有用户的 spectator 是被动启动的
- 改造成本相对低：核心是**前端行为 + 后端 spectator 启停策略**的重构

## Assumptions (temporary)

1. "准确实时"= 看到 X 此刻在游戏里的手牌（用户已确认）— 实现路径：选中 X 时，若 extractor 在推送用推送数据，否则启动 spectator 实时拉取
2. "1 小时无活动"指 last_push_time 或 spectator 关闭距今 > 1h
3. 管理员/用户并发浏览数 ≪ 总注册用户数（典型 1-5 个管理员 + 偶尔单用户查看）

## Decision (ADR-lite)

**Context**: 业务对"准确实时"的定义
**Decision**: 点开用户 X 时建立到游戏服务器的实时连接，关闭查看时断开
**Consequences**:
- 后端需要 spectator 启停的显式 API（不再完全靠 fallback 自动启）
- 需要前端的心跳/卸载检测机制来驱动 spectator 启停
- spectator 数量上限 = 同时被查看的用户数（资源可控）

## Decisions（最终确认 2026-06-17）

1. **方法论：先压测 baseline → 改 → 再压测对比，没改善就回滚**
2. **方案 D：三个闲置 relay 全部停掉**（hotspot:8000 / vpn:8001 / cloud:8003）— 释放 ~137MB
3. **方案 A：补 /presence 端点 + UI 显示"离线 Xh/Xd"**
4. **离线用户永久保留**（不删，不限期），但要确保**离线用户零带宽**：
   - 离线用户不发心跳、不触发 spectator
   - `/api/users` 列表只回 `{user_id, name, last_seen_ts, is_online}`，不带 snapshot
   - 离线用户不被 admin 自动轮询（只有点开才拉数据）
5. **方案 B/C/F 暂缓**：等真实压测数据证明 D+A 不够再考虑

## 压测方案（已锁定 2026-06-17）

### 部署位置
**ECS 上自压自测**（127.0.0.1:7777），消除网络瓶颈，结果里要减去压测客户端自己的 RSS

### 压测梯度（粗粒度，3 个数据点）
- N=10：日常负载基线
- N=50：推荐目标上限
- N=100：极限验证

### 测量指标（每档跑 3 分钟稳态）
| 指标 | 测量方法 |
|------|---------|
| ECS CPU% | `top -b -n 1` 采样 noconfig + tcp_proxy 进程 |
| 各进程 RSS | `cat /proc/$pid/status` 采样 |
| /api/users 响应 P95 | `curl -w` 统计 100 次请求 |
| /state 响应 P95 | 100 次请求统计 |
| **手牌正确性** | 强验证：每客户端 fingerprint 嵌入 0x2bc0 payload，ECS 解码 push 后从 /state 读回比对 |

### 三轮对比
| 轮次 | 状态 | 期待结果 |
|------|------|---------|
| Round 0 (baseline) | 当前架构 | 记录基础数据 |
| Round 1 (D) | 关掉 3 个闲置 relay | RSS 总和 -137MB，N=100 时余量更大 |
| Round 2 (D+A) | + /presence 端点 | 功能补齐，对性能应无负面影响 |

### 回滚条件
**Round 1/2 任一指标比 Round 0 显著恶化（CPU+10%、P95+50%、出现错配）→ 立即回滚**

## Requirements (evolving)

* 闲置 relay 停止后，noconfig 主进程内存预算 ~870MB
* tcp_proxy 主路径不动，保证现有正确性
* 补 `/presence` 端点：tcp_proxy 在游戏 PlayerData 解出后会 POST 到 relay，relay 接收后 upsert 到 user_store
* `/api/users` 默认按 `last_seen_ts` 倒序，只返回元数据（含离线时长），不带 snapshot
* 离线用户元数据持久化：进程重启后凭证不丢（写到 disk 或保持内存均可，决策见 ADR）
* 数据延迟 < 3s（轮询，1.5s 间隔）

## Acceptance Criteria

* [ ] **Round 0 baseline 数据采集完成**（N=10/50/100 三档 CPU/RSS/P95/正确率）
* [ ] **Round 1 (停 relay) 数据采集完成**，与 baseline 对比文档化
* [ ] **Round 2 (+ /presence) 数据采集完成**，功能验证通过
* [ ] D+A 部署后，相同负载下 RSS 显著低于 baseline
* [ ] `/presence` 端点工作：手机进游戏 5s 内出现在 /admin 列表，标记在线
* [ ] 离线用户在列表中显示离线时长（"离线 3h" / "离线 2d"），不消耗主动带宽
* [ ] 50 模拟用户并发场景下服务器稳定运行 3 分钟无 OOM、无错配
* [ ] **如果 Round 2 vs Round 0 无显著改善（RSS 降幅 < 100MB 且 CPU 无改善）**：回滚改动

## Definition of Done

* 改造代码部署到 ECS 并通过 8.136.37.136:8002/admin 验证
* 内存基线对比（before/after）
* 关键路径单测覆盖

## Out of Scope (explicit)

* 数据库持久化（保持内存）
* 完整 WebSocket 改造（先用轮询，必要时再升级）
* 多 ECS 横向扩展

## Capacity Assessment (实测数据 2026-06-16)

### 服务器现状 (8.136.37.136)

| 指标 | 值 |
|------|-----|
| CPU | 2 vCPU (Xeon Platinum), load avg 0.09 (几乎空闲) |
| RAM | 1608 MB 总, 477 MB 已用, 944 MB 可用, 无 swap |
| FD 限制 | 进程 soft 1024 / system 65535 |
| TCP ephemeral | 32768-60999 (28231 端口) |
| Python 版本 | 3.10.12 |
| uvicorn workers | 1 (单进程) |

### 现有进程内存分布

| 进程 | RSS | 说明 |
|------|-----|------|
| relay hotspot (8000) | 44 MB | 常驻 |
| relay vpn (8001) | 44 MB | 常驻 |
| noconfig main (8002) | 44 MB | 主服务 |
| relay cloud (8003) | 48 MB | 常驻 |
| tcp_proxy (hijack) | 37 MB | MITM 代理 |
| setup_mitm | 30 MB | DNS 劫持 |
| **合计** | **~314 MB** | |

当前 0 个 spectator 子进程在运行, 3 个注册用户(均离线)。

### 容量瓶颈分析

**内存是唯一硬瓶颈** (CPU/网络/FD 远未达上限)

```
总内存:          1608 MB
- OS/内核:       ~200 MB
- 现有 Python:   ~314 MB
- 安全余量:      ~150 MB
= 可用于 spectator: ~944 MB
```

每个 spectator 子进程 = 独立 Python 解释器 + FastAPI + SRSClient + AES
实测估算: **40-50 MB / 个**

| 场景 | 同时在线上限 | 瓶颈 |
|------|-------------|------|
| 全靠 spectator (典型无配置) | **17-20 人** | 内存 (20×45=900MB) |
| 全靠 extractor 推送 | **200+ 人** | 仅内存存 snapshot(~1KB/人) |
| 混合 (5 spectator + N extractor) | **5 spect + 200 extractor** | 内存 |

**结论：当前架构下，无配置模式的同时在线上限 ≈ 17-20 人**

### 复核数据与当前实现限制 (2026-06-17)

服务器实时复核：

| 指标 | 值 |
|------|-----|
| 时间 | 2026-06-17 08:02 CST |
| CPU/load | 2 vCPU, load avg 0.21 / 0.16 / 0.10 |
| RAM | 1608 MB 总, 476 MB 已用, 947 MB 可用, 无 swap |
| noconfig 主进程 | pid 125328, RSS 41864 KB, fd=7 |
| 当前用户 | 3 个注册用户, 0 个在线 |
| 当前 spectator | 0 个用户 spectator 进程 |
| 后台服务 | hotspot/vpn/noconfig/cloud relay + tcp_proxy + setup_mitm 常驻 |

当前代码还有一个比内存更先触发的实现限制：

* `remote/noconfig/app.py` 为每个用户启动 spectator 子进程，但每个子进程都设置 `BIND_PORT=8003`。
* `_notify_spectator()` 又固定请求 `http://localhost:8003/watch`。
* `remote/srs_spectator/main.py` 是单 `WatchState`，一次只保存一个 `active_roomid/active_gameid`。

因此，在不改代码的前提下，当前实现不能可靠支撑多个用户同时各自独立 spectator。理论内存预算是 17-20 个 spectator，但当前可用的多用户 spectator 上限应按 **1 个可靠活跃 spectator** 看待；第二个用户会遇到端口冲突、通知串线或覆盖 watch state 的风险。

对用户最新大前提的影响：

* 如果“在线状态”依赖被动推送/劫持流量，在线列表可以承载很多人，因为每个用户只是一份内存 snapshot。
* 如果“在线状态”和“实时手牌”都依赖 spectator 主动连游戏服，则必须为每个正在玩的用户保持一个轻量 watcher；当前子进程+固定端口模型不满足。
* 最合理目标是：在线状态由轻量 presence/snapshot 推送保证；点开用户时才启动或绑定实时手牌通道；未点开的用户不跑重型 spectator。

### 优化方案 (不升级硬件)

| 方案 | 预期容量提升 | 实现难度 | 说明 |
|------|-------------|---------|------|
| **A. 进程内 spectator** | 3-5× (50-80人) | 中 | 用线程替代子进程, 省 ~35MB/个 Python 解释器开销 |
| **B. 按需启停 (PRD 已规划)** | 有效容量 2-3× | 低 | 只启动被查看用户的 spectator, 典型 1-5 个同时被看 |
| **C. 清理离线用户** | 防止内存泄漏 | 低 | 1h 离线从列表隐藏, 减少列表开销 |
| **D. 关闭其他 relay** | +130MB (~3 spectator) | 低 | 如不需要 hotspot/vpn 模式, 停掉释放内存 |
| **E. WebSocket 推送** | 降低 HTTP 开销 | 中 | 替代 1.5s 轮询, 减少无谓请求 |
| **F. 增加 swap** | 扩容但降速 | 低 | `fallocate -l 2G /swapfile` 可紧急扩展, 但性能降级 |

**最优组合: A+B+C = 预计可支撑 50+ 同时在线**

## Technical Notes

* 服务器: 8.136.37.136 (root/Ysydxhyz111)
* 服务进程: `remote/noconfig/main.py --port 8002`
* 相关文件: `app.py`, `user_store.py`, `main.py`, `srs_spectator/main.py`, `srs_spectator/client.py`
* 静态文件: `remote/relay/static/index.html`
* 关键代码位置:
  - `app.py:451`  `/admin` 页面
  - `app.py:403`  `/api/users` 列表 API
  - `app.py:284`  `/state` 单用户快照 API
  - `app.py:138`  `_ensure_spectator_running` 自动 spectator 启停
  - `user_store.py:51`  `is_online()` 判定
  - `user_store.py:160`  `search_users`
