#!/usr/bin/env python3
"""
deploy_to_ecs.py — 一键同步代码 + APK 到 ECS 并重启 systemd 服务。

真实部署形态（2026-06-15 起）：
    部署目录: /opt/mahjong-remote （非旧的 /opt/mahjong-mitm）
    systemd 服务（全部已 enable，开机自启）:
      - mahjong-tcp-proxy.service       双代理: 大厅 RespSRSAddr 改写 + 游服 SRS 解密 0x2bc0 → /push
      - mahjong-relay-noconfig.service  :8002 relay + 网页 /state
      - mahjong-mitm-hotupdate.service  热更 MITM: DNS 劫持(eth0:53) + HTTPS(443) patch manifest
                                        → 解决 4G/任意网络「校验资源」卡住

⚠ 阿里云安全组必须放行入站：TCP 443、UDP 53（热更 MITM 用）；
  TCP 5748/5749/7777/5700-5799/8002 此前已放行。
⚠ 手机需把 DNS 设为 ECS 公网 IP（8.136.37.136），热更请求才会落到 ECS。

用法:
    python deploy_to_ecs.py            # 同步代码并重启服务（默认不传 APK）
    python deploy_to_ecs.py --apk      # 同时上传 88MB APK（仅首次/换版本时需要）

前提:
    - 本地 ssh/scp 可免密连 root@8.136.37.136（已配好密钥）
    - ECS 密码（备用）: Ysydxhyz111
"""
import argparse
import os
import subprocess
import sys

ECS_IP = "8.136.37.136"
ECS_USER = "root"
REMOTE_DIR = "/opt/mahjong-remote"

# (本地路径, 远程子目录) — 远程子目录相对 REMOTE_DIR
CODE_FILES = [
    ("remote/noconfig/hijack/tcp_proxy.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/setup_mitm.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/manifest_forge.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/netconf_patch.py", "remote/noconfig/hijack"),
    ("remote/srs_spectator/crypto.py", "remote/srs_spectator"),
    ("remote/srs_spectator/frame.py", "remote/srs_spectator"),
    ("remote/srs_spectator/handshake.py", "remote/srs_spectator"),
    ("remote/relay/static/index.html", "remote/relay/static"),
]
APK_LOCAL = "apk/game_base.apk"
APK_REMOTE = f"{REMOTE_DIR}/apk/game_base.apk"

SERVICES = [
    "mahjong-tcp-proxy",
    "mahjong-relay-noconfig",
    "mahjong-mitm-hotupdate",
]


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[ERROR] 命令失败 (exit {r.returncode})")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apk", action="store_true", help="同时上传 88MB APK")
    ap.add_argument("--no-restart", action="store_true", help="只同步，不重启服务")
    args = ap.parse_args()

    for local, _ in CODE_FILES:
        if not os.path.exists(local):
            print(f"[ERROR] 找不到 {local}（请在项目根目录运行）")
            sys.exit(1)

    # 1. 同步代码
    for local, subdir in CODE_FILES:
        run(["ssh", f"{ECS_USER}@{ECS_IP}", f"mkdir -p {REMOTE_DIR}/{subdir}"])
        run(["scp", local, f"{ECS_USER}@{ECS_IP}:{REMOTE_DIR}/{subdir}/"])

    # 2. APK（可选，大文件）
    if args.apk:
        if not os.path.exists(APK_LOCAL):
            print(f"[ERROR] 找不到 {APK_LOCAL}")
            sys.exit(1)
        run(["ssh", f"{ECS_USER}@{ECS_IP}", f"mkdir -p {REMOTE_DIR}/apk"])
        run(["scp", APK_LOCAL, f"{ECS_USER}@{ECS_IP}:{APK_REMOTE}"])

    # 3. 重启服务
    if not args.no_restart:
        run(["ssh", f"{ECS_USER}@{ECS_IP}",
             "systemctl daemon-reload && systemctl restart " + " ".join(SERVICES)])
        run(["ssh", f"{ECS_USER}@{ECS_IP}",
             "sleep 2 && systemctl is-active " + " ".join(SERVICES)])

    print("\n[OK] 部署完成")
    print("提醒: 安全组需放行 TCP 443 + UDP 53；手机 DNS 设为 8.136.37.136")


if __name__ == "__main__":
    main()
