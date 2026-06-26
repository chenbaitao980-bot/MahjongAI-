# ECS MITM 热更服务僵死修复：socket 泄漏 + origin fetch 超时

## Goal

修复 ECS 上 `mahjong-mitm-hotupdate` 服务在运行约 8–17 小时后僵死、无法响应任何请求（包括 `curl 127.0.0.1:443`）的问题。根因是扫描器流量触发 origin fetch → DNS 解析超时 → 工作线程堆积 → backlog 溢出 → 服务彻底不可用。

## What I already know

- ECS MITM 跑的是 `remote/noconfig/hijack/setup_mitm.py`，使用 `ThreadingHTTPServer`
- 服务启动后正常，运行 17h 后僵死（`Recv-Q=6 > Send-Q=5`，backlog 满）
- 线程堆栈显示：主线程卡在 `futex_wait`，工作线程卡在 `tcp_recvmsg`（socket 读）
- `ss -tn` 显示 6 个 `CLOSE-WAIT` 连接（来自扫描器 `20.65.193.189` 等）
- 日志反复出现 `resolve 8.136.32.137: no A record`——扫描器直接访问 ECS IP，MITM 把 IP 当域名去 DNS 解析
- `_resolve_real_ip` 对**所有 host** 都做 UDP DNS 查询（3s timeout），不区分域名和 IP
- `interface/mahjong_mitm/setup_mitm.py` 和 `remote/noconfig/hijack/setup_mitm.py` 的 `_resolve_real_ip` / `_origin_fetch` 代码**完全一致**，都有同样 bug
- `interface/` 版本已修复 `manifest_url_mode=local` 问题（Windows 热点首跳），但**未修复 origin fetch 僵死问题**

## Requirements

### R1: IP 地址跳过 DNS（最高优先级）

`_resolve_real_ip(host)` 必须在发送 DNS 查询前检测 `host` 是否已经是 IPv4/IPv6 地址。若是，直接返回原值，跳过 UDP DNS 查询。

### R2: 扫描器请求快速拒绝

对明显非游戏热更流量（如 `Host: <ECS_IP>` 直接访问根路径 `/`、常见扫描路径如 `/.git/config`、`/favicon.ico`、`/sitemap.xml`、`/nmap*`、`/HNAP1`、`/ReportServer`、`/evox/*`）在 `do_GET` 最前端直接返回 404，不进入 origin fetch 逻辑。

### R3: origin fetch socket 超时加固

- DNS UDP socket 保持 3s timeout（已有）
- `requests.get` 已有 `timeout=ORIGIN_TIMEOUT`（8s），但需拆分为 `timeout=(connect_timeout, read_timeout)`，防止 TCP 建连阶段也挂死
- origin fetch 整体加 `try/except/finally` 确保异常路径也能快速返回 502

### R4: CLOSE-WAIT 防护

`BaseHTTPRequestHandler` 的 `do_GET` 已在 `handle_one_request` 层面有 try/finally，但 handler 内部 `_send` 若抛异常（如 `SSLEOFError`）时，需确保 `self.wfile.close()` 被调用。验证 `ThreadingHTTPServer` 的默认行为是否已处理，如未处理则加一层包装。

### R5: 健康检查端点

增加 `GET /healthz` 端点（或复用已有轻量端点），返回 `{"status":"ok"}`，用于 ECS 外部监控（如阿里云负载均衡健康检查）。

### R6: 双文件同步修复

`remote/noconfig/hijack/setup_mitm.py`（ECS 用）和 `interface/mahjong_mitm/setup_mitm.py`（Windows 热点 exe 用）必须**同步修复**，避免两套代码长期分叉。

### R7: 部署验证

- 本地回归测试通过（`python -m pytest interface/tests/test_setup_mitm*`）
- ECS 上重启服务后 `curl 127.0.0.1:443/healthz` 或 `curl 127.0.0.1:443/hotfix_update?...` 正常
- 通过 `restart_hotspot_mitm_and_ecs.bat` 部署到 ECS（含本地热点 MITM + ECS MITM 同步重启）

## Acceptance Criteria

- [ ] `_resolve_real_ip("8.136.32.137")` 直接返回 `"8.136.32.137"`，不发送 UDP DNS 查询
- [ ] `_resolve_real_ip("gxb-oss.hzxuanming.com")` 仍正常走 DNS 解析
- [ ] 扫描器请求（`GET /.git/config`, `GET /favicon.ico` 等）在 handler 最前端返回 404，日志不打印 `origin fetch`
- [ ] 修复后服务在持续扫描器流量下保持响应（模拟测试：连续 100 次恶意请求后正常请求仍成功）
- [ ] `interface/` 和 `remote/noconfig/hijack/` 两个文件的关键修复代码一致
- [ ] ECS 部署后 `systemctl status mahjong-mitm-hotupdate` 为 `active`，`curl 127.0.0.1:443/hotfix_update?...` 返回 JSON

## Definition of Done

- 修复代码提交到 git
- 回归测试通过
- ECS 部署验证通过
- 更新相关记忆 / spec（如有新防扫描器模式值得沉淀）

## Out of Scope

- 不从单线程 ThreadingHTTPServer 升级为真正的线程池/协程池（当前问题可通过修复阻塞调用解决，暂不需要架构升级）
- 不增加 fail2ban/iptables 级别的扫描器封禁（在应用层快速拒绝已足够）
- 不改 systemd unit（保持现有自动重启策略）

## Technical Approach

1. **R1**: `_resolve_real_ip` 开头加 `socket.inet_pton(socket.AF_INET, host)` / `socket.inet_pton(socket.AF_INET6, host)` 检测，成功则直接返回 host
2. **R2**: `do_GET` 开头加扫描器路径黑名单快速 reject（在 `path == PATH_VERSION` 等匹配之前）
3. **R3**: `_origin_fetch` 的 `requests.get(..., timeout=ORIGIN_TIMEOUT)` 改为 `timeout=(3.05, ORIGIN_TIMEOUT)`（connect 3.05s, read 8s）
4. **R4**: 验证 `ThreadingHTTPServer` 的 `process_request_thread` 已有 try/finally 关闭 socket；如无，在 `make_http_handler` 返回的 Handler 上加 `setup`/`finish_request` 包装
5. **R5**: `do_GET` 中加 `if path == "/healthz": self._send(b'{"status":"ok"}', "application/json"); return`
6. **R6**: 两文件逐一应用相同修改，diff 对比确认一致

## Decision (ADR-lite)

**Context**: ECS MITM 僵死影响 4G 回连链路，必须修。有两份同源代码需要同步。
**Decision**: 先修阻塞根因（IP→DNS），再加扫描器快速 reject，最后补 healthz。两文件同步修改。
**Consequences**: 最小侵入性修复，不改架构，不改部署流程。风险低。

## Technical Notes

- 相关文件：
  - `remote/noconfig/hijack/setup_mitm.py` — ECS MITM（需修复）
  - `interface/mahjong_mitm/setup_mitm.py` — Windows 热点 MITM（需同步修复）
  - `interface/tests/test_setup_mitm_manifest_mode.py` — 已有回归测试（需扩展）
- 部署脚本：`restart_hotspot_mitm_and_ecs.bat` → `scripts/restart_hotspot_mitm_and_ecs.py`
- ECS systemd unit: `mahjong-mitm-hotupdate`
