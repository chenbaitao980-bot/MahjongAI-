# Meta-System Testing Thinking Guide

> **Purpose**: Stop and think about testing the **监督/保护/恢复** mechanism itself, not just the unit it watches.

---

## The Problem

**"装了 watchdog 之后业务挂了没人救"** — 是 systemd 装上、Restart=always 设了、watchdog 进程跑着的状态下，依然救不回来的真因。11 天内连发 5 次 4G/MITM 回归，最后一次就是监督者自身有 bug。

详见 spec 铁律 6/7：[mitm-connection-stability-guide.md](mitm-connection-stability-guide.md)。

---

## 监督代码 vs 业务代码：失败模式不同

| 维度 | 业务代码 | 监督/保护代码 |
|---|---|---|
| 失败时表现 | 返回 500/404/异常 → 易观察 | 表面完全正常(不告警/不报错) → 极隐蔽 |
| 验证方式 | 单测 + 集成测试 | 必须**故障注入**(造真故障) |
| 测试在什么环境 | dev/staging | **不能在生产** — 自己恢复副作用大 |
| 出 bug 谁负责 | 业务 bug | 监督代码假装在工作 = 重大事故 |
| 设计反模式 | "功能跑通就行" | "装上就行" — 没人测救不救得了 |

---

## Before Adding a 监督/保护/恢复 Mechanism

### Step 1: 列出"被监督者"所有可坏方式

| 故障类型 | 检测方法 | 现有监督者能救吗？ |
|---|---|---|
| 进程崩溃(exit) | `systemctl is-active` | ✓ systemd Restart=always |
| 进程死锁但还活着 | 看 CPU/线程数 | **✗ 装之前必须加 watchdog** |
| handler thread 全死主线程活 | curl /healthz 超时 | **✗ 装之前必须加 watchdog 探测** |
| 端口不再监听 | `ss -tln` | ✓ systemd Restart=always(端口占着不会起不来) |
| 业务逻辑 500 | 看 HTTP 状态码 | 部分(看是否覆盖) |
| 网络断(进程空转) | 看流量/看外部探测 | ✗ 装之前必须加外部 watchdog |

**任何标 ✗ 的，必须有专门的监督者 + 故障注入测试**。

### Step 2: 写故障注入测试 (Failure Injection Test)

不能放生产跑。要本地化：

| 造故障手段 | 命令 | 验证目标 |
|---|---|---|
| 进程崩溃 | `kill -9 $pid` | systemd Restart=always 拉起 |
| 主线程活 handler 死 | `kill -STOP $pid` | watchdog /healthz 探测超时 → 累计到 3 → restart |
| 端口不监听 | `iptables -A INPUT -p tcp --dport 443 -j DROP` | 健康检查 timeout → restart |
| 业务返回 500 | mock 业务逻辑抛异常 | 错误率告警 → 切流量 |
| 网络断 | `tc qdisc add dev eth0 root netem loss 100%` | 上游断流告警 |

**关键测试场景**:`进程活但不响应`(kill -STOP 或 SIGSTOP 主线程)—— 这是监督者**存在的唯一理由**,测试必含。

### Step 3: PRD 的 Acceptance Criteria 必须区分"安装确认"和"功能确认"

| 层级 | 示例 | 是否真能验证监督者工作 |
|---|---|---|
| ❌ 安装确认 | "watchdog 文件存在 / 部署到 ECS / Restart=always 配好 / 进程 active" | **不能**——只是装上了 |
| ✓ 功能确认 | "故障注入测试:kill -STOP 主线程 → 90s 内 watchdog counter 累加到 3 → systemctl restart 执行 → 服务恢复" | **能** |

**功能确认 = 故障注入测试通过 = 监督者真在工作**。这一条没勾 = 监督者等于没装。

### Step 4: counter 类自愈逻辑检查清单

任何 counter 累加机制(熔断器/重试退避/健康检查 counter),都过这清单：

| 检查项 | 通过? |
|---|---|
| reset 路径独立于 trigger 路径？(分开两个 if,不是同一个) | ✓ |
| reset 条件**严于** trigger 条件(要求"两次 trigger 都消失"或"业务真恢复")? | ✓ |
| reset 不依赖"看起来没坏"(如 systemd is-active 这种"主线程活=健康"的弱信号)? | ✓ |
| counter 文件写失败会无声吃掉? | **✗ 必须 set -e 或显式错** |
| 多次故障同时发生(partial failure)counter 行为? | 单数累加?同步累加?有测试吗? |

如果任何一个 ✗,这个监督者大概率会在你最需要它的时候掉链子。

---

## Anti-Patterns (Hard Avoid)

1. **"装上就行"** — 把 watchdog/circuit-breaker/retry 当作"心理安慰",没故障注入测试 = 装样子
2. **"systemd Restart=always 已经够"** — 它只管进程崩溃,**不管进程死锁**。两类故障并不可互相替代
3. **"is-active=健康"** — 对"主线程活(handler 死)"的进程**永远不成立**,这个假设等于"我监督我自己"
4. **"反正挂了用户会报"** — 用户报 = 你的监督者**没救**;救回来 = 监督者工作正常
5. **测试放生产** — 自己恢复的副作用大;在 staging 跑;本地化用 `nc -l` 假端口 / SIGSTOP 模拟
6. **daemon thread 跑关键服务 + 主线程空等** — `threading.Thread(target=serve_forever, daemon=True).start()` 后 `Event().wait()`。serve_forever 异常退出 = 线程静默死亡 = 主线程继续空等 = systemd 认为进程 alive = **监督者形同虚设**。关键服务必须跑在主线程，或至少能被主线程感知死亡。

---

## Self-Check Before Merging Any "Self-Protection" Code

```
□ 这段代码是监督/保护/恢复类吗?
  → 如果是,走以下清单:
    □ 被监督者有哪几类故障?列出来
    □ 每类故障的检测方法是什么?
    □ 每类故障的恢复动作是什么?
    □ 每类故障有故障注入测试吗?
    □ PRD Acceptance Criteria 有"功能确认"而非只是"安装确认"吗?
    □ counter 类逻辑(如有)过完 Step 4 清单了吗?
    □ 新增被监督服务时,WATCH_SERVICES / CO_RESTART_PAIR / counter 逻辑同步更新了吗?
    □ 被监督者跑在 daemon thread 中吗?如是,异常退出时主线程能感知吗?
  → 任何一个 □ 没勾,这 PR 不合
```

---

## Real Example: 2026-06-26 4G 校验卡回归

| 步骤 | 实际发生 | 应做但没做 |
|---|---|---|
| 装 watchdog 监督 hotupdate | ✓ scripts/mahjong-mitm-watchdog.sh 部署 | 故障注入测试**没写** |
| 装 systemd Restart=always | ✓ 配了 | (这个对进程崩溃够用) |
| PRD Acceptance | ✓ "watchdog 部署到 ECS / 自身崩溃能自启" | ✗ **缺"counter 累加到 3 真触发 restart"** |
| Counter reset 逻辑 | 写在 is-active 路径(错) | ✗ Step 4 清单没走 |
| 3 小时后 hotupdate handler 死 | watchdog counter 0→1→reset→0→1... → 永不到 3 → 不救 | ✗ 故障注入测试早该发现 |
| 新增 relay-noconfig 服务 | ✓ 部署了 :8002 独立 relay | ✗ **watchdog CO_RESTART_PAIR 没含它，/mode 失败无人管** |
| serve_forever 跑 daemon thread | ✓ `threading.Thread(...daemon=True).start()` + `Event().wait()` | ✗ handler 异常退出 = 线程静默死亡，主线程永远空等 |
| 用户报"4G 又卡了" | 第二次 4G/MITM 回归(11 天 5 次) | ✗ |

**三层根因**：
1. **战术层（直接触发）**: watchdog counter reset 条件过松 + relay-noconfig 未被覆盖
2. **战略层（系统缺陷）**: 监督代码无故障注入测试 + PRD 只有安装确认无功能确认
3. **哲学层（思维模式）**: "加了新层就安全了"——每次加新层不做端到端测试，新层救不了同层 bug；daemon thread 中跑关键服务是架构级错误

**修复后验证**（commit d1b4e1a, ec48754）：
- SIGSTOP handler 死锁 → counter 1→2→3 → RESTART → 105s 自动恢复 ✅
- SIGSTOP relay-noconfig → counter 1→2→3 → RESTART → 105s 自动恢复 ✅
- 100 并发风暴 → CLOSE-WAIT=0，线程/fd 无泄漏 ✅
- 500 DNS 洪水 → 100% 响应 ✅
- serve_forever 已移到主线程（线程栈验证 `do_poll`）✅

**教训**:**5 次回归,每次都在客户端→ECS 链路上加新东西(新服务/新配置/新监控),每次新层没端到端测试,新层救不了下次同层 bug**。**Meta-system 必须 self-test**。daemon thread 中跑关键 HTTP server = 自杀。

---

## Related Specs / Memories

- [mitm-connection-stability-guide.md](mitm-connection-stability-guide.md) 铁律 6/7 — 落地到这个项目
- [code-reuse-thinking-guide.md](code-reuse-thinking-guide.md) — counter 逻辑要复用/共享
- [cross-layer-thinking-guide.md](cross-layer-thinking-guide.md) — 监督者跨"系统层 + 测试层"两个 layer
- 记忆 `watchdog-counter-reset-bug-2026-06-26` — 本次真因
