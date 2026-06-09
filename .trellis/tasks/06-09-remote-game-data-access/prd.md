# brainstorm: remote real-time game data access

## Goal

让用户在登录一次后，即使在其他服务器/机器上也能远程获取自己实时对战的麻将游戏数据。

## What I already know

* 当前架构：本地 Npcap 在 Windows 游戏机上嗅探 TCP 端口 7777 的游戏流量
* `PacketStateTracker` 在本地将数据包重建为完整游戏状态（手牌、摸牌、打牌等）
* 游戏登录发生在游戏客户端内部；项目仅监听登录后的游戏流量，不拦截凭据
* 目前无任何 HTTP/WebSocket 服务器或远程暴露机制
* 数据捕获依赖本地网卡访问（Npcap），因此 **必须有一个本地代理** 运行在游戏机上
* 没有现有的 .trellis/spec 冲突

## Assumptions (temporary)

* 用户希望在游戏机 A 打牌时，能从另一台机器 B 实时读取游戏状态
* "登录一次"可能指：用某种 token/密钥认证一次，之后不用重复配置

## Open Questions

* Q1: "其他服务器"具体指什么？（最关键的架构决策）

## Requirements (evolving)

* 游戏机上的本地代理持续捕获并处理游戏数据包
* 处理后的游戏状态可从远端安全访问
* 认证机制：一次登录/配置后无需重复

## Acceptance Criteria (evolving)

* [ ] 本地代理运行时，远端可查询到最新的游戏状态（手牌、摸牌记录等）
* [ ] 未认证请求被拒绝
* [ ] 游戏未进行时，远端查询返回空状态而非报错

## Definition of Done

* 本地代理与远端访问端均有文档说明部署方式
* 认证流程文档化
* 基本测试覆盖（至少 happy path）

## Out of Scope (explicit)

* TBD — 等待需求明确

## Technical Notes

* `stable/tracker.py` — `PacketStateTracker` 是游戏状态核心
* `stable/protocol.py` — `NpcapCapture` 负责本地嗅探（需本地网卡访问）
* 关键约束：Npcap 必须在游戏所在机器上运行，无法远程化
* 推荐架构模式：本地 Agent → 中继/推送 → 远端拉取
