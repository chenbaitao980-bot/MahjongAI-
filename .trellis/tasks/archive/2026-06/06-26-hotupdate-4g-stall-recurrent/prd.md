# brainstorm: 4G卡校验本地资源排查(又发生)

## Goal

排查 2026-06-26 报告的「游戏又卡在校验本地资源中」故障根因。
服务器密码 Ysydxhyz111(已收到,但 SSH 密钥有效直接登录;若新 ECS 重装则需密码)。

## Root Cause (已定位)

**`mahjong-mitm-hotupdate` 服务的 HTTP handler thread 已死,但 systemd 看主线程还在不重启;watchdog 计数器因脚本 bug 卡 1 不再累加,永远到不了 3 → 永不触发自动 restart。**

### 直接证据

| 探测 | 结果 |
|---|---|
| `systemctl is-active mahjong-mitm-hotupdate` | `active` (systemd 视角) |
| `ss -tlnp \| grep :443` | `LISTEN 0.0.0.0:443 pid=15569` (socket 在) |
| `curl --max-time 5 https://127.0.0.1:443/healthz` | **timeout 5s** ← 死 |
| `curl http://127.0.0.1:8002/mode` | 1.3ms 200 (relay 正常) |
| 进程 thread 数 | 3 (主+DNS+?;正常 HTTP server 应几十条 handler) |
| 进程 CPU | 0.0% / 0 上下文切换 7 次(应是 1000+) |
| `ss -tn \| grep 443` | 2× CLOSE-WAIT(518B) + 2× ESTAB(其中 1 个无 owner) |
| 19:20 真实客户端 39.184.31.145/223.104.166.111 | 拿到 2.5.10.4783 正确响应 |
| 21:01:24 起 watchdog 持续 1/2 endpoint down | counter 卡 1 |

### 为什么「又」发生(回归链)

1. 2026-06-15 修复 4G 校验卡根因(部署 hotupdate MITM + NetConf 大小写)
2. 2026-06-17 4段缓冲版本定版
3. 2026-06-19 修 DNS 绑 0.0.0.0
4. 2026-06-26 18:30 commit 78865c2 加 watchdog 监督 + 迁 ECS IP 到 8.136.32.137
5. 19:20 hotupdate 正常服务(看到 4G 手机正常拿到 2.5.10.4783)
6. **19:20~21:01 之间某时点 handler thread 死**(死因待查)
7. 21:01:24 watchdog 第一次发现 1/2 endpoint down
8. **counter 永远卡 1** → 永远不会触发 restart
9. 21:11 用户开游戏 → DNS 解析 → ECS:443 → handler 死 → 卡 0%

### Watchdog counter bug

`/usr/local/bin/mahjong-mitm-watchdog.sh` 主循环里:

```bash
for svc in "${WATCH_SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        restart_service "$svc" || true       # 不 active → restart + 归零
    else
        set_counter "$svc" 0                # ★ active → 直接归零
    fi
done

# 之后才探测 /healthz / /mode
fails=$(probe_all_health)
if (( fails == 0 )); then continue
# 累加 counter ...
```

**Bug**:`systemctl is-active` 看主线程活就 reset counter,然后再探测 /healthz 失败只把 counter 0→1。下一轮又是 0→1,永远卡 1,达不到 `FAIL_THRESHOLD=3`。

正确逻辑应该是:**counter 累加要在 reset 之前**,或干脆只信 healthz 探测结果(active 不能 reset 已观察到的失败)。

## What I already know

- ECS 永远只读,改文件必走本地 git → restart_hotspot_mitm_and_ecs.bat
- 旧 ECS 8.136.37.136 已迁到华纳云 HK 8.136.32.137
- ssh-ecs 技能:SSH 密钥有效,密码非必需
- hotupdate 服务 systemd unit 正常,IP 参数正确(--host-ip 8.136.32.137 --dns-listen-host 0.0.0.0)

## Open Questions (待问)

- Q1: 用户当前场景(4G/热点/WiFi?)→ 4G(看 watchdog 日志+日志 IP 来源 39.184.31.145/223.104.166.111 都是公网)
- Q2: 立刻重启 hotupdate 临时恢复 + 修 watchdog 长效?

## Requirements (evolving)

- 立即 unblock 用户(临时重启 hotupdate)
- 修 watchdog counter 永远卡 1 的 bug(本地改 → commit → 部署)
- 找出 hotupdate handler 死的根因(本次不深挖,下次调查)

## Acceptance Criteria

- [ ] hotupdate 4G 链路立即恢复(/healthz < 1s)
- [ ] watchdog 3 次失败后真触发 restart
- [ ] 本地 git 提交修复 + 部署 ECS
- [ ] 文档更新(失效的 reset 逻辑)

## Definition of Done

- 临时 fix 部署,4G 手机可进游戏
- 长效 fix 提交入 git,watchdog log 验证可累加到 3
- 不在 ECS 上手改代码

## Out of Scope (本次)

- hotupdate handler 死锁的真因(资源耗尽/线程泄露/网络风暴)— 留待下次
- 协议层 0x2bc0 解密

## Spec Conflicts

(无)

## Technical Notes

- 关键路径:
  - 服务 unit: /etc/systemd/system/mahjong-mitm-hotupdate.service (正确)
  - watchdog unit: /etc/systemd/system/mahjong-mitm-watchdog.service (正确)
  - watchdog 脚本: /usr/local/bin/mahjong-mitm-watchdog.sh (有 bug)
  - 状态目录: /var/lib/mahjong-mitm-watchdog/
  - 状态文件: mahjong-mitm-hotupdate.counter (当前 1) / mahjong-mitm-tcp-proxy.counter (当前 1) / mahjong-relay-noconfig.counter (当前 0)
- 关键 commit: 78865c2 (watchdog 加入) / 744f0a7 (CLOSE-WAIT 修过)/ 7a67ac4 (R7 超时加固)
- 当前 hotupdate pid: 15569, 启动 5h17m ago (16:00 左右)
- 部署: deploy_to_ecs.py (含 watchdog 同步);start_ecs_services.bat
- 修复: 本地改 scripts/mahjong-mitm-watchdog.sh,git commit,deploy_to_ecs.py
