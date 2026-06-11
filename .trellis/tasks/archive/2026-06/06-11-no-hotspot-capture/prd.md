# 解决断开热点后无法捕获手牌数据的问题

## Goal

当手机连接 PC 热点时可以正常抓取手牌数据，但断开热点（手机连正常 WiFi）后就无法捕获。需要找到一种方案，让用户在不开启 PC 热点的情况下也能持续捕获手牌数据。

> **2026-06-11 目标澄清（重要）**：用户真实场景是**出门用 4G 也要能读牌**，不是只在家。
> 这超出软路由 MVP 的能力——软路由/PC 热点都只在「手机连那张经过抓包设备的 WiFi」时有效，
> 手机一旦走 4G/别处网络就读不到。经确认，唯一能覆盖「任意网络」的可行路是 **VPN 隧穿**
> （手机挂 WireGuard 把流量绕回带 extractor 的设备，extractor 被动嗅探游戏数据帧）。
> VPN 隧穿不碰认证（手机自己照常登录加密），只搬动「流量经过哪台设备」，因此可行——
> 与已永久放弃的「场景B（relay 冒充手机）」本质不同。详见 gameclient-scenario-b-constraints 记忆。
> 软路由 MVP 仍作为「在家场景」的可用方案保留，但不满足出门 4G 目标。

## VPN 隧穿方案（覆盖出门 4G 的真实目标）

**为什么可行**：场景B 失败是因为 relay 冒充手机做认证，撞 native 加密 + nonce 防重放。
VPN 隧穿让手机**自己**完成登录/加密/打牌，extractor 只**被动嗅探**游戏数据帧（0x2BC0 等本就可解），
不破解任何东西——只是把「手机流量经过哪」从 LAN 改成隧道。

**拓扑 V1（推荐）— 全云**：
```
手机(任意网络/4G) ──IKEv2 IPSec──▶ 云服务器[strongSwan + extractor + relay] ──▶ 游戏服务器:7777
```
- 一台云主机全搞定，家里不留设备；手机任意网络都行
- split tunnel：只把游戏服务器 IP 段路由进隧道，其余流量照常走 4G
- 手机用 **Android 系统自带 VPN**（Settings > VPN > IKEv2 IPSec PSK），0 app

**拓扑 V2 — 回家**：
```
手机(任意网络) ──IKEv2 IPSec──▶ 家里软路由/NAS[strongSwan + extractor] ──push──▶ 云 relay
```
- 复用家里带宽，但需公网/DDNS 入口 + 设备常开

**决策**：V1 + strongSwan IKEv2 + split tunnel。手机系统 VPN，一次配置永远不用管。

## What I already know

* **当前架构**：Extractor（Npcap 嗅探）+ Relay（FastAPI 中继）双组件
* **热点模式原理**：PC 开启 Windows 移动热点（ICS，网关 192.168.137.1），手机连此热点，所有流量经过 PC 网卡，Npcap 被动嗅探
* **断开热点 = 失去流量路径**：手机切到正常 WiFi 后，流量不再经过 PC，Extractor 无法嗅探
* **apk_research 结论**：relay 自己冒充手机连 7777 **不可行**（帧加密在 native .so 里，Lua/Python 无法复现）
* **GameClient（场景B）**：relay 中有 GameClient 代码，可主动连游戏服务器，依赖 extractor 先注册 handshake_blob + auth_token_12b，断热点后 extractor 也不会再推送新凭证
* **软路由方案**：已存在 install_openwrt.sh / install_linux.sh，让 extractor 常驻在 OpenWRT/软路由上，手机连正常 WiFi 即可被抓包
* **当前 extractor config**：`relay_url: http://127.0.0.1:8000`（本机）
* **当前 relay config**：`game_server_ip: 47.96.0.227`

## Assumptions (temporary)

* 用户的使用场景是：在家正常连 WiFi 打麻将，不想每次都切到 PC 热点
* 用户可能没有现成的软路由硬件
* 用户希望用最小的硬件/网络改动实现目标

## 用户需求确认

* 手机连一次 PC 热点完成凭证提取
* 之后手机切到任何网络（正常 WiFi/4G），服务器仍能抓取到打牌数据
* **本质 = 让 Relay 的 GameClient（场景B）真正工作**

## Open Questions

* ~~GameClient 用 replay 的 handshake_blob + auth_token_12b 能否成功连上游戏服务器？~~
  **已实测确认不可行**（2026-06-11）。GameClient 跳过了 SRS 认证层
  （0x0001 sub=0x0000 握手、0x0005 reauth 加密帧）→ 服务端立即关闭连接
  （存活 0.0 秒）。Extractor 日志证实真实游戏连接必须先过 native .so 加密层。
* 凭证目前仅存在内存中（`_cfg` dict），relay 重启后丢失 → 已修复（持久化到 config.yaml）

## Requirements (evolving)

* 手机连接正常 WiFi 时也能捕获手牌数据
* 不需要手机每次切换 WiFi
* 凭证需要持久化，relay 重启后仍可用
* 提供明确的普通 WiFi 部署入口：预配置 extractor bundle + 匹配的云端 relay config
* 不覆盖仓库默认 `remote/*/config.yaml`，避免真实 token 被误提交

## Acceptance Criteria (evolving)

* [ ] 手机连正常 WiFi 时，AI 客户端能获取到实时手牌数据
* [x] 可从开发机一条命令生成预配置软路由/NAS extractor bundle
* [x] bundle 内的 `remote/extractor/config.yaml` 指向云端 relay，而不是本机 `127.0.0.1`
* [x] OpenWRT/Linux 安装脚本支持环境变量免交互传入 `RELAY_URL/API_TOKEN/IFACE`
* [x] 文档明确说明断开 PC 热点后必须把抓包点移到手机流量经过的路由器/NAS/旁路由

## Definition of Done (team quality bar)

* 方案文档完整（含网络拓扑图）
* 代码改动有 lint/typecheck
* 至少一种可行方案可以端到端验证

## Out of Scope (explicit)

* 反编译 native .so 实现帧加密复现（apk_research 已确认不可行）
* 在普通 WiFi 下继续用 PC 本机 Npcap 抓手机单播流量（网络拓扑上不可保证）

## Technical Notes

### 关键文件
* `remote/extractor/capture.py` — Npcap/tcpdump 抓包适配器，含 `find_hotspot_iface()`
* `remote/extractor/config.yaml` — extractor 配置（当前 relay_url=127.0.0.1）
* `remote/relay/config.yaml` — relay 配置
* `remote/relay/game_client.py` — 场景B 主动连接游戏服务器
* `remote/relay/state_store.py` — 在线/离线模式切换逻辑
* `apk_research/apk-auth-reverse.md` — 认证逆向分析结论
* `enable_hotspot.ps1` — Windows 热点自动开启脚本

### 现有方案对比

| 方案 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| **A. Windows 热点** | PC 做热点，手机流量经 PC | 零硬件成本 | 每次要切 WiFi，PC 必须开机 |
| **B. 软路由常驻** | extractor 在 OpenWRT 上常驻嗅探 | 手机无需切 WiFi，PC 可关 | 需要软路由硬件 + 云端 Relay |
| **C. 云端 Relay + 远程 extractor** | extractor 在局域网某设备上（路由器/NAS），推送到云端 relay | 手机不需切 WiFi | 需要公网服务器 + 局域网内有 Linux 设备 |
| **D. ARP 欺骗/中间人** | PC 在局域网内伪装网关，让手机流量经过 PC | 不用切 WiFi | 复杂、不稳定、可能被检测 |
| **E. Frida hook** | 在手机上 hook native socket 层，直接读解密后的明文 | 不依赖网络拓扑 | 需要 root/越狱，维护成本高 |

### apk_research 核心结论
* 0x0005 auth_req 的帧加密全在 native `libcocos2dlua.so` 里
* m_key 由服务端动态下发，Lua 拿不到
* 纯 Python/Lua **无法复现** socket 帧加密
* **但游戏数据帧（0x2BC0 等）在被动嗅探时是可解的**（extractor 已验证）

## Research References

* `apk_research/apk-auth-reverse.md` — 认证逆向分析，确认 relay 冒充手机不可行

## Decision (ADR-lite)

**Context**: 断开 PC 热点后，手机到游戏服务器的 TCP 流量不再经过 PC。`apk_research` 已确认 relay 纯 Python/Lua 冒充手机连 7777 不可行，因此不能靠云端主动复现认证链路解决。

**Decision**: 采用“云端 relay + 常驻 extractor 在软路由/NAS/旁路由”的方案作为 MVP。新增预配置打包能力：`package_extractor.py --relay-url ... --write-relay-config ...` 会生成包含云 relay 地址和共享 token 的 extractor bundle，并写出匹配的 relay 配置。

**Consequences**: 用户需要一台承载手机流量的设备运行 extractor，或把手机默认网关指向旁路由；部署正确后手机无需再连接 PC 热点，PC 也不必作为路由器。若用户没有可部署设备，仍只能使用 Windows 热点方案或另行评估高维护成本的手机 hook 方案。

## Implementation Notes

* `remote/extractor/package_extractor.py` 支持 `--relay-url`、`--api-token`、`--write-relay-config`、`--game-server-ip`、`--game-server-port`
* `remote/extractor/install_openwrt.sh` 和 `install_linux.sh` 支持环境变量免交互安装
* `remote/extractor/DEPLOY.md`、`README.md` 已更新普通 WiFi 模式步骤和物理拓扑约束
* `test_remote.py` 更新到当前 `data_source/sub_type` 契约，并修复 RelayAPI 缺依赖时的 skip 统计
