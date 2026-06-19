> ⚠️ **SUPERSEDED BY [06-19-anti-detection-unified](../../../06-19-anti-detection-unified/prd.md)** — 2026-06-19 合并到统一反检测任务，本文件保留作历史底料。

# 实测：ClientInfo 上行帧 msg_type 抓包确认

## Goal

从 noconfig live 流量里 dump 出 ClientInfo（客户端版本上报）上行帧，**确认其 msg_type 编号**，为后续"在 ECS 透明代理改写假版本号 2.5.10.2776 → 官方真实版本"提供精确的过滤条件。

> 这是 [06-18-clientinfo-version-rewrite](../06-18-clientinfo-version-rewrite/prd.md)（P0 反检测主菜）的**前置依赖**。msg_type 没确认就无法精确改写。

## Context

来自归档调查任务 [06-17-ecs-detection-risk](../archive/2026-06/06-17-ecs-detection-risk/) 的研究结论：

- `apk_research/decrypted-lua/app/Module.lua:1006` 的 `ClientInfo` 函数会上行客户端 version 字段
- 当前我们伪造的 4 段版本号 `2.5.10.2776`（[[hotupdate-4g-stall-fake-version]]）会**原封不动**透过 ECS 反向代理上报到真服
- 边锋系运营商若加 `client_manifest_version` 白名单 SQL（行业惯例），整套 4G 链路 100% 失效
- 研究怀疑 msg_type 是 `0x000F` / `0x620C` / `0x620D`，但**没有实锤**

## Requirements

- **R1** 在 ECS noconfig live 流量上加临时 dump：抓所有 C→S 方向的帧，按 msg_type 分组统计；筛出 payload 含字符串 `"2.5.10.2776"` 或字节序列 `02 05 0a 00 ...` 的帧
- **R2** 至少抓到 3 条不同登录会话（不同 sessionid）的疑似 ClientInfo 帧，交叉确认 msg_type 一致
- **R3** 对照 [`stable/protocol.py`](../../../stable/protocol.py) 现有的 msg_type 解码器，确认这个编号是否已有别名（避免重复定义）

## Acceptance Criteria

- [ ] msg_type 编号确定（具体十六进制值，例如 `0x000F`）
- [ ] 帧 payload 结构记录：偏移量、字段类型、version 字段在第几字节起、长度前缀格式
- [ ] 写入 [`.trellis/spec/backend/game-protocol.md`](../../../.trellis/spec/backend/game-protocol.md) 新增 ClientInfo 帧条目
- [ ] dump 用的临时脚本 / 流量样本保留在本任务目录（`samples/clientinfo-*.bin`）

## Definition of Done

- 改 `06-18-clientinfo-version-rewrite` 时直接拿 msg_type 用，不需要再抓
- spec 入库的字段定义可被 [`stable/protocol.py`](../../../stable/protocol.py) 自动化校验

## Out of Scope

- 不在此任务里做改写，只确认编号
- 不在此任务里改 [`stable/protocol.py`](../../../stable/protocol.py)（那是 06-18-clientinfo-version-rewrite 的事）

## Technical Approach

1. 在 [`remote/noconfig/hijack/tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py) C→S 路径上加临时 hook：解密后扫 payload 含 `2.5.10.2776` 字面量 → 打日志（msg_type/sub_type/帧长/payload hex）
2. 部署到 ECS，等真实用户登录触发
3. 收到日志后立即下线 hook，避免污染生产
4. payload 用 [`stable/protocol.py`](../../../stable/protocol.py) `MJProtocol._decode` 验证字段结构

## Technical Notes

关键文件：
- [`remote/noconfig/hijack/tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py) — 透明代理点
- [`stable/protocol.py`](../../../stable/protocol.py) — msg_type 解码器
- [`apk_research/decrypted-lua/app/Module.lua`](../../../apk_research/decrypted-lua/app/Module.lua) :1006（如果存在）—— ClientInfo 源
- [`apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua`](../../../apk_research/decrypted-lua/app/Protocols/SRSProtocol.lua) — 确认 SRS 协议字段定义

关联记忆：[[hotupdate-4g-stall-fake-version]] [[srs-cfb-and-string-prefix-fix]] [[noconfig-4g-handread-chain]]

研究依据：[../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md](../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md) §3
