# 排查无配置模式偶发未连上 ECS

## Goal

确认当前无配置模式“有时候能连上 ECS、有时候连不上”的根因，重点判断是否存在手机偶发直连真服而绕过 ECS 的情况，并给出能够区分“旧补丁残留”与“当前代码仍会随机直连”的诊断结论。

## What I already know

- 用户现象：无配置模式有时可以连接到 ECS，有时连接不到；怀疑有时连到真服。
- 仓库中存在一个历史任务 [`06-17-ecs-failover-direct-fallback`](E:\claude\project\MahjongAI\MahjongAI\.trellis\tasks\06-17-ecs-failover-direct-fallback\prd.md)，其目标就是让 ECS 宕机时回落真服。
- 提交 [`c8cd0a2`](E:\claude\project\MahjongAI\MahjongAI/.git) 曾引入 Path Y：
  - `LOCAL_TCP_LIST[5045]` 保留真服并追加 ECS；
  - `LOCAL_TCP_LIST_50[5067/5167]` 改为 `[ECS, 真服]`；
  - 同时注入 `NetEngine.luac` 轮询/FAIL 自重连逻辑。
- 当前 HEAD 的 [`remote/noconfig/hijack/netconf_patch.py`](E:\claude\project\MahjongAI\MahjongAI\remote\noconfig\hijack\netconf_patch.py) 已写明 2026-06-19 “降级为 ECS-only”：
  - 5045 改为原地把真服 IP 替换成 ECS；
  - 5067/5167 也改为 ECS 单条；
  - 不再保留真服 fallback。
- 当前 HEAD 的 [`remote/noconfig/hijack/setup_mitm.py`](E:\claude\project\MahjongAI\MahjongAI\remote\noconfig\hijack\setup_mitm.py) 将热更版本 build 偏移从 `+1000` 提高到 `+2000`，注释明确说明这是为了让已经热更过旧 Path Y 版 NetConf 的手机强制重下；否则手机本地 `NOUPDATE`，会继续使用“真服+ECS 并存”的旧补丁，约 50% 概率抽中真服绕过 ECS tcp_proxy。
- 历史记忆也表明：
  - noconfig admin 在线态依赖 `/presence` / `/push` / tcp_proxy 路径；
  - 一旦手机绕开 ECS tcp_proxy，admin 就会看不到登录态/在线态。

## Assumptions (temporary)

- 用户描述的“有时连不上 ECS”大概率不是“当前 HEAD 代码还在随机”，而是“部分手机仍带着旧的 Path Y 热更产物，未成功重下 06-19 的 ECS-only 补丁”。
- 如果某台手机从未拿到 `+2000` 版本，或者 harbor 中仍缓存了旧 `+1000` 版本，就会继续表现为偶发直连真服。

## Open Questions

- 当前出现问题的手机，是否是 6 月 19 日之前已经成功跑过一次无配置热更、之后没有清理 harbor / 重装 / 强制重下补丁的老设备？

## Requirements (evolving)

- 明确当前仓库代码是否还存在“随机直连真服”的逻辑。
- 明确历史哪个版本引入了该行为，哪个版本又试图消除它。
- 明确“偶发”是代码随机选择导致，还是旧热更资产未刷新导致。
- 给出后续排查时应收集的最小证据（例如热更版本、手机是否重下 NetConf、admin 是否出现在线态）。

## Acceptance Criteria (evolving)

- [ ] 能指出具体提交/文件证明 Path Y 历史上确实会让一部分连接走真服。
- [ ] 能指出当前 HEAD 哪些修改试图消除这种随机性。
- [ ] 能给出一个可执行的判断：当前问题更像“旧补丁残留”还是“当前代码仍有分流 bug”。

## Definition of Done (team quality bar)

- 诊断基于代码和历史提交证据，而不是猜测。
- 关键证据写入本任务 PRD，后续实现或实机验证时可直接复用。

## Out of Scope (explicit)

- 本轮不直接修改 ECS 服务器代码或热更逻辑。
- 本轮不做实机抓包或远端服务重启，仅先完成代码层诊断。

## Technical Notes

- 关键文件：
  - `remote/noconfig/hijack/netconf_patch.py`
  - `remote/noconfig/hijack/setup_mitm.py`
  - `apk/_dump_NetEngine.lua`
  - `.trellis/tasks/06-17-ecs-failover-direct-fallback/prd.md`
- 关键提交：
  - `c8cd0a2 feat(noconfig): ECS failover Path Y — NetConf+NetEngine 双注入兜底`
  - `a8b8b2e 稳定版本`

---

## 2026-06-19 实机复现结论（推翻"旧补丁残留"假设）

### 实机证据

两台手机都热更过、都连过 ECS（不是旧 Path Y 直连真服）：

- 第一台 `223.104.166.43` → 13:30 连 5748 成功，用户 `LOLLAPALOOZA` 上线。
- 第二台 `39.184.31.145` → 13:05 连 5748（S->C 零字节，2 分钟断）、13:39 连 5749 成功，用户 `北方` 上线。**"重进好几次才出现"**。

两台手机拿到的 NetConf 都是当前 HEAD 的 ECS-only 补丁（`LOCAL_TCP_LIST[5045]` 纯 ECS 5748/5749），不是旧 Path Y。所以随机性**不在"选 ECS vs 真服"**——而在 ECS 这条路本身的连接稳定性 + srslist 缓存污染。

### 精确根因（代码坐实）

`apk_research/decrypted-lua/app/Net/NetEngine.lua:254` `getTcpConnectInfoByGroupId(groupId)`：

```lua
local list = XH.LOCAL_TCP_LIST[groupId] or {}          -- 已是纯 ECS [5748,5749]
if XH.areaData:isSupportSRS50() then                    -- 所有区 true
    for k,v in pairs(XH.LOCAL_TCP_LIST_50) do
        if k == groupId then return list[1] end         -- _50 命中 → 确定性返回，跳过随机
    end
end
self:getSRSConfigListFromFile(groupId, list)            -- ★ 读 srslist{groupId}.json 追加到 list 末尾(真服条目!)
-- ...
if len > 1 then return list[math.random(1, len)] end    -- ★ 在 [ECS,ECS,真服,真服,...] 里随机
```

`getSRSConfigListFromFile`（:292）读手机本地 `srslist{5045}.json` 缓存（游戏运行时从 RespSRSAddr 落地的真服条目），**追加到 list 末尾**。于是 `list = [ECS:5748, ECS:5749, 真服:5748, 真服:5749, ...]`，`math.random` 有概率抽中真服 → 绕过 ECS → admin 看不到。

**当前 HEAD 的 `patch_netconf` 故意不注入 `LOCAL_TCP_LIST_50[5045]`**（注释"5045 走普通路径已是 ECS 单点"）——这个判断错了：普通路径会被 `getSRSConfigListFromFile` 污染，5045 不在 `_50` 表里所以 `_50` 分支不命中，落回随机。

### 修法（确定）

恢复 `_inject_srs50_block`：往 `LOCAL_TCP_LIST_50[5045]` 注入 `{id=0, ip=ECS, port=5748/5749}`。这样 `_50` 分支命中 `return list[1]`，**确定性返回 ECS、跳过 srslist 混入和 math.random**。

- 只改 `remote/noconfig/hijack/netconf_patch.py`：在 `patch_netconf` 里恢复调用 `_inject_srs50_block`，并调整 `patch_netconf` 末尾的校验（当前校验"5045 不应在 _50 表"需反转为"5045 必须在 _50 表且只含 ECS"）。
- 不动 NetEngine（setup_mitm 当前不注入 NetEngine，靠 NetEngine 原生 `_50` 分支即可）。
- 必须 bump build 偏移（setup_mitm `_VERSION_SEGMENT_OFFSETS` 的 build 段 +N），否则已热更手机本地 NOUPDATE、不会重下新 NetConf。

### Acceptance（更新）

- [ ] `patch_netconf` 注入 `LOCAL_TCP_LIST_50[5045]=ECS`，校验反转。
- [ ] 往返校验通过；`netconf_patch` CLI 自测通过。
- [ ] setup_mitm build 偏移 bump，使旧手机强制重下。
- [ ] 部署后实机：第二台手机连续进大厅多次，每次都连 ECS（tcp_proxy 每次都有 5748/5749 连接记录 + presence 上报），不再"重进几次才中"。
