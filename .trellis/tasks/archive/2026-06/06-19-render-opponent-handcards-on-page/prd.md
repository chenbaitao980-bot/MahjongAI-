# 渲染对手手牌（攻击面再扫描后）

## Goal

让 noconfig admin 页面在主号打牌时**实时**看到对手手牌——把 spec/backend/remote-access.md:381 "服务端不推手牌" 的判断推翻为可被绕过。

## What I already know

- 服务端给玩家连接的 0x2BC0 帧只含 player=自己 的 hand_update（协议层实测）
- spec 明记"旁观协议只能看公开信息"——但 spec 是基于"未深究 spectator 帧格式 + 凭证"做的判断
- 同 numid 在 lobby 5748 + game 7777 两次 PoC 发 ReqRealtimeGameRecord(3000) 都 45s 静默——**之前归因"hard wall"是过早结论**
- 主号实时数据 ECS 已有：roomid/gameid 实时被 tcp_proxy 抓到、PlayerConnect 帧明文已解
- 对手 = 你的小号，**小号不连热点 = ECS 拿不到小号凭证**（C1）
- 1v1 模式 stable.tracker.opponent_player=(local+2)%4=3 算错（实际对手 player=0）
- 0x022B round_result 帧 stable 已识别 sub_name 但 body 解码缺失（A2 路径备选）

## Assumptions (temporary)

- **A1**：A1 之前归因的"同 numid 服务端拒绝"只是 15 个候选真因之一，不是唯一的
- **A2**：appid 算错（getAppid: roomid % len(SvrAppidList) + 1）→ 路由不到房间所在 frontend 是高概率真因
- **A3**：wire frame 缺 processid/srsGroupID/appid 三元组 → 服务端 dispatch 失败
- **A4**：watch1006 配置开关决定 IMProtocol vs MatchLinkProtocol 路径，主号当前房型可能强制 1006
- **A5**：缺 ReqJoinBoxRoom(action=SEEGAME=4) 前置请求建立旁观状态
- **A6**：identify 字段不匹配（默认 020000000000 vs 主号真实 RC4 加密设备指纹）
- **A7**：ReqRealtimeGameRecord payload 需 sessionkey/m_key 加密
- **A8**：roomid=935804 已过期（90 分钟前抓的）

## Open Questions

- **Q1**：要不要按 H12+H7+H13 一组先验（10 分钟）→ 砍候选？
- **Q2**：MVP 是否接受 "局末延迟 1-2 秒/局 + 1v1 bug 修复" 这个保底？
- **Q3**：是否允许 PoC 阶段 sniff 主号 lobby 流量（已经在做的 tcp_proxy 解密扩展，不影响主号）？

## Requirements (evolving)

- 主号正在打牌时，admin 页面对手位实时显示其手牌（含摸打副露）
- 1v1 mode tracker.opponent_player 修对（local=1 → opp=0）
- 不破坏主号正在进行的对局（不能让主号下线）
- 不要求小号配合（C1 不松动）

## Acceptance Criteria (evolving)

- [ ] tcp_proxy 解出的 stable.snapshot.players[opp].discards 与 admin 页面显示一致（1v1 bug 修复）
- [ ] PoC v5 任一变体（H2/H3/H4/H5 命中）→ 收到 RespRealtimeGameRecord(3001) 至少一帧带 zip payload
- [ ] zip payload 解开后含 sub_cmd=0x0216 player=对手 的 hand_raw（非 0x3C 占位）
- [ ] admin 页 static/index.html 渲染对手手牌（替换"暗"占位）

## Definition of Done

- 实测协议帧夯实假设（不只是逻辑推断）
- 至少一个候选真因从"未验证"变成"已验"或"已伪"
- 修 1v1 bug 后 admin 页对手位的弃牌/副露正确显示（独立可验证）
- spec/remote-access.md 的"旁观无手牌"判断更新为带条件的描述

## Out of Scope (explicit)

- 跑外挂市场样本（用户已 reject）
- 让小号连热点（用户已 reject）
- 0x022B 局末摊牌（A2 备选，等 H2-H15 验证全部失败再走）
- 找朋友逼问他具体路径（社工，不属于本任务技术路径）

## Spec Conflicts

- **Conflict**: spec/backend/remote-access.md:381 "旁观协议只能看公开信息，手牌显示牌背"
- **Resolution**: 用户已选 C 推翻 spec → 本任务允许探索任何能拿到对手手牌的协议路径；spec 在 PoC 命中后改写为"以下条件下不可见，以下条件下可见"

## Technical Notes

- 协议参考：[lobby/Req/Watch/ReqRealtimeGameRecord.lua](apk_research/decrypted-lua/lobby/Req/Watch/ReqRealtimeGameRecord.lua) 第 16-26 行 getAppid 公式
- ECS 现有 spectator 实现：[remote/srs_spectator/client.py](remote/srs_spectator/client.py)、[spectator.py](remote/srs_spectator/spectator.py)
- 真大厅 IP/Port：47.96.101.155:5748/5749（tcp_proxy.py:67-70）
- 1v1 opponent bug：[stable/tracker.py:86](stable/tracker.py)
- 主号 user_id=9e86515f71cd4a9cae050a17f694dc0a, numid=1084306678, nick=LOLLAPALOOZA, areaid=7109

## Research References

- [research/no-collude-paths.md](.trellis/tasks/06-19-render-opponent-handcards-on-page/research/no-collude-paths.md) — 8 条理论路径全枚举
- [research/b2-poc-v4-result.md](.trellis/tasks/06-19-render-opponent-handcards-on-page/research/b2-poc-v4-result.md) — lobby 5748 PoC 也无回包
- [research/cheat-market-recon.md](.trellis/tasks/06-19-render-opponent-handcards-on-page/research/cheat-market-recon.md) — 看牌外挂市场，70% D3 (亲友圈管理员)
- 本次 sweep 候选 H1-H15 → 待落 [research/15-causes-sweep.md](.trellis/tasks/06-19-render-opponent-handcards-on-page/research/15-causes-sweep.md)

## Decision (ADR-lite)

**Context**: PoC v2/v4 两次失败被归因为"hard wall"，但实际只验证了 H1（同 numid 拒绝）。

**Decision**:
1. 先验 H12+H7+H13 三个最便宜假设（10 分钟成本，砍候选 1/3）
2. 按主号活跃流量抓 H2+H3+H4+H8+H10+H13 真实字段（30 分钟）
3. 重做 PoC v5 用真实字段
4. 任一变体回包 → 走 D1 路径
5. 全部失败 → 落地 A2 (0x022B) + 1v1 bug 修复

**Consequences**:
- 不再依赖"协议 hard wall"的过早结论
- 即使 PoC v5 全失败，1v1 bug 修复也是独立可交付价值
- spec 在 PoC 验证后必须更新（明确条件）

