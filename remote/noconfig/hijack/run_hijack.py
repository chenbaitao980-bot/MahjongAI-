"""run_hijack.py — 本地一键启动热更 MITM 设置期服务。

用法（管理员终端）:
  python remote/noconfig/hijack/run_hijack.py --host-ip 192.168.137.1

流程:
  1. 启动 DNS 响应器 (UDP:53) — 把游戏热更域名劫持到 PC
  2. 启动 DNS 拦截器 (WinDivert) — 拦截游戏硬编码 DNS（119.29.29.29/223.5.5.5）
  3. 启动 HTTPS 服务 (TCP:443) — 自签证书 + 伪 manifest + 改过的 NetConf.luac
  4. 手机连热点 → 开游戏 → 热更检查 → NetConf 被改写（台州 5045 → ECS）
  5. 完成后手机断热点切任意网络，ECS 双代理（tcp_proxy）常驻读取手牌

前提:
  - PC 已开移动热点（或 ICS 共享），手机已连上
  - ECS 上已部署 tcp_proxy（remote/noconfig/hijack/tcp_proxy.py --ecs-ip 0.0.0.0）
  - APK 文件在 apk/game_base.apk
  - 以管理员权限运行（需要绑 UDP:53 + TCP:443 + WinDivert 驱动）

⚠ 设置期只需做一次。NetConf 改写后手机任意网络都能连 ECS，直到官方推更高版本。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from remote.noconfig.hijack.setup_mitm import run, DEFAULT_ECS_IP, DEFAULT_APK

try:
    from remote.noconfig.hijack.dns_divert import DnsDivert
    HAS_DNSDIVERT = True
except ImportError:
    HAS_DNSDIVERT = False


def main() -> None:
    ap = argparse.ArgumentParser(
        description="一键启动热更 MITM — 手机连热点开游戏，NetConf 被改写指向 ECS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用步骤:
  1. PC 开移动热点（设置 → 移动热点），记下 PC 热点 IP（通常是 192.168.137.1）
  2. 以管理员身份运行: python remote/noconfig/hijack/run_hijack.py --host-ip 192.168.137.1
  3. 手机连热点，打开游戏，等热更检查完成
  4. 看到日志 "NetConf.luac" 下载成功后，手机断热点切 4G/WiFi
  5. 以后任意网络，ECS 8002 端口都能读到手牌

ECS 端（提前部署，只需一次）:
  python remote/noconfig/hijack/tcp_proxy.py --ecs-ip 0.0.0.0
        """)
    ap.add_argument("--host-ip", required=True,
                    help="PC 热点 IP（手机看到的网关，如 192.168.137.1）")
    ap.add_argument("--ecs-ip", default=DEFAULT_ECS_IP,
                    help=f"ECS 公网 IP，写进 NetConf（默认 {DEFAULT_ECS_IP}）")
    ap.add_argument("--apk", default=DEFAULT_APK,
                    help="游戏 APK 路径（默认 apk/game_base.apk）")
    ap.add_argument("--tls-port", type=int, default=443,
                    help="HTTPS 端口（默认 443；需管理员权限）")
    ap.add_argument("--dns-port", type=int, default=53,
                    help="DNS 端口（默认 53；需管理员权限）")
    ap.add_argument("--no-dns", action="store_true",
                    help="不起 DNS（手动改 DNS 或高级用法）")
    ap.add_argument("--no-divert", action="store_true",
                    help="不起 WinDivert（游戏不走硬编码 DNS 时）")
    ap.add_argument("--bump-version", default="9.9.9.103",
                    help="伪版本号（默认 9.9.9.103，永不回滚）")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not os.path.isfile(args.apk):
        print(f"[ERROR] APK 不存在: {args.apk}")
        print("  请把游戏 APK 放到 apk/game_base.apk 或用 --apk 指定路径")
        sys.exit(1)

    # 1. 启动 setup_mitm（DNS responder + HTTPS）
    assets, httpd, dns = run(
        host_ip=args.host_ip,
        ecs_ip=args.ecs_ip,
        apk_path=args.apk,
        tls_port=args.tls_port,
        dns_port=args.dns_port,
        no_dns=args.no_dns,
        bump_version=args.bump_version,
    )

    # 2. 启动 DnsDivert（WinDivert 拦截硬编码 DNS）
    divert = None
    if not args.no_divert and HAS_DNSDIVERT:
        try:
            divert = DnsDivert(self_ip=args.host_ip)
            divert_thread = threading.Thread(target=divert.run, daemon=True)
            divert_thread.start()
            print(f"[OK] DnsDivert 启动: 劫持硬编码 DNS -> {args.host_ip}")
        except Exception as exc:
            print(f"[WARN] DnsDivert 启动失败（需管理员 + pydivert）: {exc}")
            print("      游戏可能因硬编码 DNS 不走 MITM，热更链路不生效")
    elif not HAS_DNSDIVERT:
        print("[WARN] pydivert 未安装，无法拦截硬编码 DNS")
        print("       pip install pydivert 后重试")

    print()
    print("=" * 60)
    print("  热更 MITM 设置期服务已启动")
    print("=" * 60)
    print(f"  PC 热点 IP:  {args.host_ip}")
    print(f"  ECS IP:      {args.ecs_ip}")
    print(f"  DNS:         :{args.dns_port} (劫持 4 个游戏域名)")
    if divert:
        print(f"  WinDivert:   已启动 (拦截 119.29.29.29 / 223.5.5.5)")
    else:
        print(f"  WinDivert:   未启动 (游戏硬编码 DNS 可能绕过)")
    print(f"  HTTPS:       :{args.tls_port} (自签证书)")
    print(f"  伪版本:      {assets.version}")
    print(f"  NetConf:     台州 5045 -> {args.ecs_ip}")
    print()
    print("  下一步:")
    print(f"  1. 手机连热点 (DNS 已自动下发 {args.host_ip})")
    print("  2. 打开游戏，等待热更检查")
    print("  3. 看到下方日志出现 [mitm] ... NetConf.luac 即成功")
    print("  4. 之后手机切任意网络，ECS 8002 都能读手牌")
    print("=" * 60)
    print()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n正在停止...")
        if divert:
            divert.stop()
        if dns:
            dns.stop()
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    main()
