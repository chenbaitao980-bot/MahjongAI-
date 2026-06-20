# N6 Server Wall — Confirmed Model (2026-06-20)

经过 attempt 1/2/3 + calibrate + 2 个 PoC，服务端断连规则已**锤死**。

## 确定的服务端行为模型

| 单连接内的发包模式 | 结果 | 证据 |
|---|---|---|
| 固定 1 个 sub_type，连发 N 个 unknown mt | **不踢**（N≥30 验证） | PoC `_poc_fixedsub`: sub=100, mt=1001..1030, final_alive=True |
| 固定 sub=100，连发 12 个 unknown mt | 不踢 | calibrate Q3 |
| 20 个 keepalive (已知 mt, sub=100) | 不踢 | calibrate Q1 |
| 6 个**不同** sub_type 混发（同一 mt 轮换 sub）| **第6帧后 FIN** | attempt 2 + attempt 3 (both mt=22 × sub 100/84/1/1006/92/0) |
| 每个 sub_type 各开**独立新连接**发 1 unknown | 全活 | pinpoint (6 subs each survive) |

## 结论

**墙 = 单连接内向 ≥6 个不同 sub_type (processid) 发包触发 FIN。**

- 不是 unknown msg_type 数量（固定 sub 连发 30 个 unknown 无事）
- 不是某个特定 sub_type（每个 sub 单独都安全）
- 不是 session 槽争抢（主号下线 75min 后 attempt 3 仍复现）
- 合理性：真实客户端一条 TCP 连接只跟一个 processid 的 frontend 通信；跨 processid 混发是明确的异常信号

## 修正后的扫描战术

**每个 sub_type 一条独立连接**，固定该 sub 扫全部 unknown mt：

```
for sub in [100, 84, 1, 1006, 92, 0]:
    connect + handshake (fresh)
    for mt in unknown_mts (4845 个):
        send (mt, sub) fixed
        wait response window
    disconnect
    cooldown
```

- **6 条连接**（不是 camouflage 估算的 9690 次重连）
- 每条 4845 mt @ 5fps ≈ 16min
- 总计 ~1.6h + 6 次握手 + cooldown
- 远比 camouflage 的 39h 可行

## 待解疑点（不影响是否可扫）

服务端对 unknown mt **静默**（不回包也不踢）。命中判据收窄为「只有会回包的隐藏协议可被发现」——这正是 Manfred 套路要找的开发期调试接口。静默的 unknown 无法区分「不存在」vs「存在但静默」，但有响应的就是 hit。

## 下一步

给 n6_fuzzer.py 加 `--sub-per-conn` 模式实现上述战术。
