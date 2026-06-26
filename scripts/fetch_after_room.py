"""Fetch logs after entering 1v1 room - look for 0x022b decode and hand_trusted."""
import sys
import paramiko

HOST = "8.136.37.136"
USER = "root"
PASSWORD = "Ysydxhyz111"

CMDS = [
    ("--- new dynamic port connections (last 90s) ---",
     "ss -tn 2>/dev/null | grep -E ':(5700|5701|5702|5707|5708|5722|5723|7777) ' | head -20"),
    ("--- 0x022b / 0x2bc0 hand_trusted / push (last 10 min) ---",
     "journalctl -u mahjong-tcp-proxy --since '10 min ago' --no-pager | grep -E '0x2bc0 hand_trusted|push to relay|new msg=0x022b|0x022b|hand_trusted|first data on' | head -50"),
    ("--- MJ 0x2bc0 decoded (any sub_cmd seen) ---",
     "journalctl -u mahjong-tcp-proxy --since '10 min ago' --no-pager | grep -E 'MJ 0x2bc0 decoded|new msg=0x2bc0|0x2bc0 flag' | head -40"),
    ("--- dynamic port activity (proxy +/- and reuse) ---",
     "journalctl -u mahjong-tcp-proxy --since '10 min ago' --no-pager | grep -E '\\[proxy 57|\\[proxy 7777' | head -30"),
    ("--- all tcp_proxy activity since 15:38 ---",
     "journalctl -u mahjong-tcp-proxy --since '15:38' --no-pager | tail -60"),
    ("--- relay POST /push hits ---",
     "journalctl -u mahjong-relay-noconfig --since '15:38' --no-pager | grep -E 'POST /push|presence' | tail -20"),
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
