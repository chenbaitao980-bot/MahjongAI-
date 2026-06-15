# noconfig 读牌链路修复：突破硬编码 DNS + NetConf 改写持久化 + 上游地址校准

## Goal

让"远程读自己手牌"的 noconfig 方案在真机跑通：手机进一局牌后，牌局流量经 ECS 代理被解码，
手牌实时显示在 8002。当前实测**牌局流量从未到过 ECS**，根因已定位（见下），需系统性修复。

## 决定性根因（见 research/diagnosis-2026-06-14.md）

1. **游戏硬编码公共 DNS（119.29.29.29 腾讯 / 223.5.5.5 阿里），绕过热点 DNS 劫持。**
   手机查 `gxb-api.hzxuanming.com` 直接问公共 DNS，从不问 PC:53 →
   `setup_mitm` 的整个 DNS 劫持前提失效 → 热更请求从未到 PC → NetConf 永远是真版 →
   手机直连真服打牌 → ECS 收不到牌。**这是 #1 阻断点。**
2. tcp_proxy 上游大厅地址 `47.96.101.155:5748` 与手机实际大厅 `47.110.230.204:5708` 不符（过时）。
3. `RespSRSAddr` 改写从未被真机触发验证。

## 关键约束（已定）

- **手机不能 root** → 排除 LayerFS/文件覆盖。持久化只能靠"热更改写 NetConf + 版本顶高让游戏跳过后续热更"。
- MVP 目标 = **任意网络读牌**（手机断热点后 4G 也走 ECS）。

## Technical Approach

**第一阻断点突破（必经）：WinDivert 网络层 DNS 劫持。**
手机经 PC 热点上网，其发往 `119.29.29.29:53 / 223.5.5.5:53` 的 DNS 查询**必经 PC 网关转发**。
用 `pydivert`(WinDivert) 在 PC 转发路径拦截 UDP:53：
- 命中 `gxb-*.hzxuanming.com`（及热更相关域名）→ 伪造 A 响应指向 PC（192.168.137.1），其余放行。
- 这样游戏连 PC:443 走现有 `setup_mitm` 热更链路 → 下发改写 NetConf（指向 ECS）。

**递进验证（决定"任意网络"是否可达）：**
1. DNS 劫持通后，确认热更走完 version→project→NetConf.luac 三步，改写 NetConf 写入手机缓存。
2. 手机断热点切 4G，确认 NetConf 仍指向 ECS（游戏因版本 9.9.9.99 跳过热更）→ 牌局流量到 ECS。
   ⚠ 风险：若游戏每次启动**强制**热更校验，4G 下会被真热更覆盖回真版 → "任意网络持久"不可达，
   届时回退为"连热点时读牌"。此风险在第 2 步才能证伪/证实。

**配套修复：**
- 校准 tcp_proxy 真实上游（用抓到的 `47.110.230.204:5708` 等核对大厅/游服真实拓扑）。
- `RespSRSAddr` 改写真机验证（确认 msgid=15 帧格式/加密与代码假设一致）。

## Requirements

- PC 端 WinDivert DNS 拦截器：拦截手机转发的 UDP:53，劫持热更域名 → PC，其余透传，不影响手机正常上网。
- 与现有 `setup_mitm` 443 热更链路对接，使改写 NetConf 真正下发。
- 校准 tcp_proxy 上游地址至真实拓扑。
- 真机验证手牌端到端显示在 8002。

## Acceptance Criteria

- [ ] WinDivert 拦截器运行后，PC MITM 日志出现手机的 `version→project→NetConf.luac` 三步请求。
- [ ] ECS `journalctl -u mahjong-tcp-proxy` 出现 `0x2bc0 hand_trusted` + `push to relay`。
- [ ] 8002 `/state?token=...` 返回与手机一致的实时手牌，连续 ≥2 局可复现。
- [ ]（终极）手机断热点切 4G 后仍能读牌 —— 若证实不可达，明确回退为"连热点读牌"并记录。

## Definition of Done

- 真机端到端复现通过（非单测）。
- WinDivert 拦截器、上游地址校准、RespSRSAddr 验证结果写回 spec/research。
- 临时调试产物（hijack_live.log/err、抓包脚本）清理或归档。
- 风险与回滚（DNS 拦截影响手机上网、NetConf 改写、ECS 配置）有记录。

## Decision (ADR-lite)

- **Context**: 游戏硬编码公共 DNS，DHCP 下发 DNS 的劫持方式对其无效。
- **Decision**: 升级为 WinDivert 网络层拦截手机转发的 DNS 包，强制劫持热更域名。
- **Consequences**: 引入 pydivert 依赖 + WinDivert 驱动 + 管理员权限；只在"手机连 PC 热点"时能布设拦截，
  因此"任意网络持久"仍取决于游戏是否跳过后续热更（待验证，有回退预案）。

## Out of Scope

- Frida 进程内 siphon、旁观者/双连等其他读牌路线（[[siphon-final-goal]]）。
- 手机端任何改动（不 root、不装证书、不改设置）。

## Technical Notes

- 见 [`research/diagnosis-2026-06-14.md`](research/diagnosis-2026-06-14.md)。
- 关键文件：`remote/noconfig/hijack/{setup_mitm,tcp_proxy,netconf_patch,manifest_forge}.py`、
  `remote/relay/main.py`、`stable/{protocol,tracker,mapping}.py`。
- 抓包入口：scapy，热点网卡 IP=192.168.137.1，手机 192.168.137.67；ECS root@8.136.37.136(paramiko)。
- 当前黄金调试窗口：手机仍在 PC 热点上。
