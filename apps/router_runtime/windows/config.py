"""config.py — Windows 托盘版的写死配置 + 旁路兜底 + 热点 IP 探测。

决议（见 prd.md）:
  - ECS IP 写死成顶层常量 ECS_IP（= mahjong_mitm 现有 DEFAULT_ECS_IP，阿里云 8.136.37.136）。
    迁服（如华纳云 HK）改这一处常量重编译即可。
  - 零成本 sidecar 兜底：exe 同目录若有 ecs.txt（单行 IP），优先用它，免重编译。
  - Windows 移动热点网关恒为 192.168.137.1（ICS 硬编码），host-ip 默认取它，无需用户填。
"""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("windows.config")

# ── 写死的 ECS IP（阿里云）。迁服改此处重编译。 ──────────────────────────────
ECS_IP = "8.136.37.136"

# ── Windows 移动热点（ICS）固定网关 IP。手机看到的网关 = 热点 IP。 ────────────
HOTSPOT_GATEWAY_IP = "192.168.137.1"

# sidecar 文件名：放在 exe / cwd 同目录，单行写一个 IP 即覆盖 ECS_IP。
_SIDECAR_NAME = "ecs.txt"

# 开机自启"首跑标记"文件名：存在 = 已默认建过一次自启，此后尊重用户选择不再覆盖。
_AUTOSTART_MARKER = ".autostart_inited"


def _app_dir() -> str:
    """exe 所在目录（打包后）或当前工作目录（源码态）——sidecar 在此查找。"""
    if getattr(sys, "frozen", False):  # PyInstaller 冻结后 sys.frozen=True
        return os.path.dirname(sys.executable)
    return os.getcwd()


def load_ecs_ip() -> str:
    """返回生效的 ECS IP：同目录 ecs.txt 存在且非空 → 用它；否则用写死的 ECS_IP。"""
    sidecar = os.path.join(_app_dir(), _SIDECAR_NAME)
    try:
        if os.path.isfile(sidecar):
            with open(sidecar, "r", encoding="utf-8") as fh:
                ip = fh.read().strip()
            if ip:
                logger.info("ECS IP 取自 sidecar %s → %s（覆盖写死值 %s）", sidecar, ip, ECS_IP)
                return ip
    except Exception as exc:
        logger.warning("读取 sidecar %s 失败，回退写死值 %s：%s", sidecar, ECS_IP, exc)
    return ECS_IP


def autostart_was_initialized() -> bool:
    """是否已做过一次"默认开机自启"初始化（首跑标记是否存在）。"""
    return os.path.isfile(os.path.join(_app_dir(), _AUTOSTART_MARKER))


def mark_autostart_initialized() -> None:
    """落首跑标记。失败不致命（最坏下次启动再默认建一次，幂等）。"""
    try:
        with open(os.path.join(_app_dir(), _AUTOSTART_MARKER), "w", encoding="utf-8") as fh:
            fh.write("1")
    except Exception as exc:
        logger.warning("写开机自启首跑标记失败（不致命）：%s", exc)


def detect_hotspot_ip() -> str:
    """探测 PC 热点网关 IP。

    Windows 移动热点/ICS 的网关恒为 192.168.137.1（系统硬编码），直接返回常量。
    保留独立函数是为日后需要在多网卡环境做真实枚举时只改这一处。
    """
    return HOTSPOT_GATEWAY_IP
