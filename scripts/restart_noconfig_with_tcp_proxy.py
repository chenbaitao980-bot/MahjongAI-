"""
Restart mahjong-relay-noconfig on ECS with updated tcp_proxy.py.
"""
import sys
import time
from pathlib import Path

import paramiko

HOST = "8.136.37.136"
PORT = 22
USER = "root"
PASSWORD = "Ysydxhyz111"

LOCAL_FILE = Path(r"E:\claude\project\MahjongAI\MahjongAI\remote\noconfig\hijack\tcp_proxy.py")
REMOTE_FILE = "/opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py"

BACKUP_CMD = f"cp {REMOTE_FILE} {REMOTE_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
RESTART_CMD = "systemctl restart mahjong-relay-noconfig"
STATUS_CMD = "systemctl is-active mahjong-relay-noconfig"
TAIL_CMD = "journalctl -u mahjong-relay-noconfig -n 30 --no-pager"


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[1/5] connecting {USER}@{HOST} ...")
    ssh.connect(HOST, PORT, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)
    print("    connected.")

    # Backup
    print(f"[2/5] backing up remote {REMOTE_FILE} ...")
    code, out, err = run(ssh, BACKUP_CMD)
    print(f"    exit={code} {out.strip()} {err.strip()}")

    # Upload
    print(f"[3/5] uploading {LOCAL_FILE.name} -> {REMOTE_FILE} ...")
    sftp = ssh.open_sftp()
    sftp.put(str(LOCAL_FILE), REMOTE_FILE)
    sftp.chmod(REMOTE_FILE, 0o644)
    sftp.close()
    # verify size match
    code, out, err = run(
        ssh,
        f"ls -l {REMOTE_FILE} && wc -l {REMOTE_FILE}",
    )
    print(f"    remote file info: {out.strip()}")

    # Restart
    print(f"[4/5] {RESTART_CMD} ...")
    code, out, err = run(ssh, RESTART_CMD, timeout=20)
    print(f"    exit={code} {out.strip()} {err.strip()}")
    time.sleep(2)
    code, out, err = run(ssh, STATUS_CMD)
    print(f"    status: {out.strip()}")

    # Tail logs
    print(f"[5/5] tail logs:")
    code, out, err = run(ssh, TAIL_CMD, timeout=15)
    print(out)

    ssh.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR: {e!r}")
        sys.exit(1)
