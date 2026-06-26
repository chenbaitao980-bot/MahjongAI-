"""ECS 三轮探测 — 直接看 spectator_forensic.jsonl 和 srs_spectator 模块的内容"""
from __future__ import annotations
import sys
from pathlib import Path
import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER, PASSWORD = "8.136.37.136", 22, "root", "Ysydxhyz111"

PROBES = [
    ("S1 spectator_forensic.jsonl 大小 + 头尾",
     "ls -lh /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null; "
     "wc -l /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null; "
     "echo '---HEAD---'; head -10 /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null; "
     "echo '---TAIL---'; tail -10 /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null"),

    ("S2 srs_spectator 模块清单",
     "ls -la /opt/mahjong-remote/remote/srs_spectator/ 2>/dev/null; "
     "echo '---'; "
     "wc -l /opt/mahjong-remote/remote/srs_spectator/*.py 2>/dev/null"),

    ("S3 spectator.py 全文（关键文件，可能含订阅/旁观协议实现）",
     "cat /opt/mahjong-remote/remote/srs_spectator/spectator.py 2>/dev/null | head -200"),

    ("S4 decrypt_validate.py 全文",
     "cat /opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py 2>/dev/null | head -200"),

    ("S5 player_connect.py 全文",
     "cat /opt/mahjong-remote/remote/srs_spectator/player_connect.py 2>/dev/null | head -200"),

    ("S6 frame.py 关键部分（看协议解析）",
     "grep -nE 'def |0x|MSG_NAMES|sub_cmd|TILE|hand_raw|0x3c|FriendTable|Realtime|action.*4|SEEGAME' "
     "/opt/mahjong-remote/remote/srs_spectator/frame.py 2>/dev/null | head -50"),

    ("S7 noconfig spectator.py",
     "cat /opt/mahjong-remote/remote/noconfig/spectator.py 2>/dev/null | head -200"),

    ("S8 grep 0x3c / HIDDEN_TILE / opp_hand 全 ECS 代码库",
     "grep -rnE '0x3c|HIDDEN_TILE|opp_hand|opponent_hand|other.*hand|spectator|FriendTable|RealtimeGameRecord|0x2bc0' "
     "/opt/mahjong-remote/remote/ 2>/dev/null | head -60"),

    ("S9 stable/protocol.py 在 ECS 上的版本",
     "grep -nE '0x2bc0|0x022B|sub_cmd|HIDDEN_TILE' "
     "/opt/mahjong-remote/stable/protocol.py 2>/dev/null | head -30"),

    ("S10 spectator_forensic.jsonl 字段名分布",
     "awk -F'\"' 'NR<=200 {for(i=2;i<=NF;i+=2) print $i}' "
     "/opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null "
     "| sort | uniq -c | sort -rn | head -40"),

    ("S11 spectator_forensic.jsonl 任意中间一行（看完整 schema）",
     "sed -n '5p;50p;200p;1000p' /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl 2>/dev/null "
     "| head -4"),

    ("S12 noconfig multiuser app.py 入口",
     "grep -nE 'def |@router|@app|FastAPI|websocket|/push|/subscribe|/watch|/spectator|/admin|forensic' "
     "/opt/mahjong-remote/remote/noconfig/app.py 2>/dev/null | head -50"),
]

def run(ssh, cmd, timeout=60):
    si, so, se = ssh.exec_command(cmd, timeout=timeout)
    rc = so.channel.recv_exit_status()
    return rc, so.read().decode("utf-8", errors="replace"), se.read().decode("utf-8", errors="replace")

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASSWORD, timeout=15, allow_agent=False, look_for_keys=False)

    findings = []
    for title, cmd in PROBES:
        print(f"\n========= {title} =========")
        rc, out, err = run(ssh, cmd)
        body = out.rstrip()
        if err.strip():
            body += "\n[stderr]\n" + err.rstrip()
        print(body)
        findings.append((title, body))
    ssh.close()

    out_dir = Path(__file__).resolve().parents[1] / ".trellis" / "tasks" / "06-19-friend-watch-handcards-sweep" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "ecs_log_sweep_3.md"
    with out_file.open("w", encoding="utf-8") as f:
        f.write("# ECS 三轮 sweep — spectator forensic + 协议代码\n\n")
        for title, body in findings:
            f.write(f"## {title}\n\n```\n{body}\n```\n\n")
    print(f"\n[write] {out_file}")

if __name__ == "__main__":
    sys.exit(main() or 0)
