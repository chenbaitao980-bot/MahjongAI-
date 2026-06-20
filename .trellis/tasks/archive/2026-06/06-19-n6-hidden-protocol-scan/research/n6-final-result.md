# N6 全量扫描最终结论 (2026-06-20 02:45 完成)

## 结果：clean negative — 没有会响应的隐藏协议

```
=== sub-per-conn finished: total_sent=24226 total_hits=0 ===
```

| 指标 | 值 |
|------|-----|
| 扫描 unknown msg_type | [1,5000] \ 闭集 = 4845 个 |
| sub_type | 100, 84, 1, 1006, 92, 0 |
| 实际发送 | 24226 帧（5 个 sub 各 4845 + sub=0 仅 1） |
| **非握手期响应（=潜在 hit）** | **0** |
| 总 recv 帧 | 24 = 握手期 push(mt 1/4/6/24) × 6 连接，全是噪声 |

## 关键观察

1. **服务端对所有 unknown msg_type 完全静默**：4845 个未知协议码 × 5 个 sub_type 全部发完，服务端**一个响应都没回**（除握手期固定推的 4 个帧）。
2. **sub=0 (SRS 入口路由) 主动拒绝**：handshake 后发第一个 unknown(mt=29) 立即 FIN。入口路由层对 unknown 零容忍。其它 sub_type(100/84/1/1006/92) 容忍 unknown（静默丢弃不踢）。
3. **断连墙战术验证成功**：`--sub-per-conn`（每 sub_type 一条连接固定 sub）完美绕过「单连接多 sub_type FIN」墙，5 个 sub_type 各扫满 4845 帧无中断，单 sub 失败隔离正常（sub=0 死了不影响整体）。

## 判定

**N6（Manfred 隐藏协议字典扫）在该服务端 = 不可行。** 

服务端不是「有隐藏协议但我们没找到」，而是**对任何 unknown msg_type 静默丢弃**——这种服务端设计下，fuzz 无法区分「协议不存在」和「协议存在但不回包」，且实测 24226 个全静默，没有任何 dead-code/debug 接口会响应。

这与 Manfred (DEFCON 25) 的前提不同：他成功的商业 MMO 对 unknown 协议**会回错误码/会响应**，给了 fuzz 反馈信号。本游戏服务端静默 = fuzz 无反馈 = 该套路失效。

## 对 H16 父任务的贡献

N6 是 H16 突破矩阵里「中等概率(15-30%)」那条路。现在**清零**：
- D23 证伪（0x022B 是自己起手）
- N7 证伪（无事件泄漏暗牌）
- **N6 clean negative（无响应的隐藏协议）**
- → 协议层读对手暗牌的所有路径已穷举完毕，确认 hard wall

可交付能力回落到 **N5 公开信息防守信号**（已 live）。

## 工件
- `full-scan-console.log` — 完整扫描日志（sessionid 已脱敏）
- ECS `/tmp/n6_fuzz/spc.jsonl` — 24250 行原始记录（含 sessionid，**不入 git**，留 ECS）
