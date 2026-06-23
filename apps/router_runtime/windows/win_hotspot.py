"""win_hotspot.py — WinRT 控制 Windows 移动热点：开 / 关 / 常开 / 看门狗。

承重墙（见 prd.md）：托盘版要"热点常开 + 自动拉起"，靠两件事保证：
  1. 禁用空闲自动关闭：Windows 移动热点无设备连接约 5 分钟会自动关
     （icssvc 的 PeerlessTimeout）。开机写注册表
     HKLM\\SYSTEM\\CurrentControlSet\\Services\\icssvc\\Settings\\PeerlessTimeoutEnabled=0
     根治。需管理员（托盘版已自提权）。
  2. 看门狗兜底：HotspotWatchdog 周期性检查，发现 Stopped 就重新 StartTetheringAsync。

API：WinRT NetworkOperatorTetheringManager（绑当前上游联网 profile）。
  - 前提：PC 必须有可共享的上游联网 profile（WiFi 或以太网；现代 Win10/11 支持
    WiFi-over-WiFi，单网卡笔记本也行）。无上游则 start 抛 RuntimeError。
  - Python 侧走 winsdk（单包，打包友好）或回退 winrt（官方分包投影）。
  - 惰性导入：本模块在任意平台都可 import（便于单测）；真正调用 WinRT 时才加载，
    缺包/非 Windows 抛 ImportError/RuntimeError，由调用方（托盘）显式提示。
"""
from __future__ import annotations

import logging
import threading
import winreg

logger = logging.getLogger("windows.win_hotspot")

# 防空闲自动关闭的注册表位（icssvc 无客户端约 5 分钟自动关热点）
_ICS_SETTINGS_KEY = r"SYSTEM\CurrentControlSet\Services\icssvc\Settings"
_PEERLESS_TIMEOUT_VALUE = "PeerlessTimeoutEnabled"

# TetheringOperationalState 枚举：Off=0 On=1 InTransition=2 Unknown=3
_STATE_ON = 1
# TetheringOperationStatus 枚举：Success=0
_OP_SUCCESS = 0


def _import_winrt():
    """返回 (NetworkOperatorTetheringManager, NetworkInformation)。winsdk 优先，回退 winrt。"""
    try:
        from winsdk.windows.networking.networkoperators import NetworkOperatorTetheringManager
        from winsdk.windows.networking.connectivity import NetworkInformation
        return NetworkOperatorTetheringManager, NetworkInformation
    except ImportError:
        from winrt.windows.networking.networkoperators import NetworkOperatorTetheringManager
        from winrt.windows.networking.connectivity import NetworkInformation
        return NetworkOperatorTetheringManager, NetworkInformation


def _tethering_manager():
    """拿到绑当前上游联网 profile 的 NetworkOperatorTetheringManager。

    无上游联网 profile 时抛 RuntimeError（移动热点必须有可共享的网络）。
    """
    NetworkOperatorTetheringManager, NetworkInformation = _import_winrt()
    profile = NetworkInformation.get_internet_connection_profile()
    if profile is None:
        raise RuntimeError(
            "无上游联网 profile（PC 当前没联网）——移动热点需要一个可共享的网络连接")
    return NetworkOperatorTetheringManager.create_from_connection_profile(profile)


def _await(op):
    """阻塞等待 WinRT IAsyncOperation 完成。winsdk 支持 .get()；否则回退 asyncio。"""
    if hasattr(op, "get"):
        return op.get()
    import asyncio
    # winsdk b10 的 IAsyncOperation 是 awaitable 而非 coroutine，
    # asyncio.run(op) 会抛 ValueError；必须包进 async def 里 await。
    async def _coro():
        return await op
    return asyncio.run(_coro())


# ─── 状态查询 ────────────────────────────────────────────────────────────────

def is_hotspot_on() -> bool:
    """移动热点当前是否开启。任何异常（无包/无上游/非 Windows）视为未开。"""
    try:
        mgr = _tethering_manager()
        return int(mgr.tethering_operational_state) == _STATE_ON
    except Exception as exc:
        logger.debug("查询热点状态失败（视为未开）：%s", exc)
        return False


def client_count() -> int:
    """已连接的客户端数（查询失败返回 -1）。"""
    try:
        mgr = _tethering_manager()
        return int(mgr.client_count)
    except Exception:
        return -1


# ─── 开 / 关 ─────────────────────────────────────────────────────────────────

def start_hotspot() -> bool:
    """开启移动热点（已开则直接返回 True）。失败返回 False 并记录原因。"""
    try:
        mgr = _tethering_manager()
    except Exception as exc:
        logger.error("无法获取热点管理器：%s", exc)
        return False

    if int(mgr.tethering_operational_state) == _STATE_ON:
        logger.info("移动热点已在开启")
        return True

    try:
        result = _await(mgr.start_tethering_async())
        status = int(result.status)
        if status == _OP_SUCCESS:
            logger.info("移动热点已开启")
            return True
        msg = getattr(result, "additional_error_message", "") or ""
        logger.error("开热点失败：status=%s %s", status, msg)
        return False
    except Exception as exc:
        logger.error("开热点异常：%s", exc)
        return False


def stop_hotspot() -> bool:
    """关闭移动热点。失败返回 False。"""
    try:
        mgr = _tethering_manager()
        result = _await(mgr.stop_tethering_async())
        return int(result.status) == _OP_SUCCESS
    except Exception as exc:
        logger.error("关热点异常：%s", exc)
        return False


# ─── 防空闲自动关闭（注册表）────────────────────────────────────────────────

def disable_idle_timeout() -> bool:
    """写 PeerlessTimeoutEnabled=0 禁用"无客户端空闲自动关闭"。需管理员。

    注：该值 icssvc 在启动时读取；改完最好重启热点（看门狗下一拍会兜住空窗）。
    """
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, _ICS_SETTINGS_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, _PEERLESS_TIMEOUT_VALUE, 0, winreg.REG_DWORD, 0)
        finally:
            winreg.CloseKey(key)
        logger.info("已写 %s\\%s=0（禁用热点空闲自动关闭）",
                    _ICS_SETTINGS_KEY, _PEERLESS_TIMEOUT_VALUE)
        return True
    except PermissionError:
        logger.error("写注册表需管理员权限——禁用热点空闲关闭失败")
        return False
    except Exception as exc:
        logger.error("写注册表失败：%s", exc)
        return False


# ─── 看门狗：确保热点常开 ────────────────────────────────────────────────────

def ensure_hotspot() -> bool:
    """检查热点；未开则拉起。返回最终是否开启。"""
    if is_hotspot_on():
        return True
    logger.warning("检测到移动热点未开启，尝试拉起……")
    return start_hotspot()


class HotspotWatchdog(threading.Thread):
    """后台线程：开机先禁用空闲关闭，之后周期性 ensure_hotspot 兜底常开。"""

    def __init__(self, interval: float = 30.0, disable_timeout: bool = True):
        super().__init__(daemon=True, name="hotspot-watchdog")
        self.interval = interval
        self.disable_timeout = disable_timeout
        self._stop = threading.Event()

    def run(self) -> None:
        if self.disable_timeout:
            disable_idle_timeout()
        while not self._stop.is_set():
            try:
                ensure_hotspot()
            except Exception as exc:
                logger.error("看门狗 ensure_hotspot 异常：%s", exc)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
