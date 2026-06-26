"""Find which process/service runs pid 116182 (the tcp_proxy on 5748/5749/7777)."""
import sys
import paramiko

HOST = "8.136.37.136"
USER = "root"
PASSWORD = "Ysydxhyz111"

CMDS = [
    ("--- ps for pid 116182 ---",
     "ps -fp 116182 2>/dev/null || echo 'not running'"),
    ("--- all python3 processes with cmdline ---",
     "ps -ef | grep -E 'python3|tcp_proxy' | grep -v grep"),
    ("--- find tcp_proxy scripts on disk ---",
     "find /opt -maxdepth 6 -name 'tcp_proxy.py' 2>/dev/null; find /opt -maxdepth 6 -name '*.service' 2>/dev/null | xargs -I{} sh -c 'echo === {} ===; cat {}'"),
    ("--- /etc/systemd/system listing ---",
     "ls -la /etc/systemd/system/ | grep -iE 'mahjong|tcp|srs|proxy|hijack'"),
    ("--- process tree from 116182 ---",
     "pstree -ap 116182 2>/dev/null || ps --forest -ef | grep -A 1 -B 1 116182"),
    ("--- lsof for pid 116182 listening ---",
     "ls -l /proc/116182/cwd 2>/dev/null; cat /proc/116182/cmdline 2>/dev/null | tr '\\0' ' '; echo"),
    ("--- find launcher referencing tcp_proxy ---",
     "grep -rln 'tcp_proxy' /opt /etc/systemd /usr/local/bin 2>/dev/null | head -30"),
]


def run(ssh, cmd, timeout=20):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    return so.channel.recv_exit_status(), so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, 22, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)
    for title, cmd in CMDS:
        print(f"\n========= {title} =========")
        code, out, err = run(ssh, cmd)
        print(out)
        if err.strip():
            print(f"[stderr] {err}")
    ssh.close()


if __name__ == "__main__":
    sys.exit(main())
