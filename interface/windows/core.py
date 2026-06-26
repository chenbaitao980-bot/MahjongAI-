"""core.py — Windows 托盘版与源码态共用的编排入口。

把三件套拉起：
  1. setup_mitm.run()  → HTTPS MITM(0.0.0.0:443) + DNS 响应器(host_ip:53)
  2. DnsDivert         → WinDivert 拦游戏硬编码 DNS（独立线程）

托盘版（PR2 tray_app.py）与源码态（__main__.py）都调 start_all() / stop_all()，
保证"源码能跑通的链路"与"打包后 exe 跑的链路"完全一致。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("windows.core")


def kill_port_conflicts(*ports: int) -> None:
    """Best-effort cleanup for stale listeners that would block MITM startup."""
    if not ports:
        return

    try:
        import os
        import psutil
    except Exception as exc:
        logger.warning("[port-guard] skipped conflict scan for %s: %s", sorted(set(ports)), exc)
        return

    own_pid = os.getpid()
    wanted_ports = {int(port) for port in ports}
    conflicts: dict[int, set[int]] = {}

    try:
        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            port = getattr(laddr, "port", None)
            pid = getattr(conn, "pid", None)
            status = getattr(conn, "status", "")
            if port not in wanted_ports or not pid or pid == own_pid:
                continue
            if status not in ("LISTEN", "NONE", ""):
                continue
            conflicts.setdefault(pid, set()).add(port)
    except Exception as exc:
        logger.warning("[port-guard] failed to inspect local listeners for %s: %s",
                       sorted(wanted_ports), exc)
        return

    for pid, pid_ports in sorted(conflicts.items()):
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            continue
        except Exception as exc:
            logger.warning("[port-guard] unable to inspect PID=%s on ports=%s: %s",
                           pid, sorted(pid_ports), exc)
            continue

        try:
            name = proc.name()
        except Exception:
            name = "<unknown>"
        try:
            cmdline = proc.cmdline()
        except Exception:
            cmdline = []

        logger.info("[port-guard] ports=%s conflict: kill %s(PID=%s) cmdline=%s",
                    sorted(pid_ports), name, pid, cmdline)
        try:
            proc.kill()
            proc.wait(timeout=2)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            logger.warning("[port-guard] kill denied for PID=%s ports=%s: %s",
                           pid, sorted(pid_ports), exc)
        except psutil.TimeoutExpired as exc:
            logger.warning("[port-guard] PID=%s did not exit within 2s for ports=%s: %s",
                           pid, sorted(pid_ports), exc)
        except Exception as exc:
            logger.warning("[port-guard] kill failed for PID=%s ports=%s: %s",
                           pid, sorted(pid_ports), exc)


@dataclass
class MitmHandles:
    """start_all() 返回的运行句柄，供停止/状态查询使用。"""
    assets: object
    httpd: object
    dns: object
    divert: Optional[object] = None
    divert_thread: Optional[threading.Thread] = field(default=None, repr=False)

    def stop(self) -> None:
        stop_all(self)

    @property
    def divert_hits(self) -> int:
        return getattr(self.divert, "_hits", 0) if self.divert else 0


def start_all(host_ip: str, ecs_ip: str, apk_path: str | None = None, *,
              enable_divert: bool = True, no_dns: bool = False,
              enable_origin: bool = True) -> MitmHandles:
    """拉起完整本地热更 MITM 链路。

    host_ip:  写进 DNS 应答 / NetConf / manifest 的地址（PC 热点网关，手机据此连 443）。
    ecs_ip:   写进 NetConf 的目标（手机以后读牌连的机器）。
    enable_divert: 起 WinDivert 拦硬编码 DNS（Windows 真机必开；离线/无 pydivert 可关）。
    """
    from mahjong_mitm import setup_mitm

    apk_path = apk_path or setup_mitm.DEFAULT_APK
    kill_port_conflicts(443, 53)
    logger.info("启动本地热更 MITM：host_ip=%s ecs_ip=%s divert=%s no_dns=%s",
                host_ip, ecs_ip, enable_divert, no_dns)

    assets, httpd, dns = setup_mitm.run(
        host_ip, ecs_ip=ecs_ip, apk_path=apk_path,
        no_dns=no_dns, enable_origin=enable_origin,
        manifest_url_mode=setup_mitm.MANIFEST_URL_MODE_LOCAL,
    )

    divert = None
    divert_thread = None
    if enable_divert:
        from .win_dns_divert import DnsDivert
        divert = DnsDivert(host_ip)
        divert_thread = threading.Thread(target=divert.run, daemon=True, name="dns-divert")
        divert_thread.start()
        logger.info("WinDivert DNS 劫持线程已起（拦 119.29.29.29/223.5.5.5 硬编码 DNS）")

    return MitmHandles(assets=assets, httpd=httpd, dns=dns,
                       divert=divert, divert_thread=divert_thread)


def stop_all(handles: MitmHandles) -> None:
    """停止链路（尽力而为，单项失败不影响其余）。"""
    if handles.divert is not None:
        try:
            handles.divert.stop()
        except Exception as exc:
            logger.debug("停止 divert 失败：%s", exc)
    if handles.dns is not None:
        try:
            handles.dns.stop()
        except Exception as exc:
            logger.debug("停止 DNS 响应器失败：%s", exc)
    if handles.httpd is not None:
        try:
            handles.httpd.shutdown()
        except Exception as exc:
            logger.debug("停止 HTTPS 服务失败：%s", exc)
    logger.info("本地热更 MITM 链路已停止")
