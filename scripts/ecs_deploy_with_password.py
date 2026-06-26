"""ecs_deploy_with_password.py — 使用密码连接 ECS 并部署代码。

用法:
    python ecs_deploy_with_password.py            # 同步代码并重启服务
    python ecs_deploy_with_password.py --apk      # 同时上传 APK

密码从环境变量 ECS_PASSWORD 或用户输入获取。
"""
import argparse
import os
import subprocess
import sys
import getpass

ECS_IP = "8.136.37.136"
ECS_USER = "root"
REMOTE_DIR = "/opt/mahjong-remote"

CODE_FILES = [
    ("remote/noconfig/hijack/tcp_proxy.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/setup_mitm.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/manifest_forge.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/netconf_patch.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/dns_divert.py", "remote/noconfig/hijack"),
    ("remote/noconfig/hijack/run_hijack.py", "remote/noconfig/hijack"),
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


def run_ssh(cmd: str, password: str) -> int:
    """使用 sshpass 通过密码执行 SSH 命令。"""
    full_cmd = ["sshpass", "-p", password, "ssh", "-o", "StrictHostKeyChecking=no",
                f"{ECS_USER}@{ECS_IP}", cmd]
    print(f"$ ssh {ECS_USER}@{ECS_IP} '{cmd}'")
    r = subprocess.run(full_cmd)
    return r.returncode


def run_scp(local: str, remote: str, password: str) -> int:
    """使用 sshpass 通过密码执行 SCP。"""
    full_cmd = ["sshpass", "-p", password, "scp", "-o", "StrictHostKeyChecking=no",
                local, f"{ECS_USER}@{ECS_IP}:{remote}"]
    print(f"$ scp {local} -> {remote}")
    r = subprocess.run(full_cmd)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apk", action="store_true", help="同时上传 88MB APK")
    ap.add_argument("--no-restart", action="store_true", help="只同步，不重启服务")
    ap.add_argument("--password", default=None, help="ECS 密码（也可从环境变量获取）")
    args = ap.parse_args()

    # 获取密码
    password = args.password or os.environ.get("ECS_PASSWORD")
    if not password:
        password = getpass.getpass(f"输入 ECS ({ECS_IP}) root 密码: ")

    # 检查 sshpass
    if subprocess.run(["which", "sshpass"], capture_output=True).returncode != 0:
        print("[ERROR] 需要安装 sshpass:")
        print("  Windows: 无原生支持，请手动 SSH 或使用 PowerShell")
        print("  Linux: apt install sshpass")
        sys.exit(1)

    for local, _ in CODE_FILES:
        if not os.path.exists(local):
            print(f"[ERROR] 找不到 {local}（请在项目根目录运行）")
            sys.exit(1)

    # 1. 同步代码
    for local, subdir in CODE_FILES:
        remote_subdir = f"{REMOTE_DIR}/{subdir}"
        if run_ssh(f"mkdir -p {remote_subdir}", password) != 0:
            print(f"[ERROR] mkdir {remote_subdir} 失败")
            sys.exit(1)
        if run_scp(local, remote_subdir + "/", password) != 0:
            print(f"[ERROR] scp {local} 失败")
            sys.exit(1)

    # 2. APK（可选）
    if args.apk:
        if not os.path.exists(APK_LOCAL):
            print(f"[ERROR] 找不到 {APK_LOCAL}")
            sys.exit(1)
        if run_ssh(f"mkdir -p {REMOTE_DIR}/apk", password) != 0:
            print(f"[ERROR] mkdir apk 失败")
            sys.exit(1)
        if run_scp(APK_LOCAL, APK_REMOTE, password) != 0:
            print(f"[ERROR] scp APK 失败")
            sys.exit(1)

    # 3. 重启服务
    if not args.no_restart:
        restart_cmd = "systemctl daemon-reload && systemctl restart " + " ".join(SERVICES)
        if run_ssh(restart_cmd, password) != 0:
            print("[ERROR] 重启服务失败")
            sys.exit(1)

        check_cmd = "sleep 2 && systemctl is-active " + " ".join(SERVICES)
        if run_ssh(check_cmd, password) != 0:
            print("[ERROR] 服务未激活")
            sys.exit(1)

    print("\n[OK] 部署完成")
    print("提醒: 安全组需放行 TCP 443 + UDP 53；手机 DNS 设为 8.136.37.136")


if __name__ == "__main__":
    main()