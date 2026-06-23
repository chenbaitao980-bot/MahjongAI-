"""win_task.py — 开机自启（任务计划程序 + 最高权限，静默提权）。

替代 win_admin 的 HKCU\\Run 方案。HKCU\\Run 在登录后**非提权**拉起进程，而本 exe
必须管理员（绑 53/443 + WinDivert 驱动）→ 开机后会立即弹 UAC 等用户手点才真正起服务。

改用 schtasks 建一条 ONLOGON 触发、RL HIGHEST 的计划任务：登录时由计划程序**静默以
管理员**拉起，不弹 UAC、无需手点，才是真正"开机自动启动"。

托盘进程运行时已是管理员（启动时自提权过），因此 enable/disable 直接 schtasks /Create
/Delete 不会再弹第二次 UAC。仅对打包 exe 有意义（源码态 python -m 跳过并告警）。
"""
from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger("windows.win_task")

_TASK_NAME = "MahjongMITM"

# 隐藏 schtasks 子进程的控制台黑窗（打包 exe 无 console 时尤其重要）。
_CREATE_NO_WINDOW = 0x08000000


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _exe_path() -> str | None:
    """计划任务要执行的 exe 路径。仅打包 exe 返回；源码态返回 None。"""
    if _frozen():
        return sys.executable
    return None


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    """跑 schtasks，吞控制台窗口，返回 CompletedProcess（不抛 returncode）。"""
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
    )


def enable_autostart(name: str = _TASK_NAME) -> bool:
    """建/覆盖开机自启计划任务（ONLOGON + 最高权限）。源码态跳过并告警。"""
    exe = _exe_path()
    if exe is None:
        logger.warning("源码态无法设置开机自启（仅打包 exe 支持），跳过")
        return False
    # /TR 的命令需自带引号以容纳含空格的路径；schtasks 要求整段再被外层引号包住，
    # 这里用 subprocess 列表传参，故 /TR 值本身写成带内层引号的字符串即可。
    tr = f'"{exe}"'
    cp = _run_schtasks([
        "/Create", "/TN", name, "/SC", "ONLOGON",
        "/RL", "HIGHEST", "/TR", tr, "/F",
    ])
    if cp.returncode == 0:
        logger.info("已设置开机自启计划任务：%s -> %s", name, tr)
        return True
    logger.error("建开机自启计划任务失败（rc=%s）：%s", cp.returncode,
                 (cp.stderr or cp.stdout or "").strip())
    return False


def disable_autostart(name: str = _TASK_NAME) -> bool:
    """删开机自启计划任务。任务本就不存在视为成功（幂等）。"""
    cp = _run_schtasks(["/Delete", "/TN", name, "/F"])
    if cp.returncode == 0:
        logger.info("已取消开机自启计划任务：%s", name)
        return True
    # 任务不存在时 schtasks 返回非 0（含 "ERROR: ... cannot find"），视为已是目标态。
    err = (cp.stderr or cp.stdout or "").strip()
    if "cannot find" in err.lower() or "找不到" in err:
        return True
    logger.error("删开机自启计划任务失败（rc=%s）：%s", cp.returncode, err)
    return False


def is_autostart_enabled(name: str = _TASK_NAME) -> bool:
    """开机自启计划任务是否存在（returncode 0 = 存在）。"""
    cp = _run_schtasks(["/Query", "/TN", name])
    return cp.returncode == 0
