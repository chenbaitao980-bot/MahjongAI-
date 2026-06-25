# ECS 同步官方资源 + NetConf 覆盖固定不变

## Goal

让被注入的手机在**任意网络（含 4G）**都能自动收到官方热更内容，同时 NetConf 覆盖层（指向 ECS 读牌）保持固定不变、客户端永久只认 ECS。消除当前"假高版本号 + DNS 劫持只在热点生效 → 离开热点后手机被冻结在注入快照、收不到官方更新"的局限。

## What I already know（代码坐实）

- **当前 setup_mitm 已做回源透传**（`remote/noconfig/hijack/setup_mitm.py`）：
  - version.manifest / project.manifest 都**回源线上当前真实版本**做底，只改 NetConf 一条 md5，版本号按"真实线上版每段 +缓冲(1,5,9,3000)"顶高（`_served_version`，4 段缓冲支配，自调节）。
  - 非 NetConf 文件 `_handle_origin_passthrough` 透明回源真实 CDN。
  - ∴ **只要请求打到 MITM，官方内容已自动透传**；版本号永远略高于"当前官方"，官方推 C 时 served=bump(C) > harbor=bump(B) → 自动触发增量下载 C 的新文件，NetConf 因 md5 不变不重下（覆盖天然固定）。
- **冻结只发生在 4G**：NetConf 只改 `LOCAL_TCP_LIST`（游戏服→ECS），**不改热更地址**；热更 `update_url` 来自 manifest 自身。4G 下 gxb-api 域名走运营商 DNS→官方，harbor 版本被顶高→`versionLessThan=false`→NOUPDATE→冻结。
- **永久重定向机制坐实**（`HotFixProcessor.lua`）：
  - `:start()` L128 更新检查地址 = `self._localManifest:getUpdateUrl()` = manifest 的 `update_url` 字段（`Manifest.lua:85`）。
  - `:_updateLocalManifest()` 热更完成后 `localManifest:setJson(projectManifest:getJson())` **整体替换**——下发 manifest 里的 `update_url` 会落进 harbor localManifest。
  - ∴ **在下发 project.manifest 里写 `update_url = https://<ECS_IP>/hotfix_update`，一次热更后手机 harbor 永久把更新检查指向 ECS（IP 直连，任意网络无需 DNS）。**
- **ECS 能回源官方**：setup_mitm 用固定公共 DNS `119.29.29.29` 解析真实 CDN（`_resolve_real_ip`），ECS 出网可达。
- 现有部署姿态：5045/5067/5167 全 ECS 单点（记忆 ecs-failover-path-y）；ECS MITM DNS 须绑 0.0.0.0（记忆 ecs-mitm-dns-bind-public）。

## Core Insight（一句话）

不需要"定期拉取 + 合并 harbor 底层"那么重——把 **update_url 永久改写到 ECS** + ECS 常驻跑现有的**按需回源透传 MITM**，就实现"官方内容自动 + NetConf 固定 + 只认 ECS"。定期预取 mirror 只是可选的抗风险增强层。

## Open Questions

- [ ] **核心方向**：按需回源透传（Approach A，轻）还是定期预取 mirror（Approach B，重）还是 A+B？
- [ ] update_url 改写后 ECS 成为唯一更新入口，ECS 宕机时更新检查失败（不影响已 harbor 内容、游戏照常跑）——可接受？是否要保留官方兜底？
- [ ] 检测面：所有手机更新检查经 ECS 单 IP 回源官方，是否在意指纹聚集？

## Requirements (evolving)

- R1: 在下发 project.manifest（`patch_real_project_manifest`）里写入 `update_url = https://<ECS_IP>/hotfix_update`，使 harbor 永久指向 ECS。
- R2: ECS 常驻 MITM 服务（非设置期一次性）：稳定回源官方 + 改写 NetConf md5 + 顶高版本（已具备，需固化为长跑服务 + systemd）。
- R3: 官方推更高版本时，4G 手机经 ECS 自动增量下载官方新文件；NetConf 覆盖不被冲掉（md5 不变）。
- R4: 离线/单元可测：update_url 改写、版本支配关系、NetConf 不重下、official-bump 触发关系。

## Acceptance Criteria (evolving)

- [ ] 下发的 project.manifest 含 `update_url` 指向 ECS_IP，且 `_updateLocalManifest` 语义下会落进 harbor（离线断言 + 逆向佐证）。
- [ ] 给定 harbor=bump(旧官方)、official=新版本 C，ECS 计算 served=bump(C) 且 `versionLessThan(harbor, served)=true`（触发更新）；official 未变时 served==harbor（NOUPDATE，不空跑）。
- [ ] NetConf 条目 md5 在两次官方版本间保持不变（手机不重下 NetConf）。
- [ ] ECS 服务长跑稳定（systemd / 自启），DNS 绑 0.0.0.0，安全组放行 443/53。

## Definition of Done

- 离线/单元测试覆盖 update_url 改写 + 版本支配 + NetConf 幂等。
- 不破坏现有 5045/5067/5167 ECS 单点读牌链路（detect_changes 核对）。
- 部署文档：ECS 常驻服务起停 + 安全组 + 版本缓冲调整。
- 真机验证项清单（4G 下离开热点仍能收官方增量 + 读牌不断）。

## Out of Scope (explicit)

- 不改手机、不装 app、不改手机 DNS（noconfig 铁律）。
- 不做官方资源的本地全量镜像存储，除非选 Approach B。

## Technical Approach（待定方向）

**Approach A — 永久 ECS 更新端点 + 按需回源透传（推荐）**
- 改 `patch_real_project_manifest`：注入 `update_url`=ECS。
- `setup_mitm` 固化为 ECS 常驻服务（已有回源逻辑，补 systemd + 稳定性）。
- 官方内容按请求实时回源；NetConf 覆盖每次重贴（md5 恒定）。
- 优点：改动最小、无存储、4G 永久生效、版本支配自调节已现成。
- 缺点：每次更新检查实时回源官方（延迟/官方波动敏感）；ECS 单 IP 回源指纹聚集；ECS 宕则更新检查失败（游戏仍可玩）。

**Approach B — ECS 定期预取 mirror（可选增强）**
- cron 拉官方 manifest+资源 → ECS 本地 harbor 镜像，贴 NetConf 覆盖，重算版本缓冲，serve from disk。
- 优点：抗官方封 ECS 出网 IP、低延迟、官方宕时仍可服务。
- 缺点：全量镜像存储；脏 harbor 增量合并黑屏坑（记忆 hotupdate-blackscreen-skip-cleanres）；需处理多 appid/channel manifest；复杂度高。

> A 是达成"只认 ECS + NetConf 固定 + 自动官方"的**必需机制**；B 是 ECS 侧抗风险层，可后置。

## Decision (ADR-lite)

**Context**: 需在不改手机的前提下，让 4G 手机也能自动收官方更新 + NetConf 覆盖固定 + 只认 ECS。
**Decision**: 选 **Approach A**——`update_url` 永久改写到 ECS + ECS 常驻按需回源透传。**B（定期预取 mirror）后置**为可选抗风险增强。
**关键澄清**: A 路径**无定时任务**；官方内容更新由手机每次更新检查被动触发（通常每次启动游戏一次），ECS 实时回源官方，不主动定时拉取。
**Consequences**: 改动最小、4G 永久生效；但每次更新实时回源官方（延迟/官方波动敏感）、ECS 单 IP 回源指纹聚集、ECS 宕则更新检查失败（harbor 已有内容仍可玩）。

## 实施切片（按用户测试节奏）

- **PR1（当前）— 可观测性日志**：不加 update_url 改写，先给现有 origin-passthrough + NetConf serve 路径加结构化日志，让真机测试能读出：①官方版本 X→下发支配版本 Y②每个官方文件透传事件③NetConf md5=Z(恒定，证明重贴未变)。验证"现有静态/回源版能否更新官方内容 + NetConf 正常重贴"。
- **PR2 — update_url 改写**：`patch_real_project_manifest` 注入 `update_url`=ECS，实现 4G 永久指向 ECS。
- **PR3 — ECS 常驻服务固化** + 部署文档 + 真机验证清单。

## Spec Conflicts

- 已扫描 `.trellis/spec/backend/remote-access.md`：覆盖 VPN/relay/热点机制，**无**"假高版本必须永久支配 / 不得改 update_url"类硬规则。**无冲突**。

## 最终方案（锁版 2026-06-25，Approach A + file_url=official）

### 决策汇总
- ECS 视为高可用，**不做宕机兜底**（update_url 改写后 ECS 为唯一更新入口）。
- **只改一个业务文件** `remote/noconfig/hijack/setup_mitm.py`（它被 PC 热点设置 run_hijack 与 ECS 常驻服务**共用**，一处改动两个角色都生效——这正是需要的）。不碰 `apps/router_runtime/` 那份、不碰 `manifest_forge.py`/`netconf_patch.py`。
- **file_url 保持官方（A）**：控制面（version/project.manifest + NetConf）走 ECS；官方文件字节 4G 下直连官方 CDN。NetConf 因 md5 恒定永不被请求，覆盖绝对安全；ECS 零文件带宽。

### 关键纠正（为何"只改 update_url"不够）
4G 无 DNS 劫持，manifest 里任何官方域名都解析到真官方。若只改 update_url、不改 manifest_url：
4G→ECS 取 version.manifest→manifest_url 仍官方→手机从真官方取 project.manifest（官方 NetConf md5≠harbor）→重下官方 NetConf→**覆盖被冲掉**。
∴ 必须改写**整条链**：`update_url`(project.manifest)→ECS + `manifest_url`(version.manifest)→ECS + ECS 两个 handler 回源改用**硬编码官方 host**（4G 下进来的 Host=ECS IP，不能再靠 Host 头判断回源目标）。

### 改动范围（全在 setup_mitm.py + 其测试）
| # | 位置 | 改动 |
|---|---|---|
| 1 | 顶部常量 | 新增 `OFFICIAL_UPDATE_HOSTS`（gxb-api[-tx].imeete/hzxuanming）、`OFFICIAL_MANIFEST_HOST`、ECS 回写基址；`--file-url-mode {official,ecs}` 默认 official |
| 2 | `patch_real_version_manifest` | `manifest_url` 由"保留官方"改为"→ `https://<ECS_IP>/<project_path>`"；继续捕获官方真实 manifest host/path 供回源 |
| 3 | `patch_real_project_manifest` | 新增：`update_url` → `https://<ECS_IP>/hotfix_update?<原query>`（host 换 ECS、保留 appid/engine_ver/channel/version）；NetConf md5 改写不变；file_url 视 mode |
| 4 | `_handle_version_manifest` | 回源官方 version.manifest 改用硬编码官方 update host（不依赖 Host 头），query 透传 |
| 5 | `_handle_project_manifest` | 回源官方 project.manifest 改用捕获的官方 manifest host/path（不依赖 Host 头）|
| 6 | `_handle_origin_passthrough` | 仅 `--file-url-mode ecs`（验收用）时回源改硬编码官方 file host；official 模式不变 |
| 7 | `tests/test_setup_mitm.py` | 更新 manifest_url 断言（→ECS）+ 新增 update_url 改写断言 + file-url-mode 两态 |

### 日志设计（默认 INFO，低频，tag 可 grep；不改业务行为）
低频（每次更新检查 1~2 行，非每文件）：
- `[CHAIN-VER] client=<ip> real_online=<X> served=<Y> manifest_url→ECS=<url>` — version.manifest 服务时
- `[CHAIN-PROJ] client=<ip> real_online=<X> served=<Y> netconf_md5=<Z>(const) update_url→ECS=<url> file_count=<N>` — project.manifest 服务时
高频（仅 `--file-url-mode ecs` 验收模式存在）：
- `[OFFICIAL-FILE] client=<ip> <name> <bytes>` — 每个官方文件经 ECS 透传
- `[REINJECT] client=<ip> NetConf.luac re-served md5=<Z>` — 仅当 NetConf 真被请求（正常不应出现在官方更新流程，出现=覆盖被误重下，反向告警）

### 测试流程（真机，三场景）
> 部署前置：ECS 跑改后服务（systemd），安全组放 443/53/8002，DNS 绑 0.0.0.0。验收建议先用 `--file-url-mode ecs` 跑通三场景（日志全可见），再切回 `official` 生产。

- **场景1｜连热点注入**：PC 开热点跑 run_hijack（同一改后文件）→ 手机连热点开游戏 → 完成热更。
- **场景2｜切其他网络不受影响**：手机断热点切 4G → 进游戏正常对局、后台 ECS:8002 能读牌；再次进游戏触发一次更新检查（官方未变）。
- **场景3｜其他网络遇官方更新**：构造"官方已更新"（真等官方推，或测试期临时降低 ECS 顶高缓冲使 served>harbor 触发一次增量）→ 4G 进游戏 → 官方新内容下载完成、对局/读牌正常、NetConf 未被重下。

### 验收流程（你给我 ECS MITM 日志，我逐条核对）
| 场景 | 我在日志里要看到（生效判据） | 不该看到（失败信号）|
|---|---|---|
| 1 | `[CHAIN-VER]` + `[CHAIN-PROJ]` 各 1，且 `update_url→ECS`、`manifest_url→ECS`、`netconf_md5=Z`；ecs 模式下 1 行 `[REINJECT]`（首次注入正常）| project/version patch failed、502、static fallback |
| 2 | 来自**4G 公网 IP**(非热点网段) 的 `[CHAIN-*]`（证明 update_url→ECS 永久生效）；`real_online==上次`→手机端 NOUPDATE | 无任何 4G IP 命中（说明没指向 ECS，永久重定向没写进 harbor）|
| 3 | `[CHAIN-PROJ] real_online=<新C> served=bump(C)>上次`、`file_count` 变化、`netconf_md5=Z`**不变**；ecs 模式下一批 `[OFFICIAL-FILE]` 且**无** `[REINJECT]`（NetConf 没进 diff）| 出现 `[REINJECT]`（NetConf 被重下=覆盖危险）、netconf_md5 变化 |

> 读牌链路（tcp_proxy/ECS:8002）独立于热更，三场景全程应保持可读牌（admin 有登录态）——这是"NetConf 不受影响"的端到端佐证。

## Open Questions（已全部收敛）
- ~~核心方向 A/B~~ → **A（按需回源透传 + 全链路 update_url/manifest_url→ECS）**
- ~~ECS 宕机兜底~~ → **不做兜底，假设高可用**
- ~~file_url 官方 vs ECS~~ → **official（验收临时用 ecs 看日志）**
- ~~改两份 setup_mitm~~ → **只改 remote/noconfig/hijack 那份**

## Technical Notes

- 关键文件：`remote/noconfig/hijack/setup_mitm.py`（回源/patch/版本）、`manifest_forge.py`、`netconf_patch.py`。
- 逆向佐证：`apk_research/decrypted-lua/app/hotupdate/universe/hotfix/HotFixProcessor.lua`（L128 getUpdateUrl / `_updateLocalManifest` setJson 整体替换）、`Manifest.lua:85-90`（getUpdateUrl/setUpdateUrl 读写 `update_url`）。
- 相关记忆：hotupdate-mitm-netconf-overlay、hotupdate-4g-stall-fake-version、noconfig-srslist-random-pollution-fix、ecs-failover-path-y、ecs-mitm-dns-bind-public、hotupdate-blackscreen-skip-cleanres。
