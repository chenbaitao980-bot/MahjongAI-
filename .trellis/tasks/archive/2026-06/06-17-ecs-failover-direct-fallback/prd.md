# ECS 故障兜底：让用户在 ECS 挂掉时仍能直连真服

## Goal

当前 noconfig 链路把手机硬钉死在 ECS（`8.136.37.136`）：
NetConf.luac 改写让大厅 5045（5748/5749）+ 金币游服 _50 表（5067/5167）
全部指向 ECS。**ECS 整机宕机时，手机即便走 4G 或别家 WiFi 也开不了游戏**——
因为注入是写在手机 harbor 里的，永久生效，跟当前网络无关。

目标：**ECS 挂掉时，用户走任何网络（4G/陌生 WiFi）打开游戏仍能正常玩所有玩法**；
ECS 恢复时，下一次连接自动回到 ECS。**全玩法不受影响**——
含大厅、好友局、大众场、**金币局**。

## What I already know

- 当前注入两个独立点：
  - `LOCAL_TCP_LIST[5045]` 大厅：47.96.101.155:5748/5749 → 8.136.37.136:5748/5749
  - `LOCAL_TCP_LIST_50[5067/5167]` 金币游服：真服 → ECS:5767/5768
  - `LOCAL_TCP_LIST_50[5045]` 注入：把 5045 钉死成 list[1]=ECS
- `NetEngine.lua::getTcpConnectInfoByGroupId`（已 dump 验证 [`apk/_dump_NetEngine.lua:254`](apk/_dump_NetEngine.lua)）：
  - **_50 路径直接 `return list[1]`**——列表里塞多个 IP 没用，永远第一个
  - 普通路径合并 srslist 缓存后 `random(1, len)`——单次随机，不是顺序 fallback
  - **完全没有 connect-fail 重试代码**；失败要靠上层 UI 触发 `sendProtoBuf` 再次进入此函数
- `NetConf.luac` 与 `NetEngine.luac` 同一加密格式（SIGN=`devaguopeifei` + XXTEA(KEY=`03f1fdcbf5215b45`)），
  我们已能解密+改写+回包（[`netconf_patch.py`](remote/noconfig/hijack/netconf_patch.py)）
- `manifest_forge.py` 当前只塞一条 NetConf 文件；可以扩展成多文件下发
- 内存 [[srs-key-cracked]] [[hotupdate-mitm-netconf-overlay]] [[noconfig-multiuser-deployed]] 已记录
  ECS 部署形态、HTTP/443 MITM、systemd 单点

## Requirements

1. **NetConf.luac 改写策略调整**（保留真服 + 追加 ECS）：
   - `LOCAL_TCP_LIST[5045]`：原 47.96.101.155:5748/5749 **保留**，**追加** ECS:5748/5749
   - `LOCAL_TCP_LIST_50[5045]`：**删除**对此条的注入（不再钉死）
   - `LOCAL_TCP_LIST_50[5067/5167]`：列表改成 [ECS_entry, 真服 entry] 两项
2. **NetEngine.luac patch**（同一 XXTEA 流程，新增改写）：
   - `getTcpConnectInfoByGroupId` 中 _50 分支 `return list[1]` 改成
     "按全局 connect-fail 计数器轮询：`return list[(_failCount % #list) + 1]`"
   - 普通路径不动（已经有 random）
   - 注入一个全局计数器变量；在 TcpConnection 的 link-state-FAIL 回调里 +1
   - 同时把 `LINK_STATE_FAIL` 触发的"上层重连"补一次自动 startTcp 调用，
     让失败后不依赖 UI 也能切换到下一个 IP
3. **manifest_forge.py 扩展**：支持多文件下发
   （NetConf.luac + NetEngine.luac），保持 manifest md5 / size / name 字段一致
4. **ECS 服务一键停/启 bat**：
   - `stop_ecs_services.bat` —— SSH 到 ECS 一键
     `systemctl stop mahjong-mitm-hotupdate mjx mjx-vpn noconfig-multi`
     （只停进程，不关机；可逆，断电恢复成本高）
   - `start_ecs_services.bat` —— 配套启动
   - 用于验证兜底是否生效；输出 ECS 关键端口连通性自检
5. **回归验证**：
   - 真机：手机做一次正常热更（注入新 luac），登录确认正常运行（ECS 在线）
   - 真机：跑 `stop_ecs_services.bat` 关掉 ECS 服务后，手机切 4G 重启游戏，
     验证大厅/好友局/金币局**全部能进**（一次重连内）
   - 真机：跑 `start_ecs_services.bat` 后再次重启游戏，验证回到 ECS（relay 能抓牌）

## Acceptance Criteria

**[REVISED 2026-06-18]** 见下方 Postmortem 节。下面 5045 双 IP 那条已废弃，改为 5045 ECS 单点 in-place 改写。其他条目仅作历史记录。

- [ ] `netconf_patch.py` 改写后，往返自测里 5045 列表含 [真服+ECS] 两条
- [ ] `_inject_srs50_block`(5045) 已删除，验证生成的 NetConf 里 `LOCAL_TCP_LIST_50[5045]` 不存在
- [ ] `_50[5067/5167]` 列表含 [ECS, 真服] 两项
- [ ] `netengine_patch.py`（新模块）能解→改→回 NetEngine.luac，单测覆盖：
  - 注入了全局 `_srsConnFailCount` 变量
  - `_50` 分支 `return list[1]` 已替换成轮询表达式
  - 在 link-state FAIL 回调里 `_srsConnFailCount = _srsConnFailCount + 1` 注入
- [ ] `manifest_forge.forge_manifest_full` 接受多文件参数，
  返回 manifest 的 file_list 同时含 NetConf 与 NetEngine 两条 md5/size 正确
- [ ] `setup_mitm` HTTP 路由能同时返回两个 luac 字节
- [ ] `stop_ecs_services.bat` 双击执行后输出"ECS 服务已停"且 8.136.37.136:443/8002 不可达
- [ ] `start_ecs_services.bat` 执行后端口恢复
- [ ] 真机验证：ECS 关停状态下，4G 网络打开游戏能进大厅、好友局、金币局
- [ ] 真机验证：ECS 恢复后，relay 能再次抓到牌局数据

## Definition of Done

- 单元测试覆盖 NetConf/NetEngine 解密-改写-加密往返
- 离线自测：dump 注入后的两个 luac，文本比对预期改动点
- 真机回归：上述四条真机用例全部通过；记录到
  [`regression-tests/cases/ecs-failover-direct-fallback.md`](regression-tests/cases/ecs-failover-direct-fallback.md)
- spec 同步：把"NetConf+NetEngine 双注入兜底"作为 noconfig 默认形态写入
  [`.trellis/spec/backend/remote-access.md`](.trellis/spec/backend/remote-access.md)
- 内存条目：新增 ecs-failover-y / 修订 hotupdate-mitm-netconf-overlay

## Technical Approach

### 改写流水线（设置期，离线）
```
APK
  ├─ NetConf.luac    → netconf_patch.patch_netconf()    [保留真服+追加 ECS]
  └─ NetEngine.luac  → netengine_patch.patch_netengine() [_50 轮询 + fail 计数]
        ↓
  manifest_forge.forge_manifest_full(files=[NetConf, NetEngine])
        ↓
  setup_mitm 投递（443 HTTP）
```

### NetEngine.luac 注入点（伪代码 diff）
```diff
+ XH._srsConnFailCount = XH._srsConnFailCount or 0   -- 文件顶部追加

  function NetEngine:getTcpConnectInfoByGroupId(groupId)
      local list = XH.LOCAL_TCP_LIST[groupId] or {}
      if XH.areaData:isSupportSRS50() then
          for k,v in pairs(XH.LOCAL_TCP_LIST_50) do
              if k == groupId then
                  list = XH.LOCAL_TCP_LIST_50[groupId]
                  if list and #list > 0 then
-                     return list[1]
+                     return list[(XH._srsConnFailCount % #list) + 1]
                  end
              end
          end
      end
      ...
  end
```
+ 在每个 connect 调用点的 link-state 回调里加 FAIL 分支自增 + 自动重发 startTcp。

### bat 关闭服务（SSH 远程 systemctl）
- 用 PuTTY plink.exe（已部署机器上常见）或 ssh 直接 invoke
- 关闭目标：`mahjong-mitm-hotupdate.service` `mjx-vpn.service`
  `noconfig-multi.service`（确认服务名，下面 jsonl 已挂参考文档）

## Decision (ADR-lite)

**Context**: ECS 单点故障当前会让所有 noconfig 用户全玩法卡死，与"用户在外面也能玩"的产品承诺冲突。

**Decision**: 选 **Path Y**——同时改 NetConf.luac（保留真服 IP）和 NetEngine.luac
（注入 fail-count 轮询），让客户端在 ECS 不可达时**自身**逐步切换到真服。
拒绝 Path X（金币局救不回）和 Path Z（DNS 切换有黑屏期且需买域名）。

**Consequences**:
- 优点：所有玩法兜底；不依赖 PC 在场；不依赖网络环境；一次注入永久生效
- 风险：改 client Lua 比改配置激进；游戏官方一旦覆盖热更我们要重追
- 工作量：~1.5 天（含真机回归）

## Spec Conflicts

无。`.trellis/spec/backend/remote-access.md` 不含 ECS 故障兜底既有规则；
本任务结束后向其追加规则。

## Out of Scope

- 不做 PC 端探针 / 自动回滚（用户离开 PC 时无效，违反需求）
- 不做 DNS 切换方案（黑屏期 + 域名采购）
- 不重构 ECS 多副本部署（成本超本任务范围；机器级 HA 是另一议题）
- 不动 vpn / hotspot 模式（这两个本来就要求 ECS 在线，不需要兜底）

## Research References

- [`apk/_dump_NetEngine.lua`](apk/_dump_NetEngine.lua) —— 解密后 Lua 源码，
  锁定 `getTcpConnectInfoByGroupId` 行为
- [`apk/_dump_NetConf.lua`](apk/_dump_NetConf.lua) —— 5045/5067/5167 表当前内容
- 内存 [[hotupdate-mitm-netconf-overlay]] —— 热更注入唯一咽喉的逆向证据
- 内存 [[hotupdate-4g-stall-fake-version]] —— 版本号必须 4 段、99.99.99.9999 兜底

## Technical Notes

- XXTEA inc 标记：NetConf 用 `inc=False`（密文长 == 明文长），
  NetEngine 用 `inc=True`（明文末尾带 4 字节长度尾），
  `unwrap_luac/wrap_luac` 已正确处理两者
- ECS 关停后端口语义：systemd stop → connect refused（不是 SYN 黑洞），
  客户端能立刻拿到失败回调，触发 `_srsConnFailCount` 自增
- bat 文件硬性纪律：[[feedback_bat_ascii_only]]——纯 ASCII，禁中文/画线符号
- 服务器只读纪律：[[server-readonly-git-sync-discipline]]——
  bat 只 stop/start，不改 ECS 上代码

## Postmortem (2026-06-18)

**结论**：方案 Y（5045 双 IP + NetEngine 轮询）真机验证失败，回滚到"5045 ECS 单点 + NetEngine 轮询补丁 + _50 双 IP"。产品承诺"ECS 整机宕机时用户全玩法可玩"**降级**——不再保证。

### 根因

5045 大厅列表保留真服 + 追加 ECS 后是 4 项 [真服, 真服, ECS, ECS]。NetEngine 普通路径走 `math.random(1, len)` **单次随机选**——不是顺序 fallback。

- ~50% 几率随机抽到真服 IP → 手机直连真服 7777
- 完全绕过 ECS 上 `mahjong-tcp-proxy` 的 RespSRSAddr 改写链路
- relay 抓不到任何 0x2bc0 帧
- 用户视角"抓牌时灵时不灵"

### 矛盾

抓牌（relay 抓 RespSRSAddr/0x2bc0）依赖 ECS 全程在线做改写 + 旁路；与"ECS 整机宕机时手机走真服能玩"在产品层**互斥**。本项目选**抓牌**，回到"ECS 高可用是前提"的传统形态。

### 回滚后的形态

- **NetConf.luac**：5045 大厅 **in-place 改写为 ECS 单点**（不再保留真服）；`_50[5067/5167]` 仍 `[ECS, 真服]` 两项；不注入 `_50[5045]`
- **NetEngine.luac**：fail-count 轮询补丁保留——配合 _50 双 IP 仍是 **ECS 内部金币游服代理瞬时故障**兜底（不再是 ECS 整机宕机兜底）
- **bat 工具** `stop_ecs_services.bat` / `start_ecs_services.bat`：保留作运维/调试杠杆（验证 ECS 关停时游戏会挂——这是预期行为），不再是"兜底验证"

### 不变

- NetEngine.luac patch 不删（仍有用，作 ECS 内部代理瞬时故障兜底）
- stop/start_ecs_services.bat 不删（运维仍需要）
- 不动 ECS 上代码（[[server-readonly-git-sync-discipline]]）

### 验证

- `python -m remote.noconfig.hijack.netconf_patch --selftest` ✅
- `python -m pytest tests/test_netengine_patch.py tests/test_setup_mitm.py -v` ✅ 15/15

### Spec 同步

- [`.trellis/spec/backend/remote-access.md §17`](.trellis/spec/backend/remote-access.md) 整节重写为"noconfig 部署纪律：ECS 高可用前提"
- §18.4/§18.6 更新约束：5045 大厅必须 in-place 单点；_50 表保留真服仅作内部端口故障兜底
- 内存 [[ecs-failover-path-y]] 标题/内容降级，标注 2026-06-18
