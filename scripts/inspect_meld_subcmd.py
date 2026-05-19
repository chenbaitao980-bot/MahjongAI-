"""一次性诊断：从 stable events_*.jsonl 找出吃/碰对应的 sub_cmd 及 body 偏移。

策略：
- 找出每条 discard 事件，看后续 3 个事件里哪个候选 sub_cmd 的 body 含有刚被打出的那张牌
- 对每个匹配，打印 body 全文 + 牌位置（用于推断字段偏移）
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stable.protocol import stable_tile_id  # noqa: E402


def main(jsonl_path: str) -> None:
    events = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != 0x2BC0:
                continue
            events.append(obj)

    print(f"total events: {len(events)}")

    # 找所有 discard
    discards = []
    for i, ev in enumerate(events):
        g = ev["game"]
        if g.get("sub_name") == "discard":
            try:
                body = bytes.fromhex(g.get("body_hex", ""))
                actor = int(body[0]) if body else -1
                tile_raw = int(body[1]) if len(body) >= 2 else 0
                discards.append((i, actor, tile_raw))
            except Exception:
                pass
    print(f"discards: {len(discards)}")

    candidates = {
        "sub_0x021d", "sub_0x05dc", "sub_0x0211", "sub_0x0214",
        "sub_0x0215", "sub_0x0212", "sub_0x0202", "sub_0x0224",
        "sub_0x0225", "kong",  # kong 也加进来对比
        "round_start", "sub_0x0217", "sub_0x0218",
    }

    # 对每个 discard，扫紧随其后的 5 个事件
    print("\n=== Candidate body containing the just-discarded tile ===")
    body_pattern = Counter()  # sub_name → 出现次数（body 含 tile）
    body_offsets = defaultdict(Counter)  # sub_name → offset → 次数
    body_samples = defaultdict(list)
    for d_idx, d_actor, d_tile in discards:
        for delta in range(1, 6):
            j = d_idx + delta
            if j >= len(events):
                break
            sn = events[j]["game"].get("sub_name", "")
            if sn not in candidates:
                continue
            try:
                body = bytes.fromhex(events[j]["game"].get("body_hex", ""))
            except Exception:
                continue
            # 找 d_tile 在 body 中的所有出现位置
            positions = [k for k in range(len(body)) if body[k] == d_tile]
            if not positions:
                continue
            body_pattern[sn] += 1
            for pos in positions:
                body_offsets[sn][pos] += 1
            if len(body_samples[sn]) < 5:
                body_samples[sn].append(
                    (d_idx, d_actor, d_tile, j, delta, body.hex(), positions)
                )

    print(f"{'sub_name':<14} {'count':>6}  offsets")
    for sn, cnt in body_pattern.most_common():
        offs = ", ".join(f"pos={p}({c})" for p, c in body_offsets[sn].most_common(5))
        print(f"{sn:<14} {cnt:>6}  {offs}")

    print("\n=== Samples ===")
    for sn, samples in body_samples.items():
        print(f"\n--- {sn} ---")
        for d_idx, d_actor, d_tile, j, delta, hx, positions in samples:
            print(f"  discard@{d_idx} actor={d_actor} tile=0x{d_tile:02x} → @{j} (delta={delta})")
            print(f"    body={hx}")
            print(f"    tile positions: {positions}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/stable_reader/events_20260519_192721.jsonl"
    main(path)
