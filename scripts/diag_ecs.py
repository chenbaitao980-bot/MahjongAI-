#!/usr/bin/env python3
"""ECS 读牌链路一键诊断（4G/热点手牌不显示时用）。

通过 SSH（GUI 密码弹窗，复用 restart 脚本同款）登录 ECS，依次检查：
  1) 三个服务是否 active
  2) 关键端口是否在监听（大厅 5748/5749、游服动态 5700-5723、relay 8002、热更 443）
  3) mahjong-tcp-proxy 最近日志里读牌链路各环节的标记
  4) relay 最近是否收到 /push

把输出整段贴回即可定位链路断点。无需记任何命令。

用法：python scripts/diag_ecs.py   （或双击 diag_ecs.bat）
"""

import argparse
import sys

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


# 远程诊断脚本：每段加分隔标题，便于人读。since 窗口可调。
REMOTE_DIAG = r"""
echo '===== [1] services ====='
systemctl is-active mahjong-tcp-proxy mahjong-relay-noconfig mahjong-mitm-hotupdate 2>&1 | paste -d' ' <(printf 'tcp-proxy\nrelay\nmitm-hotupdate') -

echo
echo '===== [2] listening ports ====='
ss -tlnp 2>/dev/null | grep -E ':(5748|5749|7777|8002|443|5[67][0-9][0-9])\b' || echo '(no matching listeners)'

echo
echo '===== [3] tcp-proxy 读牌链路日志 (last %(since)s) ====='
journalctl -u mahjong-tcp-proxy --since '%(since)s' --no-pager 2>/dev/null \
  | grep -E 'proxy [0-9]+\] \+|lobby\]|RespSRSAddr|game-mgr\]|game-decrypt\]|0x2bc0|hand_trusted|push' \
  | tail -120 || echo '(no proxy log lines matched)'

echo
echo '===== [4] tcp-proxy 最近原始尾部 (40 行, 看有无异常/报错) ====='
journalctl -u mahjong-tcp-proxy --since '%(since)s' --no-pager 2>/dev/null | tail -40

echo
echo '===== [5] relay 最近 /push 接收 (last %(since)s) ====='
journalctl -u mahjong-relay-noconfig --since '%(since)s' --no-pager 2>/dev/null \
  | grep -iE 'push|hand|snapshot|extractor|game_client' | tail -40 || echo '(no relay push lines)'

echo
echo '===== [6] 安全组/防火墙 (本机 iptables, 看动态游服端口是否被本机拦) ====='
iptables -L INPUT -n 2>/dev/null | grep -E 'DROP|REJECT|5[67][0-9][0-9]' | head -20 || echo '(no local INPUT drops)'
echo '===== DONE ====='
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="ECS 读牌链路一键诊断")
    ap.add_argument("--ecs-host", default="root@8.136.37.136", help="user@host")
    ap.add_argument("--since", default="20 min ago", help="日志回看窗口 (journalctl --since)")
    args = ap.parse_args()

    username, _, hostname = args.ecs_host.partition("@")
    if not hostname:
        username, hostname = "root", username

    password = get_ssh_password(args.ecs_host)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=username, password=password,
                    timeout=15, banner_timeout=15, auth_timeout=15)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "banner" in msg.lower() or "reset" in msg.lower() or "10054" in msg:
            print(f"ERROR: SSH 握手被重置——ECS 可能又把你的 IP 封了。\n"
                  f"  控制台 VNC 执行: cat /etc/hosts.deny / fail2ban-client set sshd unbanip <IP>\n"
                  f"  原始: {msg}", file=sys.stderr)
        else:
            print(f"ERROR: SSH 连接失败: {type(exc).__name__}: {msg}", file=sys.stderr)
        sys.exit(1)

    try:
        cmd = REMOTE_DIAG % {"since": args.since}
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        print(out)
        if err.strip():
            print("----- stderr -----", file=sys.stderr)
            print(err, file=sys.stderr)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
