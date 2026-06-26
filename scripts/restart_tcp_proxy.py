"""Restart mahjong-tcp-proxy service on ECS so new tcp_proxy.py (with diagnostic tags) loads."""
import sys
import time
import paramiko

HOST = "8.136.37.136"
USER = "root"
PASSWORD = "Ysydxhyz111"

CMDS = [
    ("--- pre: status & uptime ---",
     "systemctl is-active mahjong-tcp-proxy; systemctl show mahjong-tcp-proxy -p ActiveEnterTimestamp --value"),
    ("--- restart service ---",
     "systemctl restart mahjong-tcp-proxy"),
    ("--- post: status ---",
     "systemctl is-active mahjong-tcp-proxy; sleep 2; ps -ef | grep tcp_proxy.py | grep -v grep"),
    ("--- listening sockets of new pid ---",
     "PID=$(pgrep -f 'tcp_proxy.py.*--ecs-ip' | head -1); echo pid=$PID; ss -tnlp 2>/dev/null | grep -E \"python3,$PID\" | head -20"),
    ("--- last 60 log lines ---",
     "journalctl -u mahjong-tcp-proxy -n 60 --no-pager"),
]


def run(ssh, cmd, timeout=30):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    return so.channel.recv_exit_status(), so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, 22, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)
    for title, cmd in CMDS:
        print(f"\n========= {title} =========")
        code, out, err = run(ssh, cmd, timeout=30)
        print(out)
        if err.strip():
            print(f"[stderr] {err}")
    ssh.close()


if __name__ == "__main__":
    sys.exit(main())
