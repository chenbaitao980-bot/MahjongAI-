# 排查热更MITM服务稳定性与NetConf覆盖有效性

## Goal

1. 验证「同步官方资源 + NetConf 覆盖固定不变」机制在当前代码和部署状态下是否依然有效
2. 基于历史故障（06-19 间歇性连接失败已修复）和代码审查，排查剩余可能导致服务不可用或用户无法登录的风险点

## What I already know

### NetConf 覆盖机制当前状态
- `setup_mitm.py` 使用 4 段缓冲支配版本：`(1, 5, 9, 3001)` offsets，build 段当前 +3001（scenario 3 真机验证后定版）
- `patch_real_version_manifest`: 回源真实 version.manifest → 顶高 version + 清空 project_md5 + 删 zip + manifest_url/update_url 改写到 ECS
- `patch_real_project_manifest`: 回源真实 project.manifest → 只改 NetConf 条目 md5/size/name + 顶高 version + forbid_zip + update_url→ECS
- `INJECT_LOBBY_CHECKER = False`（默认）：不注入跳过 clean_res 的 ResEnsure/ResChecker，避免黑屏
- `file_url_mode = "official"`（默认）：官方文件 4G 直连官方 CDN，ECS 零带宽
- `_inject_srs50_block` 已注入 `LOCAL_TCP_LIST_50[5045]=ECS`，钉死 _50 分支跳过 srslist 随机污染（06-19 修复）

### 历史故障与修复
- **06-19 间歇性连接失败**: 根因 = `srslist{5045}.json` 缓存把真服混进随机池 → 修复 = 注入 `_50[5045]=ECS` + bump build 偏移到 +3000（后定版 +3001）
- **06-18 ECS 故障兜底回滚**: Path Y（保留真服 fallback）被回滚为 ECS 单点，与"ECS 宕机用户能玩"互斥 → 选抓牌
- **06-15 热更后黑屏**: 根因 = 跳过 clean_res 的 ResEnsure 在版本回落脏 harbor 上做增量合并 → 修复 = `INJECT_LOBBY_CHECKER=False`
- **06-14 真机首次成功**: 4 个 bug 修复（DNS 缺 imeete / NetConf 注入 / file 前缀 / 版本降级）
- **06-17 PlayerData nick_len 1B**: 误用 `<H`(2B) 吃掉首字符 → sessionid 拿不到 → 已修

### 关键代码文件
- `remote/noconfig/hijack/setup_mitm.py` — 热更 MITM，版本控制 + manifest patch
- `remote/noconfig/hijack/netconf_patch.py` — NetConf 解密/改写/重加密
- `remote/noconfig/hijack/tcp_proxy.py` — ECS 双代理（大厅+游服）
- `remote/noconfig/hijack/ecs_run.py` — ECS 代理独立进程启动器
- `remote/noconfig/app.py` — noconfig relay (8002)，多用户管理

### 已发现的潜在风险（初步）
1. **ECS IP 硬编码不一致**: `setup_mitm.py DEFAULT_ECS_IP="8.136.32.137"` ✓，但 `tcp_proxy.py` 默认 `--ecs-ip 8.136.37.136`（旧 IP！）、`ecs_run.py` 默认 `"8.136.37.136"`
2. **回源官方 host 硬编码**: `OFFICIAL_UPDATE_HOSTS` / `OFFICIAL_MANIFEST_HOST` 固定写死，若官方改域名则回源 502 → 静态兜底
3. **tcp_proxy.py 中 requests Session 关闭问题**: `_origin_fetch` 中 `session.close()` 在 finally 里，但 session 变量在异常分支可能未定义
4. **热更 MITM 服务健壮性**: ThreadingHTTPServer + daemon thread，异常时可能静默停止
5. **APK 版本过旧风险**: 静态 manifest fallback 基于 APK 内置旧版，若线上版本差异大可能 diff 出大量文件

## Assumptions (temporary)

- 当前 ECS 部署使用的是最新代码（含 06-19 _50 注入修复和 +3001 版本偏移）
- 用户提到的"服务不可用"是指 noconfig 模式的 admin 页面看不到用户 / 手机连不上 ECS

## Open Questions

- 用户说的"最近服务出现过不可用"具体是什么症状？（admin 空 / 手机卡登录 / 手牌不更新 / 进程崩溃？）
- 是否已确认 ECS 上 tcp_proxy 的 `--ecs-ip` 参数使用的是新 IP 8.136.32.137？

## Requirements (evolving)

### 必做（本任务）
- 实施 watchdog 进程（A 方案），独立监督 3 个 ECS 服务：
  - `mahjong-mitm-hotupdate`
  - `mahjong-tcp-proxy`
  - `mahjong-relay-noconfig`
- 探测机制：每 30s 探测 `/healthz` + `/mode`，失败则 systemctl restart
- watchdog 自身作为 systemd unit 部署（Restart=always）
- watchdog 脚本 + service file 全部进 git 仓库并走 deploy 同步
- 同步修复 P0-1（IP 硬编码默认值）：tcp_proxy / ecs_run / ecs_proxy / deploy_to_ecs / start_ecs_services 默认值改为 8.136.32.137（保持运行时正确，但默认值与实际一致）

### 可选（后续任务）
- P1-2 session 关闭健壮性
- P1-3 静态 manifest fallback 用 APK 旧版风险
- P2-1 官方 host 硬编码
- P2-2 健康监控告警

## Acceptance Criteria

- [ ] `mahjong-mitm-watchdog.sh` 部署到 ECS，能自动探测 /healthz
- [ ] `mahjong-mitm-watchdog.service` 文件在 git 仓库中，deploy_to_ecs.py 同步
- [ ] /healthz 失败 2/2 时自动 restart hotupdate + tcp_proxy
- [ ] watchdog 自身崩溃能自启（Restart=always）
- [ ] tcp_proxy.py / ecs_run.py / ecs_proxy.py 默认 ECS IP 改为 8.136.32.137
- [ ] deploy_to_ecs.py ECS_IP 常量改为 8.136.32.137
- [ ] start_ecs_services.bat ECS_HOST 改为 8.136.32.137
- [ ] 部署后 systemd is-active 全部 active

## Technical Approach

**方案 A：独立 watchdog 进程**

- watchdog 脚本：`/usr/local/bin/mahjong-mitm-watchdog.sh`，30s 循环
- 探测 `https://127.0.0.1:443/healthz` + `http://127.0.0.1:8002/mode`
- 失败 ≥ 2/2 → `systemctl restart mahjong-mitm-hotupdate mahjong-tcp-proxy`
- watchdog 自身：`mahjong-mitm-watchdog.service`（Type=simple, Restart=always, RestartSec=10）
- 所有文件走 deploy_to_ecs.py 同步

## Decision (ADR-lite)

**Context**: 06-26 修复的 MITM 死锁/CLOSE-WAIT 是导致服务不可用的根因。systemd 的 `Restart=always` 只能捕获**进程崩溃**，无法捕获**进程死锁但还活着**（主线程 `threading.Event().wait()` 阻塞，handler thread 全挂）。需要独立监督。

**Decision**: 选 A 方案 - 独立 watchdog 进程。

**Consequences**:
- 优点：进程解耦，零代码改动，可观测，多服务统一监督
- 缺点：多一个 systemd unit 需要维护
- 风险：watchdog 自身可能 bug 死循环 → 用 bash + 简单循环 + 重启策略规避

## Out of Scope

- C 方案（systemd Type=notify + sd_notify） - 长期演进，本轮不做
- P1-2 / P1-3 / P2-1 / P2-2 风险 - 后续任务
- 改 systemd Type=simple → Type=notify - 暂不实施

## Technical Notes

- 现有 systemd unit（实测）:
  - `mahjong-mitm-hotupdate.service`: `--host-ip 8.136.32.137 --dns-listen-host 0.0.0.0 --ecs-ip 8.136.32.137`
  - `mahjong-tcp-proxy.service`: `--ecs-ip 8.136.32.137 --listen-host 0.0.0.0 --relay-push http://127.0.0.1:8002/push`
  - `mahjong-relay-noconfig.service`: `main.py --host 0.0.0.0 --port 8002`
- /healthz 端点已在 `setup_mitm.py:887` 实现
- 参考现有 `remote/extractor/files/mahjong-extractor.service` 的部署模式
- Spec: `.trellis/spec/guides/mitm-connection-stability-guide.md`
- 记忆: `noconfig-srslist-random-pollution-fix` / `ecs-mitm-dns-bind-public` / `hotupdate-4g-stall-fake-version`
