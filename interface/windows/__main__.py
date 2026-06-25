"""`python -m windows` — Windows 本地源码态入口（PR1）。

在拿到打包 exe 前，用它在 Windows 上把完整链路跑通：
  python -m windows                 # 自动探测热点 IP(192.168.137.1) + 写死 ECS IP，起全链路
  python -m windows --no-divert     # 不起 WinDivert（无 pydivert / 调试 manifest 改写用）

前提（与仓库原 run_hijack.py 一致）：
  - 管理员终端（绑 53/443 + WinDivert 驱动）
  - PC 已开 Windows 移动热点，手机已连上
  - PR2 的托盘版会自动开热点 + 自提权，此入口仍需手动开热点

托盘编排（PR2）复用 core.start_all()，故此处跑通即代表打包后链路一致。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

# 让 `python -m windows` / `python windows/__main__.py` 都能 import 到同级 mahjong_mitm 包
_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from windows import config
from windows.core import start_all, stop_all


def main() -> None:
    ap = argparse.ArgumentParser(
        description="noconfig 本地热更 MITM — Windows 源码态入口（PR2 托盘版复用同一 core）")
    ap.add_argument("--host-ip", default=None,
                    help="PC 热点网关 IP（默认自动探测 192.168.137.1）")
    ap.add_argument("--ecs-ip", default=None,
                    help="写进 NetConf 的 ECS IP（默认写死值 / sidecar ecs.txt）")
    ap.add_argument("--apk", default=None, help="游戏 APK 路径（默认包内 assets/game_base.apk）")
    ap.add_argument("--no-divert", action="store_true",
                    help="不起 WinDivert（无 pydivert 或只调试 manifest 改写时）")
    ap.add_argument("--no-dns", action="store_true", help="不起 DNS 响应器（高级用法）")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    host_ip = args.host_ip or config.detect_hotspot_ip()
    ecs_ip = args.ecs_ip or config.load_ecs_ip()

    handles = start_all(
        host_ip, ecs_ip, apk_path=args.apk,
        enable_divert=not args.no_divert, no_dns=args.no_dns,
    )

    print("=" * 60)
    print("  noconfig 本地热更 MITM 已启动（源码态）")
    print(f"  热点网关:   {host_ip}")
    print(f"  ECS IP:     {ecs_ip}")
    print(f"  HTTPS:443  DNS:{'off' if args.no_dns else '53'}  "
          f"WinDivert:{'off' if args.no_divert else 'on'}")
    print("  手机连热点开游戏触发热更；Ctrl+C 退出。")
    print("=" * 60)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print(f"\n停止（divert 累计劫持 {handles.divert_hits} 次）。")
        stop_all(handles)


if __name__ == "__main__":
    main()
