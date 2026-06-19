> ⚠️ **SUPERSEDED BY [06-19-anti-detection-unified](../../../06-19-anti-detection-unified/prd.md)** — 2026-06-19 合并到统一反检测任务，本文件保留作历史底料。

# ClientInfo 假版本号 ECS 在线改写（P0 反检测主菜）

## Goal

在 ECS 反向代理 [`tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py) 的 C→S 路径上识别 ClientInfo 帧 → 把上行的假版本号 `2.5.10.2776` 改写成**官方真实版本** → 上传到真服。**堵死调查阶段定性的 P0 漏洞**：边锋若加 `client_manifest_version` 白名单 SQL（成本 1 人 1 周），整套 4G 链路一夜失效。

## Context

来自 [research/cocos2dx-manifest-tamper-detection.md](../archive/2026-06/06-17-ecs-detection-risk/research/cocos2dx-manifest-tamper-detection.md) 的 P0 结论：

- Cocos2d-x 引擎层无 manifest 签名（永久安全）
- 但 [`Module.lua:1006`](../../../apk_research/decrypted-lua/app/Module.lua) 的 ClientInfo 协议会上行客户端 version
- 我们的 `2.5.10.2776` 是为了让 `versionLessThan` 永远返回 NOUPDATE 而设的伪高位（[[hotupdate-4g-stall-fake-version]]）
- 但这个值会原封不动透过 ECS → 真服一旦做 SQL 白名单核对，立即穿帮

**前置依赖**：[06-18-clientinfo-msgid-dump](../06-18-clientinfo-msgid-dump/prd.md) 必须先确认 msg_type 编号。

## Requirements

- **R1** 在 [`remote/noconfig/hijack/tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py) C→S 路径加 ClientInfo 帧识别（按 msg_type 过滤）
- **R2** 解密帧 → 找到 version 字段 → 改写成**官方真实最新版本**（**配置项**，避免硬编码；从 `config_noconfig.yaml` 读 `official_client_version`）
- **R3** 重新加密 + 修正 payload 长度前缀（参考 [[srs-cfb-and-string-prefix-fix]]：CFB 每帧 fresh-from-IV，字符串 1B 长度前缀）
- **R4** 改写后的帧透传到真服，确保 SRS 加密链不破（fresh-from-IV 每帧独立，不影响后续帧解密）
- **R5** **零停机激活**：通过 systemctl reload 而非 restart；保持现有用户连接不掉
- **R6** ECS 加结构化日志：每改写一次记录 (sessionid, original_version, rewritten_version)，方便 admin 审计

## Acceptance Criteria

- [ ] 真机经 ECS 登录后，从 ECS 出站抓帧确认 version = 官方真实版本（不是 2.5.10.2776）
- [ ] 真服认证依然 flag=0（改写后的版本号被服务端接受）
- [ ] 现有用户登录链路不受影响（reload 期间无掉线）
- [ ] 配置项 `official_client_version` 在 `config_noconfig.yaml` 中可改、改完 reload 即生效
- [ ] 改写日志可在 admin 页面或 journalctl 中查询

## Definition of Done

- 真机测试覆盖：4G + 家宽 WiFi 各一次完整对局
- 单元测试：构造一帧含 `2.5.10.2776` 的 ClientInfo → 确认输出帧 version 字段已替换、长度前缀正确、解密后能 round-trip
- 部署遵守 [[server-readonly-git-sync-discipline]]：本地改 → git commit → restart_hotspot_mitm_and_ecs.bat 推 ECS

## Out of Scope

- 不顺手改其他字段（只改 version；其他字段如 channelid / osver 等若也需要改，另立任务）
- 不在此任务实施多 IP 池

## Technical Approach

1. **依赖确认**：等 [06-18-clientinfo-msgid-dump](../06-18-clientinfo-msgid-dump/prd.md) 完成，拿到 msg_type 实锤
2. **配置加字段**：[`remote/relay/config_noconfig.yaml`](../../../remote/relay/config_noconfig.yaml) 加 `official_client_version: "1.0.1.1776"`（实际官方版本由 [06-18-clientinfo-msgid-dump](../06-18-clientinfo-msgid-dump/prd.md) 顺带 dump 一份官方真包确认）
3. **rewriter 实现**：仿照 [`remote/noconfig/hijack/`](../../../remote/noconfig/hijack/) 现有 `LobbyS2CRewriter` / `RespSRSAddr` 改写器风格，新建 `clientinfo_rewriter.py`
4. **接入 tcp_proxy**：在 5045 / 5067 / 5167 / 5700-5723 全部入口生效（避免漏改）
5. **测试**：本地用录制的 ClientInfo 样本（来自 [06-18-clientinfo-msgid-dump](../06-18-clientinfo-msgid-dump/prd.md) 的 samples/）做 round-trip
6. **部署**：必须走 `restart_hotspot_mitm_and_ecs.bat`，禁止 ssh 上手改（[[server-readonly-git-sync-discipline]]）

## Technical Notes

关键文件：
- [`remote/noconfig/hijack/tcp_proxy.py`](../../../remote/noconfig/hijack/tcp_proxy.py) — 透明代理点，所有用户流量入口
- [`remote/noconfig/hijack/`](../../../remote/noconfig/hijack/) — 现有 rewriter 实现风格参考
- [`remote/relay/config_noconfig.yaml`](../../../remote/relay/config_noconfig.yaml) — 配置文件
- [`stable/protocol.py`](../../../stable/protocol.py) — 加解密工具
- [`scripts/restart_hotspot_mitm_and_ecs.py`](../../../scripts/restart_hotspot_mitm_and_ecs.py) — 部署入口

关联记忆：[[srs-cfb-and-string-prefix-fix]] [[srs-key-cracked]] [[playerdata-nick-len-1byte]] [[hotupdate-4g-stall-fake-version]] [[server-readonly-git-sync-discipline]]

研究依据：
- [../archive/2026-06/06-17-ecs-detection-risk/research/cocos2dx-manifest-tamper-detection.md](../archive/2026-06/06-17-ecs-detection-risk/research/cocos2dx-manifest-tamper-detection.md) §1.2 P0 应对
- [../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md](../archive/2026-06/06-17-ecs-detection-risk/research/srs-server-side-fingerprint.md) §3
