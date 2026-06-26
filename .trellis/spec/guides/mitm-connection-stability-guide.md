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

### 铁律 6：监督/保护/恢复机制本身必须有"故障注入测试"

> 2026-06-26 4G 校验卡回归真因(第二次 4G/MITM 回归)。脚本 [`scripts/mahjong-mitm-watchdog.sh`](../../scripts/mahjong-mitm-watchdog.sh) 装上 3 小时就因 counter reset bug 永远卡 1，到不了 FAIL_THRESHOLD=3 永不 restart。`06-26-mitm-stability-check` PRD 风险段**识别了**"watchdog 自身可能 bug 死循环"但**没加测试**——24 个 setup_mitm 测试全测被监督者，0 个测试监督者。

**为什么**：监督/保护/恢复机制(进程看门狗/重试/熔断/限流/降级)的失败模式跟普通业务代码不一样——它失败时**正是它该救的场景**。业务代码失败通常返回 500/404，可观察；监督代码失败时系统**表现完全正常**(表面看一切好)但其实救不了。**没有故障注入测试 = 监督代码等于没装**。

**怎么做**：
- **故障注入测试必须存在**：能造一个"被监督者真坏"的场景(进程死/端口挂/handler 死但主线程活)，跑监督者，看它**真触发恢复动作**(systemctl restart / 切流量 / 报警)
- **测试覆盖三类故障**：
  1. 进程崩溃（systemd is-active=false）—— 最简单
  2. 端口不再监听(socket closed)
  3. **进程活但不响应**（主线程活 / handler 死 / CPU 0%）—— **这才是 watchdog 想抓的，测试必含**
- **PRD 的 Acceptance Criteria 必须有"故障注入测试通过"这条**，不能只有"安装确认"(文件存在/服务 active/Restart=always)
- 测试不能放生产上跑(自己恢复的副作用大)，要本地化：被监督者用 `nc -l` 假端口 / 假服务进程 / SIGSTOP 暂停主线程 等手段

> 警惕写法：PRD 写"watchdog 部署到 ECS"/"watchdog 自身崩溃能自启"——这只是**安装确认**，不是**功能确认**。后者必须有"真故障 → 真恢复"端到端测试。

**新增被监督服务的 checklist**：
- [ ] `WATCH_SERVICES` 数组是否包含新服务？
- [ ] 新服务是否有独立的 health probe endpoint？
- [ ] `CO_RESTART_PAIR` 或独立 counter 逻辑是否覆盖新服务？
- [ ] 故障注入测试是否包含新服务的"进程活但不响应"场景？

> 本次 relay-noconfig 被遗漏：新加了服务但 watchdog 只监督 `/healthz`，`/mode` 失败时 counter 永不累加 relay-noconfig，永远到不了 threshold。

### 铁律 7：Counter 类自愈逻辑的 reset 条件必须严于 trigger 条件

> 紧接铁律 6，watchdog counter 永远卡 1 的具体根因。

**为什么**：counter 累加机制(reset vs trigger)如果 reset 路径**比 trigger 路径更宽松**，就等于"无 reset 永不升级"或"trigger 一次 reset 一次"两种死循环。本次 bug 形态：

```bash
# 错误写法(实际发生 bug 的代码)
for svc in "${WATCH_SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        restart_service "$svc"     # 死 → 救 + reset
    else
        set_counter "$svc" 0       # ★ active → 立即 reset(!!)
    fi
done
fails=$(probe_all_health)        # 然后才真探测
if (( fails == 0 )); then continue
for svc in "${CO_RESTART_PAIR[@]}"; do
    cnt=$((cnt + 1))             # 只累加一次 → 1
done
```

`is-active` 看主线程活就 reset(对 hotupdate 来说总是 true,因为 setup_mitm 用 `threading.Event().wait()` 主线程不退出)→ /healthz 失败时只把 counter 0→1 → 下一轮又 reset → **永远到不了 3,永不 restart**。

**正确写法**(已修,commit 9be8998):counter 重置**只**在 health probe 成功(0 fails)时,is-active 路径不再 reset。

**反模式清单**：
- reset 路径独立于 trigger 路径(本次 bug)
- reset 条件 = "trigger 条件的子集"(本例:active ⊇ healthz-fail)
- reset 与 trigger 用同一个观察源(本例:active 路径与 healthz 路径观察的是不同维度但都被 reset)

**铁律 7 的速记**:**reset 严于 trigger**——reset 必须要求"两次 trigger 条件都消失"或"业务真恢复正常",不能"仅仅是看起来没坏"。

### 铁律 8：关键 HTTP server 必须运行在主线程（或至少能被主线程感知死亡）

> 2026-06-26 handler 死锁真因。`setup_mitm.py` 用 `threading.Thread(target=httpd.serve_forever, daemon=True).start()` + 主线程 `threading.Event().wait()`，handler thread 异常退出时主线程完全无感。

**为什么**：`BaseHTTPServer.serve_forever()` 内部是 `while not shutdown: selector.select(); handle_request()`。当 SSL `wrap_socket` 遇到损坏 client hello、或 `selector.select()` 遇到损坏 fd（`OSError EBADF`）、或底层 TCP 栈异常时，`serve_forever` 抛出异常退出。如果 `serve_forever` 跑在 **daemon thread** 中：
- 异常不传播到主线程
- 主线程继续 `Event().wait()` 永远阻塞
- systemd 看到 PID 还在 → `is-active=true`
- **服务实际不可用，但没有任何人知道**

daemon thread 的语义是"主线程退出时自动收掉"，不是"线程退出时通知主线程"。这是 Python threading 的设计，不是 bug，但**把关键服务放在 daemon thread 中是架构级错误**。

**正确写法**(已修,commit d1b4e1a):
```python
# Before (dangerous: serve_forever in daemon thread)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
threading.Event().wait()

# After (safe: main thread runs serve_forever)
httpd.serve_forever()  # 异常 → raise → 进程退出 → systemd Restart=always 自动拉起
```

**适用场景**：任何被 systemd `Restart=always` 监督的 Python HTTP server（`BaseHTTPServer` / `ThreadingHTTPServer` / `wsgiref` 等）。

**不适用场景**：PC 本地临时运行（非 systemd 监督，daemon thread 方便 Ctrl+C 退出）。这类场景用 `blocking=False` 参数区分。

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
| `scripts/mahjong-mitm-watchdog.sh` | 服务监督者，铁律 6/7 的实现 |
| `scripts/mahjong-mitm-watchdog.service` | watchdog 自身 systemd unit |
| `scripts/ecs_stability_test.sh` | 回归+极端稳定性测试脚本（铁律 6 验证工具） |
| 记忆 `noconfig-srslist-random-pollution-fix` | 根因 srslist 随机污染 |
| 记忆 `ecs-mitm-dns-bind-public` | DNS 绑公网 |
| 记忆 `watchdog-counter-reset-bug-2026-06-26` | counter 卡 1 永不 restart 真因 |
| 记忆 `4g-mitm-ecs-meta-pattern-5-regressions` | 11 天 5 次回归 meta-pattern |
| 任务 `06-26-hotupdate-4g-stall-recurrent` | 本次 handler 死锁 + relay-noconfig 覆盖修复 |
