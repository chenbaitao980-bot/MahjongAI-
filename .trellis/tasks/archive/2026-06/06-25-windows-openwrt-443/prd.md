# Windows/OpenWrt 启动时清理 443 端口冲突进程

## Goal

Windows exe（`MahjongMITM.exe`）和 OpenWrt ipk 启动时，若有其他进程占用 TCP 443 端口，
**自动 kill 掉冲突进程后再 bind**，避免旧 python.exe / 旧 MITM 实例把正确的 NetConf 流量
截走，导致手机始终拿到含旧 ECS IP 的 NetConf 而连旧服务器。

根因（2026-06-25 实录）：用户在服务器迁移后重启了新 `MahjongMITM.exe`，但之前调试时
跑的 `python remote/noconfig/hijack/run_hijack.py --ecs-ip 8.136.37.136` 仍在后台占用 443，
手机热更流量被旧进程拦截，热更下发旧 IP，导致全程连旧服。

## Requirements

### Windows（`interface/windows/core.py` → `start_all()` 之前）

1. 在 `setup_mitm.run()`（即 `start_https_server()` bind 443）之前，枚举所有占用
   TCP 443 的进程（用 `psutil.net_connections` + `psutil.Process`）。
2. 排除自身 PID（`os.getpid()`）。
3. 对每个冲突进程：
   - 记录日志：`[port-guard] 443 冲突：kill <name>(PID=<X>) cmdline=<...>`
   - 调用 `proc.kill()`（不用 terminate，要立即生效）
   - catch `psutil.NoSuchProcess` / `psutil.AccessDenied`（后者日志 warning 继续）
4. kill 后等待最多 2s（`proc.wait(timeout=2)` with except），确认端口释放。
5. 若 kill 失败（AccessDenied），打 WARNING 继续启动（bind 可能失败再报 OSError）。
6. 逻辑放在 `core.py` 的独立函数 `kill_port_conflicts(*ports)` 中，`start_all()` 开头调用。

### 端口范围：同时清理 443 和 53

7. `start_all()` 开头调用 `kill_port_conflicts(443, 53)`：
   - 443：HTTPS MITM（核心冲突场景）
   - 53：DNS 响应器（`SO_REUSEADDR` 通常无冲突，但旧进程残留时同样有效）
   - 两个端口复用同一函数，循环处理

### OpenWrt（`interface/openwrt/files/etc/init.d/mahjong-mitm`）

1. 在 `start_service()` 的 `procd_open_instance` 之前，加一行：
   ```sh
   fuser -k 443/tcp 2>/dev/null || true
   ```
2. 如果 `fuser` 不可用（某些路由器精简固件），fallback：
   ```sh
   lsof -ti:443 2>/dev/null | xargs -r kill -9 2>/dev/null || true
   ```
3. kill 后 `sleep 0.5`（给端口时间释放）再启动 procd。

## Acceptance Criteria

- [ ] Windows：启动时若有其他进程占用 443，日志中出现 `[port-guard]` kill 记录，
      MITM 正常绑定 443 启动
- [ ] Windows：若没有冲突进程，无额外日志，启动不受影响
- [ ] Windows：两个冲突进程同时存在时都被 kill（循环处理所有冲突）
- [ ] Windows：`psutil.AccessDenied` 时打 WARNING 不崩溃
- [ ] OpenWrt：`start_service()` 执行前 443 已被清空

## Definition of Done

- Windows 代码通过 pyinstaller 打包后在 `interface/dist/MahjongMITM/` 可运行
- OpenWrt 脚本 `sh -n` 语法检查通过
- 不引入新的依赖（`psutil` 已在 requirements；`fuser` 是 BusyBox 标准命令）

## Technical Approach

### Windows

`kill_port_443_conflicts()` 插入到 `start_all()` 第一行：

```python
def kill_port_conflicts(*ports: int) -> None:
    import psutil, os
    own = os.getpid()
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr.port in ports and conn.status in ("LISTEN", "") and conn.pid and conn.pid != own:
            try:
                proc = psutil.Process(conn.pid)
                logger.info("[port-guard] %d 冲突：kill %s(PID=%d) cmdline=%s",
                            conn.laddr.port, proc.name(), conn.pid, proc.cmdline())
                proc.kill()
                proc.wait(timeout=2)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied as e:
                logger.warning("[port-guard] kill PID=%d 失败(AccessDenied)：%s", conn.pid, e)
```

`start_all()` 开头：`kill_port_conflicts(443, 53)`

### OpenWrt

在 `start_service()` 里 `procd_open_instance` 之前：

```sh
# 清理 443 端口冲突（防止旧实例残留）
fuser -k 443/tcp 2>/dev/null || lsof -ti:443 2>/dev/null | xargs -r kill -9 2>/dev/null || true
sleep 0.5
```

## Decision (ADR-lite)

**Context**: 443 冲突发现时机 — 启动前检查 vs bind 失败后重试  
**Decision**: 启动前主动 kill（而非 bind 失败再处理）  
**Consequences**: 更早发现，日志清晰；缺点是若有合法的其他 HTTPS 服务也在 443 会被误杀
（但实际上 exe 本就要独占 443，此场景不合理）

## Out of Scope

- 进程白名单 / 用户确认弹窗（直接 kill，用日志告知）
- ECS 服务器端 443 冲突（由 systemd `ExecStartPre` 或手动处理）

## Technical Notes

- `psutil` 已在 `interface/requirements.txt` 且 PyInstaller spec 已包含
- `core.py` 现在 `start_all()` 直接调 `setup_mitm.run()` → 在此之前插入 port-guard
- OpenWrt BusyBox `fuser` 支持 `443/tcp` 语法（`-k` kill all）
- 需验证 `psutil.net_connections` 在 PyInstaller 冻结环境是否需要额外 hiddenimport
- 相关文件：`interface/windows/core.py`, `interface/openwrt/files/etc/init.d/mahjong-mitm`
