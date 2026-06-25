"""run_pc.py — Windows 本地直测入口（第二优先级交付）。

等同于把 openwrt 的 procd 服务在 Windows PC 上手动跑起来，用于在拿到路由器前
验证抽取后的 mahjong_mitm 包与 PC 热点完全等效。

用法（管理员终端，PC 已开移动热点、手机已连上）:
  cd interface
  python pc-dev/run_pc.py --host-ip 192.168.137.1 --ecs-ip 8.136.32.137

与路由器版的区别:
  - DNS 端口默认 53（PC 直接绑，不像路由器要避开 dnsmasq）
  - 硬编码 DNS 拦截在 PC 上靠 WinDivert（remote/noconfig/hijack/dns_divert.py），
    本最小化包不含它；若游戏走硬编码 DNS，请用仓库原版 run_hijack.py 做完整 PC 测试，
    本入口主要验证「抽取后的 manifest/NetConf 改写逻辑」在新包结构下不回归。

证书落点: interface/data/mitm/（首次运行用 cryptography 自动生成，需 pip install cryptography）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

# 让 `python pc-dev/run_pc.py` 能 import 到同级的 mahjong_mitm 包
_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from mahjong_mitm.setup_mitm import DEFAULT_APK, DEFAULT_ECS_IP, run


def main() -> None:
    ap = argparse.ArgumentParser(
        description="mahjong_mitm PC 直测入口 — 验证抽取后的热更 MITM 逻辑",
    )
    ap.add_argument("--host-ip", required=True,
                    help="PC 热点 IP（手机看到的网关，如 192.168.137.1）")
    ap.add_argument("--ecs-ip", default=DEFAULT_ECS_IP,
                    help=f"ECS 公网 IP，写进 NetConf（默认 {DEFAULT_ECS_IP}）")
    ap.add_argument("--apk", default=DEFAULT_APK,
                    help="游戏 APK 路径（默认包内 assets/game_base.apk）")
    ap.add_argument("--tls-port", type=int, default=443)
    ap.add_argument("--dns-port", type=int, default=53)
    ap.add_argument("--no-dns", action="store_true", help="只起 HTTPS，不起 DNS")
    ap.add_argument("--no-origin", action="store_true",
                    help="禁用透明回源（调试用）")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not os.path.isfile(args.apk):
        print(f"[ERROR] APK 不存在: {args.apk}")
        sys.exit(1)

    run(
        host_ip=args.host_ip,
        ecs_ip=args.ecs_ip,
        apk_path=args.apk,
        tls_port=args.tls_port,
        dns_port=args.dns_port,
        no_dns=args.no_dns,
        enable_origin=not args.no_origin,
    )

    print("=" * 60)
    print("  mahjong_mitm PC 直测服务已启动")
    print(f"  PC 热点 IP:  {args.host_ip}")
    print(f"  ECS IP:      {args.ecs_ip}")
    print(f"  HTTPS:       :{args.tls_port} / DNS: :{args.dns_port}")
    print("  手机连热点开游戏触发热更；Ctrl+C 退出。")
    print("=" * 60)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n停止。")


if __name__ == "__main__":
    main()
