"""tray_app.py — Windows 托盘全自动版主入口（PR2）。

开箱即用流程（双击 exe → 全自动）：
  1. 未提权 → 弹 UAC 提权重启自身（绑 53/443 + WinDivert + 写 icssvc 注册表都需管理员）
  2. 首跑默认设开机自启（计划任务+最高权限，静默提权；仅打包 exe），并清旧 HKCU\\Run 残留
  3. 禁用热点空闲自动关闭 + 开启移动热点
  4. 起完整本地热更 MITM 链路（core.start_all：HTTPS 443 + DNS 53 + WinDivert）
  5. 起热点看门狗（常开兜底）
  6. 托盘常驻：图标色显示状态，菜单可手动开关热点 / 切自启 / 退出

来一台手机连热点开游戏即被注入（幂等，无需设备去重）。
源码态调试：python -m windows.tray_app（仍会自提权）。

依赖：pystray + Pillow（托盘）。winsdk/winrt（热点）。pydivert（WinDivert）。
"""
from __future__ import annotations

import logging
import sys
import threading
import time

from windows import config, win_admin, win_hotspot, win_task
from windows.core import MitmHandles, start_all, stop_all

logger = logging.getLogger("windows.tray_app")

_REFRESH_INTERVAL = 5.0  # 托盘状态刷新间隔（秒）


# ─── 托盘图标位图（纯代码生成，免外部 .ico）────────────────────────────────

def _make_icon(color: tuple[int, int, int]):
    """生成一个 64x64 实心圆图标。color=状态色（绿=运行/琥珀=热点关/红=故障）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=color + (255,))
    return img


_COLOR_RUNNING = (46, 160, 67)    # 绿：热点开 + MITM 跑
_COLOR_HOTSPOT_OFF = (210, 153, 34)  # 琥珀：MITM 跑但热点没开
_COLOR_FAULT = (218, 54, 51)      # 红：MITM 未起


def _ip_bindable(ip: str) -> bool:
    """这个 IP 是否已是本机可绑地址（热点接口 IP 是否就绪）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((ip, 0)); return True
    except OSError:
        return False
    finally:
        s.close()


class TrayApp:
    """托盘应用：持有 MITM 句柄 + 看门狗，驱动 pystray 图标与菜单。"""

    def __init__(self, host_ip: str, ecs_ip: str):
        self.host_ip = host_ip
        self.ecs_ip = ecs_ip
        self.handles: MitmHandles | None = None
        self.watchdog: win_hotspot.HotspotWatchdog | None = None
        self.icon = None
        self._refresher: threading.Thread | None = None
        self._stop_refresh = threading.Event()

    # ── 状态 ──
    def _running(self) -> bool:
        return self.handles is not None

    def _status_text(self, _item=None) -> str:
        if not self._running():
            return "状态：未运行"
        hs = "开" if win_hotspot.is_hotspot_on() else "关"
        n = win_hotspot.client_count()
        ncli = f"{n} 台" if n >= 0 else "?"
        return f"状态：MITM 运行中 | 热点 {hs} | 已连 {ncli} | 劫持 {self.handles.divert_hits}"

    def _current_color(self):
        if not self._running():
            return _COLOR_FAULT
        return _COLOR_RUNNING if win_hotspot.is_hotspot_on() else _COLOR_HOTSPOT_OFF

    # ── 生命周期 ──
    def start_services(self) -> None:
        # 承重墙：本方法绝不抛异常，否则托盘图标根本起不来（用户只见"无窗口"）。
        win_hotspot.disable_idle_timeout()
        if win_hotspot.start_hotspot():
            # StartTetheringAsync 返回成功 ≠ 接口 IP 已分配（DHCP/网卡 IP 有滞后），
            # 轮询等 192.168.137.1 可绑再起 MITM 链路，避开竞态。
            for _ in range(20):  # 最多约 10s
                if _ip_bindable(self.host_ip):
                    break
                time.sleep(0.5)
            else:
                logger.warning("热点已开但网关 IP %s 迟迟不可绑——稍后由刷新循环自愈",
                               self.host_ip)
        else:
            logger.warning("移动热点未能开启——请确认 PC 已联网（热点需可共享的上游）；"
                           "看门狗会持续重试")
        try:
            self.handles = start_all(self.host_ip, self.ecs_ip)
        except Exception as exc:
            # MITM 链路起不来也要让托盘先出来（红灯），由刷新循环自愈。
            self.handles = None
            logger.error("启动 MITM 链路失败（托盘仍会出现，稍后自愈）：%s", exc)
        self.watchdog = win_hotspot.HotspotWatchdog(interval=30.0)
        self.watchdog.start()
        logger.info("托盘服务就绪：host=%s ecs=%s MITM=%s",
                    self.host_ip, self.ecs_ip,
                    "运行" if self.handles is not None else "未起")

    def stop_services(self) -> None:
        if self.watchdog:
            self.watchdog.stop()
        if self.handles:
            stop_all(self.handles)
            self.handles = None

    # ── 菜单回调 ──
    def _on_toggle_hotspot(self, icon, item):
        if win_hotspot.is_hotspot_on():
            win_hotspot.stop_hotspot()
        else:
            win_hotspot.start_hotspot()
        self._refresh_now()

    def _on_toggle_autostart(self, icon, item):
        # 勾选/取消 = 建/删计划任务。托盘进程已是管理员，不会再弹 UAC。
        if win_task.is_autostart_enabled():
            win_task.disable_autostart()
        else:
            win_task.enable_autostart()
        icon.update_menu()

    def _on_quit(self, icon, item):
        logger.info("托盘退出，停止服务（热点保持现状不强制关闭）")
        self._stop_refresh.set()
        self.stop_services()
        icon.stop()

    # ── 托盘刷新 ──
    def _refresh_now(self):
        if self.icon:
            self.icon.icon = _make_icon(self._current_color())
            self.icon.title = self._status_text()
            self.icon.update_menu()

    def _refresh_loop(self):
        while not self._stop_refresh.wait(_REFRESH_INTERVAL):
            try:
                # 自愈：MITM 链路当初没起来（多半因网关 IP 没就绪），
                # 一旦热点恢复且 192.168.137.1 可绑，就补建一次链路（无需新线程）。
                if (self.handles is None
                        and win_hotspot.is_hotspot_on()
                        and _ip_bindable(self.host_ip)):
                    try:
                        self.handles = start_all(self.host_ip, self.ecs_ip)
                        logger.info("MITM 链路已自愈起来：host=%s", self.host_ip)
                    except Exception as exc:
                        logger.error("MITM 链路自愈失败（下一拍重试）：%s", exc)
                self._refresh_now()
            except Exception as exc:
                logger.debug("托盘刷新失败：%s", exc)

    def run(self) -> None:
        import pystray
        self.start_services()
        menu = pystray.Menu(
            pystray.MenuItem(self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("开/关 移动热点", self._on_toggle_hotspot),
            pystray.MenuItem(
                "开机自启", self._on_toggle_autostart,
                checked=lambda item: win_task.is_autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_quit),
        )
        self.icon = pystray.Icon(
            "MahjongMITM", _make_icon(self._current_color()),
            title=self._status_text(), menu=menu)
        self._refresher = threading.Thread(target=self._refresh_loop, daemon=True,
                                           name="tray-refresh")
        self._refresher.start()
        self.icon.run()  # 阻塞直到 _on_quit


def _setup_logging() -> None:
    """控制台 + 文件双输出。打包后 console 可关，文件日志仍可查（真机排障关键）。"""
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        import os
        log_path = os.path.join(config._app_dir(), "mahjong_mitm.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logger.info("日志文件：%s", log_path)
    except Exception as exc:  # 文件日志失败不致命
        logger.warning("文件日志初始化失败（仅控制台）：%s", exc)


def main() -> None:
    _setup_logging()

    # 1) 自提权：未提权则弹 UAC 重启自身，当前进程退出。
    if not win_admin.is_admin():
        logger.info("未以管理员运行，申请 UAC 提权……")
        if win_admin.relaunch_as_admin():
            return
        logger.error("提权失败/被拒绝，无法绑 53/443 与 WinDivert，退出")
        sys.exit(1)

    # 2) 开机自启（计划任务 + 最高权限，静默提权，仅打包 exe 生效）。
    #    迁移：清掉旧 HKCU\Run 残留项，避免与计划任务双重自启。
    win_admin.set_autostart(False)
    #    默认开、可关：仅首跑默认建一次任务，之后尊重用户在托盘里的选择不再覆盖；
    #    若用户保持开启，则每次启动按当前 exe 路径刷新一次（移动文件夹后自启仍有效）。
    if not config.autostart_was_initialized():
        win_task.enable_autostart()
        config.mark_autostart_initialized()
    elif win_task.is_autostart_enabled():
        win_task.enable_autostart()

    # 3) 配置：热点网关 + 写死/旁路 ECS IP
    host_ip = config.detect_hotspot_ip()
    ecs_ip = config.load_ecs_ip()
    logger.info("配置：热点网关=%s ECS=%s", host_ip, ecs_ip)

    # 4) 起托盘 + 全链路
    app = TrayApp(host_ip, ecs_ip)
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop_services()


if __name__ == "__main__":
    main()
