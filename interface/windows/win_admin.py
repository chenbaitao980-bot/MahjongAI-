"""win_admin.py — UAC 自提权 + 开机自启（注册表 Run）。

托盘版需管理员（绑 53/443 + WinDivert 驱动 + 写 icssvc 注册表）。未提权时
relaunch_as_admin() 用 ShellExecuteW "runas" 重新拉起自身（弹 UAC），调用方随即退出。

开机自启写 HKCU\\...\\Run。仅对打包后的 exe 有意义（源码态 python -m 不写）。
"""
from __future__ import annotations

import ctypes
import logging
import sys
import winreg

logger = logging.getLogger("windows.win_admin")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "MahjongMITM"


def is_admin() -> bool:
    """当前进程是否管理员。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def relaunch_as_admin() -> bool:
    """以管理员重新拉起自身（弹 UAC）。返回 True 表示已发起重启，调用方应立即退出。

    打包 exe：直接 runas 自身 exe。
    源码态：runas python.exe，参数为当前脚本路径 + 原参数。
    """
    try:
        if _frozen():
            exe = sys.executable
            params = subprocess_list_to_str(sys.argv[1:])
        else:
            exe = sys.executable  # python.exe
            params = subprocess_list_to_str([sys.argv[0], *sys.argv[1:]])
        logger.info("请求 UAC 提权：%s %s", exe, params)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if rc <= 32:
            logger.error("ShellExecuteW 提权失败，返回码=%s（用户拒绝或出错）", rc)
            return False
        return True
    except Exception as exc:
        logger.error("提权异常：%s", exc)
        return False


def subprocess_list_to_str(args: list[str]) -> str:
    """把参数列表拼成可传给 ShellExecuteW 的命令行字符串（含空格的加引号）。"""
    out = []
    for a in args:
        if a and (" " in a or "\t" in a):
            out.append(f'"{a}"')
        else:
            out.append(a)
    return " ".join(out)


def _exe_command() -> str | None:
    """开机自启写进 Run 的命令行。仅打包 exe 返回；源码态返回 None。"""
    if _frozen():
        return f'"{sys.executable}"'
    return None


def set_autostart(enabled: bool, name: str = _AUTOSTART_NAME) -> bool:
    """打开/关闭开机自启（HKCU Run）。源码态（非 exe）打开时跳过并告警。"""
    cmd = _exe_command()
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS)
        try:
            if enabled:
                if cmd is None:
                    logger.warning("源码态无法设置开机自启（仅打包 exe 支持），跳过")
                    return False
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
                logger.info("已设置开机自启：%s -> %s", name, cmd)
            else:
                try:
                    winreg.DeleteValue(key, name)
                    logger.info("已取消开机自启：%s", name)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as exc:
        logger.error("设置开机自启失败：%s", exc)
        return False


def is_autostart_enabled(name: str = _AUTOSTART_NAME) -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, name)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
