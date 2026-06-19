> ⚠️ **SUPERSEDED BY [06-19-anti-detection-unified](../../../06-19-anti-detection-unified/prd.md)** — 2026-06-19 合并到统一反检测任务，本文件保留作历史底料。

# 实测：废账号经 ECS vs 直连对照实验

## Goal

用**废账号**做 24h 对照实验，确认边锋系运营商**当前**对"阿里云杭州段经 ECS 反代登录"的实际处置形态——是已经在风控（封号 / 软处置 / 二次验证），还是仍在装死窗口。

## Context

来自 [research/idc-ip-multi-account-risk.md](../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md) 的预测：

- ECS 同城掩护（真服 + 我们都在阿里云杭州 AS37963）→ 命中信号弱 1-2 档
- ≤ 10 用户/1 月：< 15% 被打 —— **预测是装死窗口**
- 但**没有实测过**

这是个二选一：
- **A**：ECS 段已被风控（哪怕轻处置）→ 必须立刻多 IP 池兜底
- **B**：装死窗口确认 → 按当前 B 方案推进 P0/P1 措施即可

实验在 4 小时内拿到强信号，比凭推测决策强 100 倍。

## Requirements

- **R1** 准备 2 个废账号（注册成本最低的小号；不能用主力账号，存在被永封风险）
- **R2** **账号 A**：连续 24h 通过 ECS 反代登录打 5 局（小额）
- **R3** **账号 B**：同样 24h 直连真服（4G 或家宽不经 ECS）打 5 局，作为对照组
- **R4** 观察项（每个账号每局后记录）：
  - 能否正常登录（flag 值）
  - 能否进游戏房间
  - 局后是否能正常结算
  - 是否触发图形验证 / 短信验证 / 二次登录确认
  - 是否被踢出
  - 24h 后账号能否登录
- **R5** 结论补到 [research/idc-ip-multi-account-risk.md](../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md) §6

## Acceptance Criteria

- [ ] 两个账号 24h 实验完成，每局后观察项有记录（即使全 OK 也要写）
- [ ] 二选一结论明确：A（已风控）/ B（装死窗口确认）
- [ ] 若结论是 A，**立即升级**：暂停 noconfig 新用户注册 + 启动多 IP 池采购评估（独立任务）
- [ ] 沉淀 1 条 project memory 标记本次实验日期与结论

## Definition of Done

- 决策 B 方案是否需要紧急加 #3（多 IP 池）有明确依据
- [06-18-noconfig-user-cap](../06-18-noconfig-user-cap/prd.md) 的限流阈值是否要从 10 调成 5 / 3 有依据

## Out of Scope

- 不在此任务里搭建多 IP 池（结论决定后另立任务）
- 不用主力账号
- 不上报问题给客服（怕引起注意）

## Technical Approach

| 步骤 | 操作 |
|---|---|
| 注册废账号 | 用临时手机号注册 2 个新账号（账号 A / B） |
| 账号 A 路径 | 手机连 PC 热点（已配 NetConf MITM） → 4G 切回打牌 → 流量经 ECS 反代 |
| 账号 B 路径 | 不连 PC 热点，纯 4G 直连真服 → 不走 ECS |
| 局后记录 | 每局结束截图 + 文字日志（登录 flag、是否被踢、是否弹验证）→ samples/log-A-{局}.md / log-B-{局}.md |
| 24h 验证 | 第二天再登录一次确认账号状态 |

## Technical Notes

⚠️ **风险声明**：

- 实验本身**有可能加速被发现**（如果运营商有"新账号 + IDC IP 首次登录"的强规则）
- 但相比"用户量起来后被批量封"，这是更可控的早期暴露
- 必须用废账号；主力账号封禁损失大于实验收益

关联记忆：[[noconfig-multiuser-deployed]]

研究依据：[../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md](../archive/2026-06/06-17-ecs-detection-risk/research/idc-ip-multi-account-risk.md) §2 §6
