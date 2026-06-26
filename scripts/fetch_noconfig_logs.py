"""Pull recent noconfig logs with new diagnostic tags for 1v1 investigation."""
import sys
import paramiko

HOST = "8.136.37.136"
PORT = 22
USER = "root"
PASSWORD = "Ysydxhyz111"

CMDS = [
    ("--- TAG lines (last 5 min) ---",
     "journalctl -u mahjong-relay-noconfig --since '5 min ago' --no-pager | grep -E 'tag=|first data on|TcpProxy listening|register dynamic route|reuse dynamic route' || true"),
    ("--- Last 200 lines, all noconfig ---",
     "journalctl -u mahjong-relay-noconfig -n 200 --no-pager"),
    ("--- Spectator / state errors ---",
     "journalctl -u mahjong-spectator -n 100 --no-pager 2>/dev/null || echo 'no spectator unit'"),
    ("--- Active connections to game ports ---",
     "ss -tnp 2>/dev/null | grep -E ':(7777|5045|5067|5167|5748|5749|5747) ' | head -30 || netstat -tnp 2>/dev/null | grep -E ':(7777|5045|5067|5167|5748|5749|5747) ' | head -30"),
    ("--- tcp_proxy listening sockets (ECS-side TcpProxy) ---",
     "ss -tnlp 2>/dev/null | grep -E 'python|TcpProxy' | head -40"),
]


def run(ssh, cmd, timeout=30):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    return so.channel.recv_exit_status(), so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)
    for title, cmd in CMDS:
        print(f"\n========= {title} =========")
        code, out, err = run(ssh, cmd)
        print(out)
        if err.strip():
            print(f"[stderr] {err}")
    ssh.close()


if __name__ == "__main__":
    sys.exit(main())
