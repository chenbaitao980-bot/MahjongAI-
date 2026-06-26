"""attack-surface-sweep: 加好友→看对手手牌 全链路证据扫描

在 ECS 日志里找：
  L1) 协议 ID 是否真在线上被使用：
      - 431 (CMDT_REQFRIENDTABLEINFO)
      - 432 (CMDT_RESPFRIENDTABLEINFO)
      - CMDT_REQ/RESP_REALTIME_GAME_RECORD（数字未在我们解的协议中标定）
      - 461 (REQWILLJOINTABLE)
  L2) RoomProtocol.action=4(SEEGAME) / 9(SEEGAME2) 的 ReqJoinTable
  L3) 0x2BC0 sub_cmd=0x0003 deal 帧里对手位是否 == 0x3C
  L4) m_SeeRule 字符串实际下发了什么字面量
  L5) nManagerRight / nUserRight 实际值的位模式

每条独立可验证，结果回写本地 .trellis/tasks/<taskdir>/research/。
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import paramiko

HOST = "8.136.37.136"
PORT = 22
USER = "root"
PASSWORD = "Ysydxhyz111"

# --- 探测用的 grep 命令组（只读，不改服务端） ---
PROBES = [
    ("L1.A friend-table-info 协议 ID 出现频次（all-time + last hour）",
     "echo '[total]'; "
     "journalctl --no-pager -u mahjong-relay-noconfig -u mahjong-tcp-proxy 2>/dev/null "
     "| grep -E 'cmd=43[12]|XY_ID=43[12]|ReqFriendTableList|RespFriendTableList' | wc -l; "
     "echo '[last 1h]'; "
     "journalctl --no-pager --since '1 hour ago' -u mahjong-relay-noconfig -u mahjong-tcp-proxy 2>/dev/null "
     "| grep -E 'cmd=43[12]|ReqFriendTableList|RespFriendTableList' | wc -l"),

    ("L1.B 实时观战协议（搜可能的常量名 + 任何 RealtimeGameRecord 字面）",
     "journalctl --no-pager -u mahjong-relay-noconfig -u mahjong-tcp-proxy --since '7 days ago' 2>/dev/null "
     "| grep -aiE 'realtime.{0,3}gamerecord|RespRealtimeGame|ReqRealtimeGame|watch.{0,3}room|UnwatchRealtime' "
     "| head -40 || echo '(no hits)'"),

    ("L1.C SEEGAME / 旁观 join action 字段",
     "journalctl --no-pager -u mahjong-relay-noconfig -u mahjong-tcp-proxy --since '7 days ago' 2>/dev/null "
     "| grep -aiE 'action=4|action=9|SEEGAME|bSeer=true|seer=true|isSeer' "
     "| head -40 || echo '(no hits)'"),

    ("L2 0x2BC0 deal 帧 sub_cmd=0x0003 在 noconfig pcap 历史里出现的次数（必须有，否则 stable 解码器都没活）",
     "ls -lh /opt/mahjong-remote/data/pcaps/ 2>/dev/null | head -10; "
     "ls -lh /opt/mahjong-remote/data/sessions/ 2>/dev/null | head -10; "
     "echo '---'; "
     "find /opt/mahjong-remote/data /var/log/mahjong* /tmp -name '*.jsonl' -mtime -7 2>/dev/null | head -10"),

    ("L3.A 找曾经记录到的 hand_raw / 0x3c 占位符字段（dump 哪局是 obscured 的）",
     "find /opt/mahjong-remote -name '*.jsonl' -mtime -3 2>/dev/null "
     "| xargs -I{} sh -c 'echo \"== {} ==\"; grep -hE \"hand_raw|0x3c|HIDDEN_TILE|untrusted_hand_raw_candidate\" {} 2>/dev/null | head -5' "
     "| head -80"),

    ("L3.B noconfig 抓过的 0x2BC0 game_event sub 类型分布",
     "find /opt/mahjong-remote -name '*.jsonl' -mtime -3 2>/dev/null "
     "| head -3 "
     "| xargs -I{} sh -c 'echo \"== {} ==\"; grep -hoE \"sub_name\\\":\\\"[a-z_]+\" {} 2>/dev/null | sort | uniq -c | sort -rn | head -20'"),

    ("L4 m_SeeRule 字面量（如果你抓过 TableInfo/CreateTable 的服务端响应）",
     "find /opt/mahjong-remote -name '*.jsonl' -o -name '*.log' -mtime -7 2>/dev/null "
     "| xargs grep -ahE 'SeeRule|m_SeeRule|seerule' 2>/dev/null | head -20 || echo '(no hits)'"),

    ("L5.A nManagerRight / nUserRight 字面",
     "find /opt/mahjong-remote -name '*.jsonl' -o -name '*.log' -mtime -7 2>/dev/null "
     "| xargs grep -ahE 'ManagerRight|UserRight|nManagerRight|nUserRight' 2>/dev/null | head -20 || echo '(no hits)'"),

    ("L5.B teahouse summary 在日志里出现过吗（有就有 nTeaOwnerNumid 的 dump）",
     "journalctl --no-pager -u mahjong-relay-noconfig -u mahjong-tcp-proxy --since '7 days ago' 2>/dev/null "
     "| grep -aiE 'TeaHouseSummary|teahouseSummery|nTeaOwnerNumid|TeaOwnerNumid' | head -20 || echo '(no hits)'"),

    ("L6 mitm hotupdate 服务最近 200 行（看是不是有 manifest/NetConf 注入相关的迹象）",
     "journalctl --no-pager -u mahjong-mitm-hotupdate -n 200 2>/dev/null | tail -60 || echo '(unit missing)'"),

    ("L7 pcap 文件清单（拿来本地用 stable 解一遍）",
     "ls -lhS /opt/mahjong-remote/data/pcaps/ 2>/dev/null | head -20 ; "
     "ls -lhS /opt/mahjong-remote/data/captures/ 2>/dev/null | head -20"),

    ("L8 7777 协议 ID 全分布（最近 50000 条匹配）",
     "journalctl --no-pager -u mahjong-relay-noconfig -u mahjong-tcp-proxy --since '24 hours ago' 2>/dev/null "
     "| grep -aoE 'cmd=0x[0-9a-fA-F]+|XY_ID=[0-9]+|sub_cmd=0x[0-9a-fA-F]+' "
     "| sort | uniq -c | sort -rn | head -40"),

    ("L9 端口 5045/5067/5167/5748/5749/5747/7777 的连接拓扑（看有没有第三方旁观者连接）",
     "ss -tnp 2>/dev/null | grep -E ':(7777|5045|5067|5167|5748|5749|5747) ' | head -30"),

    ("L10 现在跑着的服务清单",
     "systemctl list-units --type=service --state=running 2>/dev/null | grep -iE 'mahjong|mitm|relay|noconfig|tcp_proxy|spectator' | head -20"),
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
    print(f"[connect] {USER}@{HOST}:{PORT} ...")
    ssh.connect(HOST, PORT, USER, PASSWORD, timeout=15,
                allow_agent=False, look_for_keys=False)

    findings = []
    for title, cmd in PROBES:
        print(f"\n========= {title} =========")
        try:
            rc, out, err = run(ssh, cmd)
        except Exception as e:
            print(f"[ssh-error] {e}")
            findings.append((title, "[ssh-error]\n" + str(e)))
            continue
        print(out.rstrip())
        if err.strip():
            print(f"[stderr] {err.rstrip()}")
        findings.append((title, out + (("\n[stderr]\n" + err) if err.strip() else "")))

    ssh.close()

    # 把结果落到 task 研究目录
    out_dir = Path(__file__).resolve().parents[1] / ".trellis" / "tasks" / "06-19-friend-watch-handcards-sweep" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "ecs_log_sweep.md"
    with out_file.open("w", encoding="utf-8") as f:
        f.write("# ECS log sweep — 加好友→看对手手牌 路径证据\n\n")
        for title, body in findings:
            f.write(f"## {title}\n\n```\n{body.rstrip()}\n```\n\n")
    print(f"\n[write] {out_file}")


if __name__ == "__main__":
    sys.exit(main() or 0)
