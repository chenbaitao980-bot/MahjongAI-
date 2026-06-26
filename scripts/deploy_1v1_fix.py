"""Deploy updated stable/protocol.py to ECS and restart mahjong-tcp-proxy."""
import sys
import time
import paramiko

HOST = "8.136.37.136"
USER = "root"
PASSWORD = "Ysydxhyz111"

LOCAL = r"E:\claude\project\MahjongAI\MahjongAI\stable\protocol.py"
REMOTE = "/opt/mahjong-remote/stable/protocol.py"

CMDS = [
    ("--- backup remote ---", f"cp {REMOTE} {REMOTE}.bak.$(date +%Y%m%d_%H%M%S)"),
    ("--- size before ---", f"wc -l {REMOTE} && ls -l {REMOTE}"),
    ("--- restart service ---", "systemctl restart mahjong-tcp-proxy"),
    ("--- status & pid ---", "sleep 2; systemctl is-active mahjong-tcp-proxy; pgrep -af tcp_proxy.py"),
    ("--- new log: listening + tag= ---",
     "journalctl -u mahjong-tcp-proxy -n 40 --no-pager | grep -E 'TcpProxy listening|tag=|tag=deal_1v1|protocol.py' | head -20"),
]


def run(ssh, cmd, timeout=30):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    return so.channel.recv_exit_status(), so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, 22, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)

    print("[1/3] upload stable/protocol.py ...")
    sftp = ssh.open_sftp()
    sftp.put(LOCAL, REMOTE)
    sftp.chmod(REMOTE, 0o644)
    sftp.close()
    code, out, err = run(ssh, f"wc -l {REMOTE} && md5sum {REMOTE}")
    print(f"    remote: {out.strip()} {err.strip()}")

    for title, cmd in CMDS:
        print(f"\n========= {title} =========")
        code, out, err = run(ssh, cmd, timeout=30)
        print(out)
        if err.strip():
            print(f"[stderr] {err}")

    ssh.close()


if __name__ == "__main__":
    sys.exit(main())
