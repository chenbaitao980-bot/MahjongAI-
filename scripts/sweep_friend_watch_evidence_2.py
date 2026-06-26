"""ECS 二轮探测 - 去找 raw frame / pcap 文件，并测出 0x2BC0 deal 帧里
对手位的 hand 是不是 0x3C 占位符。

策略：
  P1 - 找 ECS 上所有可能保存原始帧的目录
  P2 - 找 tcp_proxy 是否有 hexdump 模式日志
  P3 - 找 stable/protocol.py 在 ECS 上跑过没（noconfig 多用户后端的 spectator 入口）
  P4 - 从 ECS 拉一个最近的 pcap / jsonl 回本地，用 stable 离线解析
  P5 - 直接 strace -p tcp_proxy 抓正在转发的帧（如果手机正在玩）
"""
from __future__ import annotations

import sys, io
from pathlib import Path
import paramiko

# 强制 UTF-8 输出，避免 Windows GBK 乱码
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER, PASSWORD = "8.136.37.136", 22, "root", "Ysydxhyz111"

PROBES = [
    ("P1.A 全盘搜 raw/pcap/frame/dump 类文件",
     "find / -maxdepth 6 \\( -name '*.pcap' -o -name '*.jsonl' -o -name '*.dump' "
     "-o -name 'raw_*' -o -name 'frame_*' -o -name '*.bin' \\) "
     "-not -path '/proc/*' -not -path '/sys/*' -not -path '/snap/*' "
     "-mtime -30 2>/dev/null | head -40"),

    ("P1.B /opt/mahjong-remote 完整目录 (深度3)",
     "ls -la /opt/mahjong-remote 2>/dev/null; echo '---'; "
     "find /opt/mahjong-remote -maxdepth 3 -type d 2>/dev/null"),

    ("P1.C 看看 noconfig 多用户后端 (8002) 是否落盘 spectator 数据",
     "ls -laR /opt/mahjong-remote/data 2>/dev/null | head -80; echo '---'; "
     "ls -la /var/lib/mahjong* /var/log/mahjong* 2>/dev/null"),

    ("P2.A tcp_proxy 服务是否记录了原始帧（hex/raw 模式）",
     "journalctl -u mahjong-tcp-proxy -n 500 --no-pager 2>/dev/null "
     "| grep -aE 'cmd=|XY=|pay_len=|sub_cmd=|frame|hex=' | head -40"),

    ("P2.B tcp_proxy 配置看一眼",
     "cat /etc/systemd/system/mahjong-tcp-proxy.service 2>/dev/null | head -30"),

    ("P2.C tcp_proxy 当前进程 + 它打开的文件",
     "pgrep -af tcp_proxy; "
     "PID=$(pgrep -f 'tcp_proxy.py' | head -1); "
     "echo \"pid=$PID\"; "
     "ls -la /proc/$PID/fd/ 2>/dev/null | head -30"),

    ("P3.A noconfig spectator/multi-user 入口源码摘要",
     "ls /opt/mahjong-remote/remote/noconfig/ 2>/dev/null; "
     "ls /opt/mahjong-remote/remote/srs_spectator/ 2>/dev/null; "
     "cat /opt/mahjong-remote/remote/noconfig/main.py 2>/dev/null | head -80"),

    ("P3.B 看 cloud_player / spectator 入口在 ECS 干啥",
     "grep -rE 'ReqFriendTableList|RealtimeGameRecord|FriendTableInfo|0x2bc0|sub_cmd' "
     "/opt/mahjong-remote/remote/ 2>/dev/null | head -40"),

    ("P4 现在有手机正在连接吗 (7777/5045/5067)",
     "ss -tnp state established 2>/dev/null | head -40; echo '---'; "
     "ss -tnp 2>/dev/null | grep -E ':(7777|5045|5067|5167)' | head"),

    ("P5 tcp_proxy 最近 1000 行日志（有路由就有 cmd 信息）",
     "journalctl -u mahjong-tcp-proxy -n 1000 --no-pager 2>/dev/null | tail -50"),

    ("P6 noconfig backend 最近 100 行 (8002 多用户)",
     "journalctl -u mahjong-relay-noconfig -n 100 --no-pager 2>/dev/null | tail -40"),

    ("P7 看 ECS 上 stable 解码器逻辑（如有）",
     "find /opt/mahjong-remote -name 'protocol.py' -o -name 'tracker.py' 2>/dev/null"),

    ("P8 tcp_proxy.py 源码（看是否有 frame parse）",
     "wc -l /opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py 2>/dev/null; "
     "grep -nE 'def |0x2bc0|sub_cmd|parse_frame|MJProtocol|frame|cmd_id' "
     "/opt/mahjong-remote/remote/noconfig/hijack/tcp_proxy.py 2>/dev/null | head -30"),
]


def run(ssh, cmd, timeout=60):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    rc = so.channel.recv_exit_status()
    out = so.read().decode("utf-8", errors="replace")
    err = se.read().decode("utf-8", errors="replace")
    return rc, out, err


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASSWORD, timeout=15,
                allow_agent=False, look_for_keys=False)

    findings = []
    for title, cmd in PROBES:
        print(f"\n========= {title} =========")
        try:
            rc, out, err = run(ssh, cmd)
        except Exception as e:
            print(f"[err] {e}")
            findings.append((title, "[err] "+str(e)))
            continue
        body = out.rstrip()
        if err.strip():
            body += "\n[stderr]\n" + err.rstrip()
        print(body)
        findings.append((title, body))

    ssh.close()

    out_dir = Path(__file__).resolve().parents[1] / ".trellis" / "tasks" / "06-19-friend-watch-handcards-sweep" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "ecs_log_sweep_2.md"
    with out_file.open("w", encoding="utf-8") as f:
        f.write("# ECS 二轮 sweep — 找 raw frame / pcap / spectator 入口\n\n")
        for title, body in findings:
            f.write(f"## {title}\n\n```\n{body}\n```\n\n")
    print(f"\n[write] {out_file}")


if __name__ == "__main__":
    sys.exit(main() or 0)
