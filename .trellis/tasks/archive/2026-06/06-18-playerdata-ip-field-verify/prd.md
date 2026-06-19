> ⚠️ **SUPERSEDED BY [06-19-anti-detection-unified](../../../06-19-anti-detection-unified/prd.md)** — 2026-06-19 合并到统一反检测任务，本文件保留作历史底料。

# 实测：PlayerData ip 字段值确认

## Goal

抓一段经 ECS 反代登录的 PlayerData (msgid=6, S→C) 帧，**确认服务端权威记录的 `ip / iparea / sp / lastip / lastiparea / lastsp` 5 个字段实际填了什么值**——验证调查阶段的核心假设："服务端用 IP 做账号画像，且我们多用户共享 ECS 出站 → 全部记到 8.136.37.136"。

## Context

来自 [research/srs-server-side-fingerprint.md](../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md) §1：

- `apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua:19-110` 反汇编实锤 PlayerData 含 5 个 IP 画像字段
- **但研究没看到实际值**——这是推断不是实测
- 假设若成立：所有 noconfig 用户的 `ip` 都 = 8.136.37.136 → 一条 SQL 即出风控
- 假设若不成立：服务端可能从别处（应用层上报、TCP 真实源）取 IP，这会改变反检测优先级

这是一道单选题，必须实测。

## Requirements

- **R1** 抓至少 2 个不同 noconfig 用户的 PlayerData（S→C, msgid=6, flag=0 认证成功后）解密帧
- **R2** 解析出 `ip / iparea / sp / lastip / lastiparea / lastsp` 6 个字段的实际值并脱敏记录（IP 只露 `8.136.37.*` 段确认即可）
- **R3** 横向对比：同一账号在 ECS vs 直连真服 (4G/家宽不经 ECS)，看 `ip` 字段是否切换 —— 这是验证"服务端从 TCP 源取 IP"的关键
- **R4** 把结论补回 [research/srs-server-side-fingerprint.md](../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md) §1（可在归档目录原地编辑研究文件）

## Acceptance Criteria

- [ ] 6 个 IP 字段的实测值已记录（脱敏后），至少 2 条独立样本
- [ ] ECS vs 直连对照已完成，结论二选一明确：
  - **A**：服务端 ip = TCP 源 IP（= 我们 ECS）→ 多 IP 池是必须的兜底
  - **B**：服务端 ip 来自客户端上报 → 可在 tcp_proxy 改写
- [ ] 结论写入研究文件 §1 + 沉淀 1 条 user memory（标题如 "SRS PlayerData ip 字段来源实测"）

## Definition of Done

- 改 [06-18-noconfig-user-cap](../06-18-noconfig-user-cap/prd.md) 时，结论决定限流阈值是否要调（如果 ip = TCP 源，10 用户上限就是绝对值；如果 ip 来自上报且能改写，可放宽）
- 改 [06-18-clientinfo-version-rewrite](../06-18-clientinfo-version-rewrite/prd.md) 时，可以同步评估"是否顺手改写 ClientInfo 里上报的本地 IP"（如果协议有这个字段）

## Out of Scope

- 不在此任务里实施 IP 改写（仅做实测）
- 不在此任务里实施多 IP 池（仅给出后续是否要做的依据）

## Technical Approach

1. 在 ECS 上对 noconfig 5045 大厅端口加 dump：`tcp_proxy.py` S→C 路径，msgid=6 帧解密后 hexdump
2. 等 2 个不同 noconfig 用户登录（admin 上能看到 sessionid）
3. 用 [`stable/protocol.py`](../../../stable/protocol.py) 的 `parse_player_data` 解析（注意 [[playerdata-nick-len-1byte.md]] —— nick_len/url_len/msg_len 都是 1B 不是 2B）
4. 对照实验：让一个用户先经 ECS 登录抓一帧，再切 4G 直连真服抓一帧

## Technical Notes

关键文件：
- [`remote/srs_spectator/handshake.py`](../../../remote/srs_spectator/handshake.py) `parse_player_data` —— 已有解析器
- [`apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua`](../../../apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua) :19-110 —— 字段定义权威
- [`stable/protocol.py`](../../../stable/protocol.py) — msgid=6 解码

关联记忆：[[playerdata-nick-len-1byte]] [[srs-cfb-and-string-prefix-fix]] [[srs-key-cracked]]

研究依据：[../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md](../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md) §1
