#!/usr/bin/env python3
"""把本地 tcp_proxy.py 推到 ECS 并重启 mahjong-tcp-proxy（不碰本地 MITM/热点）。

调试 P1 读牌时用：本地改完 tcp_proxy.py（加诊断/改解码）后，一键部署到 ECS 生效。
复用 GUI 密码弹窗。SSH 又被封时给解封提示。

用法：python scripts/deploy_ecs_proxy.py   （或双击 deploy_ecs_proxy.bat）
"""

import argparse
import sys
from pathlib import Path

import paramiko


def get_ssh_password(ecs_host: str) -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        pw = simpledialog.askstring("SSH Authentication",
                                    f"Enter password for {ecs_host}:", show="*")
        root.destroy()
        if pw is None:
            raise RuntimeError("SSH password input cancelled by user.")
        return pw
    except ImportError:
        import getpass
        return getpass.getpass(f"Enter password for {ecs_host}: ")


REMOTE_DIR = "/opt/mahjong-remote/remote/noconfig/hijack"


def main() -> None:
    ap = argparse.ArgumentParser(description="部署 tcp_proxy.py 到 ECS 并重启服务")
    ap.add_argument("--ecs-host", default="root@8.136.37.136", help="user@host")
    args = ap.parse_args()

    username, _, hostname = args.ecs_host.partition("@")
    if not hostname:
        username, hostname = "root", username

    repo_root = Path(__file__).parent.parent.resolve()
    local_file = repo_root / "remote" / "noconfig" / "hijack" / "tcp_proxy.py"
    if not local_file.exists():
        print(f"ERROR: not found {local_file}", file=sys.stderr)
        sys.exit(1)

    password = get_ssh_password(args.ecs_host)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=username, password=password,
                    timeout=15, banner_timeout=15, auth_timeout=15)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "banner" in msg.lower() or "reset" in msg.lower() or "10054" in msg:
            print(f"ERROR: SSH 握手被重置——ECS 可能又封了你的 IP。\n"
                  f"  控制台 VNC: cat /etc/hosts.deny / fail2ban-client set sshd unbanip <IP>\n"
                  f"  原始: {msg}", file=sys.stderr)
        else:
            print(f"ERROR: SSH 连接失败: {type(exc).__name__}: {msg}", file=sys.stderr)
        sys.exit(1)

    try:
        print(f"Uploading tcp_proxy.py -> {REMOTE_DIR}/tcp_proxy.py ...")
        sftp = ssh.open_sftp()
        sftp.put(str(local_file), f"{REMOTE_DIR}/tcp_proxy.py")
        sftp.close()

        print("Restarting mahjong-tcp-proxy ...")
        cmd = ("systemctl restart mahjong-tcp-proxy && sleep 2 && "
               "systemctl is-active mahjong-tcp-proxy && "
               "journalctl -u mahjong-tcp-proxy --since '30 sec ago' --no-pager | tail -15")
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=40)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        print(out)
        if err.strip():
            print("----- stderr -----", file=sys.stderr)
            print(err, file=sys.stderr)
        if code != 0:
            print(f"WARNING: remote exit code {code}（服务可能未正常重启，检查上面日志）",
                  file=sys.stderr)
            sys.exit(2)
        print("OK: tcp_proxy.py 已部署并重启。现在进游戏打一局，再跑 diag_ecs.bat。")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
