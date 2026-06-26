"""Fetch recent noconfig/tcp_proxy logs focused on 1v1 decoding."""
import sys
import paramiko

HOST = "8.136.37.136"
USER = "root"
PASSWORD = "Ysydxhyz111"

CMDS = [
    ("--- ALL tcp_proxy logs since restart (pid 117740) ---",
     "journalctl -u mahjong-tcp-proxy --since '5 min ago' --no-pager | grep -E '117740|tcp_proxy' | tail -50"),
    ("--- Diagnostic tags (register/reuse/first data/listening) ---",
     "journalctl -u mahjong-tcp-proxy -n 200 --no-pager | grep -E 'register dynamic route|reuse dynamic route|first data on|TcpProxy listening' | tail -40"),
    ("--- 0x022b / 0x2bc0 hand_trusted / push ---",
     "journalctl -u mahjong-tcp-proxy -n 300 --no-pager | grep -E '0x2bc0 hand_trusted|push to relay|MJ 0x2bc0|deal_1v1|0x022b|new msg=0x022b' | tail -30"),
    ("--- last 30 lines of any noconfig/tcp_proxy activity ---",
     "journalctl -u mahjong-tcp-proxy -n 30 --no-pager"),
    ("--- session key + presence + HandshakeRsp (lobby) ---",
     "journalctl -u mahjong-tcp-proxy -n 300 --no-pager | grep -E 'session key|presence|HandshakeRsp|RespSRSAddr' | tail -20"),
    ("--- relay push endpoint activity (port 8002) ---",
     "journalctl -u mahjong-relay-noconfig -n 100 --no-pager | grep -E 'POST /push|hand|presence|srs_sessionid' | tail -20"),
    ("--- netstat: any new connections to dynamic ports? ---",
     "ss -tn 2>/dev/null | grep -E ':(5700|5701|5702|5707|5708|5722|5723|7777) ' | head -20"),
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
