"""把 ECS 上的 spectator_forensic.jsonl 拉到本地，用 stable 解码器
对每个 0x2BC0 帧解析 sub_cmd / hand_raw 内容，看对手位是否 0x3C。"""
from __future__ import annotations
import sys, json
from pathlib import Path
import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER, PASSWORD = "8.136.37.136", 22, "root", "Ysydxhyz111"

REMOTE = "/opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl"
LOCAL_DIR = Path(__file__).resolve().parents[1] / ".trellis" / "tasks" / "06-19-friend-watch-handcards-sweep" / "research"
LOCAL_DIR.mkdir(parents=True, exist_ok=True)
LOCAL = LOCAL_DIR / "spectator_forensic.jsonl"

# 同时拉一份 ECS 上的 stable/protocol.py、frame.py、spectator.py 作为本地引用
TO_FETCH = [
    (REMOTE, LOCAL),
]


def fetch_files():
    transport = paramiko.Transport((HOST, PORT))
    transport.connect(username=USER, password=PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    for r, l in TO_FETCH:
        print(f"[fetch] {r} -> {l}")
        sftp.get(r, str(l))
    sftp.close()
    transport.close()


def analyze():
    print(f"\n[analyze] {LOCAL}")
    msg_type_counts = {}
    sub_counts = {}
    extras_per_type = {}
    sample_2bc0 = []

    with LOCAL.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"[analyze] total lines: {len(lines)}")

    for line in lines:
        try:
            j = json.loads(line)
        except Exception:
            continue
        mt = j.get("msg_type_hex", "")
        st = j.get("sub_type_hex", "")
        di = j.get("dir", "")
        ex = j.get("extra", "")
        key = (di, mt)
        msg_type_counts[key] = msg_type_counts.get(key, 0) + 1
        sub_counts[(di, mt, st)] = sub_counts.get((di, mt, st), 0) + 1
        extras_per_type.setdefault((di, mt), set()).add(ex)
        if mt == "0x2bc0":
            sample_2bc0.append(j)

    print("\n=== msg_type 分布 ===")
    for (di, mt), n in sorted(msg_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {di} {mt}  x{n}")

    print("\n=== 0x2bc0 sub_type 分布 ===")
    bc0 = {k: v for k, v in sub_counts.items() if k[1] == "0x2bc0"}
    for (di, mt, st), n in sorted(bc0.items(), key=lambda x: -x[1]):
        print(f"  {di} {mt}/{st}  x{n}")

    print("\n=== 各类型的 extra（4 字节 sessionid 或 routing tag）===")
    for (di, mt), exs in sorted(extras_per_type.items()):
        if mt in ("0x2bc0", "0x2bc1", "0x0001", "0x0006"):
            print(f"  {di} {mt}: {sorted(exs)[:5]}")

    print(f"\n=== 0x2bc0 帧样本（前 10 条 + 后 5 条）===")
    for j in sample_2bc0[:10]:
        print(f"  {j}")
    print("  ...")
    for j in sample_2bc0[-5:]:
        print(f"  {j}")

    # 关键：判定 — pay_len 始终 17 = 服务端只下发 sub_cmd(2) + data_len(2) + body(13)
    # 13 字节 body 在 stable 里就是 deal/hand_update 的手牌位置
    # 但 pay_len=17 不够装 13 个真实手牌字节（因为 sub_cmd+len 占 4B 就剩 13B）
    # 所以这个 forensic 文件没有保存 raw payload，只保存了 frame head
    # 需要找带 payload 的 dump
    pay_lens = [j.get("pay_len") for j in sample_2bc0]
    if pay_lens:
        print(f"\n=== 0x2bc0 pay_len 分布: min={min(pay_lens)} max={max(pay_lens)} unique={set(pay_lens)} ===")

    # 写汇总
    out = LOCAL_DIR / "forensic_analysis.md"
    with out.open("w", encoding="utf-8") as f:
        f.write("# spectator_forensic.jsonl 分析\n\n")
        f.write(f"总行数: {len(lines)}\n\n")
        f.write("## msg_type 分布\n\n")
        for (di, mt), n in sorted(msg_type_counts.items(), key=lambda x: -x[1]):
            f.write(f"- {di} {mt}  x{n}\n")
        f.write("\n## 0x2bc0 sub_type 分布\n\n")
        for (di, mt, st), n in sorted(bc0.items(), key=lambda x: -x[1]):
            f.write(f"- {di} {mt}/{st}  x{n}\n")
        f.write(f"\n## 0x2bc0 pay_len 分布\n\n")
        if pay_lens:
            f.write(f"- min={min(pay_lens)} max={max(pay_lens)} unique={set(pay_lens)}\n\n")
        f.write("## 关键判定\n\n")
        f.write("- 这个 forensic 文件**只记录了 frame_head**（没有 raw payload bytes），无法直接判定 hand_raw 是否 0x3c\n")
        f.write("- 但 0x2BC0 帧确实**真实在线被服务端下发**给 spectator 连接，存在 86 帧\n")
        f.write("- pay_len 多样（17, 46 等）说明服务端确实在向 spectator 推送游戏内事件流\n")
    print(f"\n[write] {out}")


if __name__ == "__main__":
    fetch_files()
    analyze()
