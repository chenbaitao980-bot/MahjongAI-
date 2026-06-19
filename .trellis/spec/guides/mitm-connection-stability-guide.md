# MITM 连接稳定性与排查方法论

> **Purpose**: noconfig 热更 MITM 场景下，确保手机稳定连 ECS、admin 稳定展示用户；并给出"间歇性连接失败"这类 bug 的标准排查链。
>
> 沉淀自 2026-06-19 排查：admin 间歇性不展示用户 / 手机"重进几次才连上 ECS"。任务 `06-19-noconfig-ecs-intermittent-routing`，commit `b9bf68c`。

---

## 一、铁律：连接稳定性（改 NetConf 时必须全部满足）

> 这些是**架构层硬约束**，违反任意一条都会导致手机偶发绕过 ECS、admin 丢用户。

### 铁律 1：改大厅/游服 ECS 指向，必须同时注入 `LOCAL_TCP_LIST_50[groupId]`

**为什么**：`NetEngine.getTcpConnectInfoByGroupId`（`apk_research/decrypted-lua/app/Net/NetEngine.lua:254`）选地址逻辑：

```lua
local list = XH.LOCAL_TCP_LIST[groupId] or {}        -- 静态配置(你改成纯ECS)
if XH.areaData:isSupportSRS50() then                  -- 所有区都是 true
    for k,v in pairs(XH.LOCAL_TCP_LIST_50) do
        if k == groupId then return list[1] end       -- ★ _50 命中 → 确定性返回,跳过随机
    end
end
self:getSRSConfigListFromFile(groupId, list)          -- ★ 读 srslist{groupId}.json 缓存,把真服条目追加进 list
-- ...
if len > 1 then return list[math.random(1, len)] end  -- ★ 在 [ECS,ECS,真服,真服,...] 里随机
```

`getSRSConfigListFromFile` 读手机本地 `srslist{groupId}.json`（游戏运行时从 `RespSRSAddr` 落地的**真服条目**）追加到候选池。所以**光把 `LOCAL_TCP_LIST[groupId]` 改成纯 ECS 不够**——运行时缓存会把真服重新混进来，`math.random` 有概率抽中真服 → 绕过 ECS tcp_proxy → admin 看不到该用户。

只有 `_50` 分支的 `return list[1]` 能在缓存混入**之前**短路。

**怎么做**：`netconf_patch.patch_netconf` 必须调用 `_inject_srs50_block` 注入 `LOCAL_TCP_LIST_50[groupId] = { {id=0, ip=ECS, port=...} }`。校验断言：`_50[groupId]` **必须存在且只含 ECS、不含真服**。

> ⚠️ 曾经的"降级形态"注释说"5045 走普通路径已是 ECS 单点，不需要注入 _50"——**这是错的**，实机已证伪。普通路径必被 srslist 污染。

### 铁律 2：NetConf 内容任何变化，必须 bump `setup_mitm` build 偏移

**为什么**：热更版本号是手机判断"要不要重下 NetConf"的唯一依据。手机本地 harbor 存了上次热更的版本，若下发版本 ≤ 本地版本 → `NOUPDATE` → **不重下，继续用旧 NetConf**。你改了 NetConf 内容但没 bump 版本，等于改了寂寞，旧手机永远跑旧逻辑。

**怎么做**：`setup_mitm.MitmAssets._VERSION_SEGMENT_OFFSETS` 的 build 段（第 4 段）每次改 NetConf 内容就 +1000。当前 +3000。历史：
- `+1000` 初始 Path Y
- `+2000` 回滚 ECS 单点
- `+3000` 注入 `_50[5045]` 修 srslist 随机

### 铁律 3：公网 ECS 上 DNS responder 必须绑 `0.0.0.0`

**为什么**：`setup_mitm` 的 `DnsResponder` 默认 `listen_host = self_ip`，这套代码原给本地热点 PC 用（绑热点网卡 192.168.137.1）。搬到 ECS 若用 `--dns-listen-host <内网IP>`，公网手机的 DNS 查询发到公网 IP:53 收不到响应 → 不拉热更 → NetConf 不改 → 不连 ECS。

**怎么做**：systemd unit 用 `--dns-listen-host 0.0.0.0`（`--host-ip` 仍填公网 IP，作为 DNS 应答返回的地址）。阿里云安全组放行 UDP:53 + TCP:443。

> 注：手机走 TCP 直连 ECS 大厅时**不依赖 DNS**（NetConf 已永久指向 ECS IP）。DNS 只在"首次热更"那一步需要。但绑 0.0.0.0 是公网部署的正确形态，留着无害。

### 铁律 4：诊断大厅连接问题，先用 tcp_proxy 字节计数日志区分 C→S / S→C

`tcp_proxy._pump` 已加诊断日志（commit `859d88e`）：每个方向首块到达 + 会话结束时无条件记录字节总数。复现时看：

| C→S 字节 | S→C 字节 | 结论 |
|----------|----------|------|
| 0 | 0 | 手机没发登录包 / 连接没建立 |
| >0 | 0 | **上游接受连接却不回包**（账号会话问题、上游拒绝） |
| >0 | >0 | 链路通，问题在 PlayerData 解析层 |

**永远先看这个，再猜上层。** 不要一上来就猜代码 bug。

### 铁律 5："代码已修复"必须实机复现验证，不信注释 / 不信 research 结论

`research/path-y-vs-ecs-only.md` 曾下结论"当前 HEAD 已无随机直连真服"，但未经实机验证就写进 PRD，导致排查方向跑偏半天。**诊断结论必须标"待实机验证"**；任何"应该已经解决了"的注释，排查时一律当未解决对待，直到实机坐实。

---

## 二、排查方法论：间歇性连接失败的标准链

> 当症状是"有时能连上、有时连不上"时，按此链排查，避免在错误层级打转。

### Step 0：先定义"连不上"的精确含义

"admin 不展示用户"是**结果**，不是**症状**。先拆成三种可能，别混为一谈：

1. 手机**根本没连 ECS 大厅**（tcp_proxy 无连接记录）
2. 手机连了 ECS 大厅但 **S→C 零字节**（上游不回）
3. 手机连了、有数据，但 **PlayerData 没解析出**（admin 无该用户）

三种根因完全不同。先用铁律 4 的字节计数日志归类。

### Step 1：对比法——找"成功"和"失败"两组样本

间歇性 bug 的最强武器是**同系统对比**。本次两台手机：一台每次都成、一台重进几次才成。对比它们的：
- 公网 IP / 运营商（4G vs WiFi）
- 大厅连接记录（连的哪个端口 5748/5749）
- PlayerData 解析是否成功

**差异点即线索。** 别只盯着失败的那台看。

### Step 2：核实"运行时"而非只看"静态配置"

静态配置改对了 ≠ 运行时一定走它。问三个问题：
1. 有没有**磁盘缓存**会在运行时把旧值重新引入？（本次：`srslist{groupId}.json`）
2. 有没有**随机选择**逻辑会在多个候选里摇骰子？（本次：`math.random`）
3. 有没有**短路分支**能在污染前确定性返回？（本次：`_50` 分支 `return list[1]`）

**读运行时源码**（`apk_research/decrypted-lua/`）找答案，别只看补丁脚本。

### Step 3：区分"客户端行为"和"服务端行为"

本次第二台手机曾在疯狂轮询 `:8002/api/player-status`（404）。这容易让人误判"手机在尝试连接"。要分清：
- **轮询 admin API** = 配套查看端/读牌端在跑，**不是游戏客户端进大厅**
- **连 5748/5749** = 游戏客户端真正进大厅

看 tcp_proxy 的 5748/5749 连接记录，才是"游戏客户端是否进大厅"的真凭据。

### Step 4：版本/缓存污染排查

确认修复部署后仍偶发，问：
- 手机本地 harbor 缓存的版本号是多少？是否 ≥ 下发版本（导致 NOUPDATE 不重下）？
- `srslist{groupId}.json` 缓存是否还含真服条目？
- 手机是否真的重新拉过热更？（看 hot-update MITM 日志有没有外部 IP 请求）

---

## 三、本次排查的教训（避免重蹈）

1. **第一直觉"新代码引入 bug"通常是错的**。先审 diff 判断新代码是否触及故障路径，再决定要不要往这方向查。本次 provisional 新代码完全无辜，差点浪费半天。
2. **research 结论要标"待实机验证"**。未经验证的结论写进 PRD 会误导后续排查。
3. **"DNS 绑内网"这类合理的修复即使不是根因也值得做**，但要明确标注"非根因，顺带修"，避免把次因当主因结案。
4. **服务器配置变更（如 systemd unit）必须固化到 git 或部署脚本**，否则下次部署回滚。本次 `--dns-listen-host 0.0.0.0` 改的是手工 unit，部署脚本只 restart 不重写，所以安全——但要记进记忆防遗忘。

---

## 四、相关文件

| 文件 | 作用 |
|------|------|
| `remote/noconfig/hijack/netconf_patch.py` | NetConf 解密/改写/重加密，铁律 1 的实现 |
| `remote/noconfig/hijack/setup_mitm.py` | 热更 MITM，铁律 2/3 的实现 |
| `remote/noconfig/hijack/tcp_proxy.py` | 大厅/游服代理，铁律 4 的诊断日志 |
| `apk_research/decrypted-lua/app/Net/NetEngine.lua` | 地址选取源码，铁律 1 的依据 |
| 记忆 `noconfig-srslist-random-pollution-fix` | 本次根因与修法 |
| 记忆 `ecs-mitm-dns-bind-public` | DNS 绑公网 |
