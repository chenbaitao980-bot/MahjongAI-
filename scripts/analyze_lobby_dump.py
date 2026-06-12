"""Analyze frida/hook_lobby_key.js output to decide the active-path verdict.

Reads .lobby_dump.jsonl (pulled from the phone) and reports, for the LOBBY layer
(processid 1147) and every other processid seen:
  - the pre-encryption plaintext (from packMsg) per msgid,
  - the REAL AES keys captured (from aes_set_key), distinct values + sizes,
  - whether the game's stored Encryption.objkey was anti-tamper-scrubbed to zeros
    (compares encrypt.objkey vs the real aes_set_key).

Pass TWO dump files (two separate login sessions) to get the decisive verdict:
  - lobby plaintext IDENTICAL across sessions -> stable credential -> REPLAYABLE
    (active path ALIVE: capture plaintext once, re-encrypt with cloud's own key).
  - lobby plaintext DIFFERS  -> per-connection nonce -> NOT replayable (active DEAD).

Usage:
  python scripts/analyze_lobby_dump.py dump1.jsonl
  python scripts/analyze_lobby_dump.py dump1.jsonl dump2.jsonl   # compare 2 sessions
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

LOBBY_PID = 1147


def load(path):
    recs = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    return recs


def summarize(path):
    recs = load(path)
    packs = [r for r in recs if r.get("type") == "packMsg"]
    keys = [r for r in recs if r.get("type") == "aes_set_key"]
    encs = [r for r in recs if r.get("type") == "encrypt"]

    print(f"\n===== {path} =====")
    print(f"records: total={len(recs)} packMsg={len(packs)} aes_set_key={len(keys)} encrypt={len(encs)}")

    # distinct real keys
    distinct_keys = {}
    for k in keys:
        distinct_keys[k.get("key", "")] = (k.get("bits"), distinct_keys.get(k.get("key", ""), (None, 0))[1] + 1)
    print("\n-- distinct REAL AES keys (from AES_set_encrypt_key) --")
    for kv, (bits, cnt) in distinct_keys.items():
        zero = all(c == "0" for c in kv) if kv else True
        print(f"  AES-{bits}  x{cnt}  {kv}{'   <-- ALL ZERO (scrubbed?)' if zero else ''}")

    # objkey scrub check
    scrubbed = sum(1 for e in encs if e.get("objkey") and all(c == "0" for c in e["objkey"]))
    print(f"\n-- Encryption.objkey scrubbed-to-zero on {scrubbed}/{len(encs)} encrypt calls "
          f"(confirms anti-tamper; real key still captured via AES_set_encrypt_key) --")

    # plaintext per processid
    by_pid = defaultdict(lambda: defaultdict(list))
    for p in packs:
        by_pid[p.get("pid")][p.get("msgid")].append(p.get("payload", ""))
    print("\n-- pre-encryption plaintext by processid/msgid --")
    for pid in sorted(by_pid, key=lambda x: (x is None, x)):
        tag = "  <== LOBBY" if pid == LOBBY_PID else ""
        print(f"  processid={pid}{tag}")
        for mid, pls in sorted(by_pid[pid].items(), key=lambda x: (x[0] is None, x[0])):
            uniq = sorted(set(pls))
            print(f"    msgid={mid}: {len(pls)} frame(s), {len(uniq)} distinct")
            for u in uniq[:4]:
                print(f"        {u}")
    return by_pid


def compare(p1, p2):
    print("\n" + "=" * 64)
    print("VERDICT — lobby plaintext stability across the two sessions")
    print("=" * 64)
    lob1 = {mid: sorted(set(pls)) for mid, pls in p1.get(LOBBY_PID, {}).items()}
    lob2 = {mid: sorted(set(pls)) for mid, pls in p2.get(LOBBY_PID, {}).items()}
    if not lob1 or not lob2:
        print("  No lobby (pid=1147) packMsg in one/both dumps — can't compare.")
        return
    for mid in sorted(set(lob1) | set(lob2)):
        a = lob1.get(mid, [])
        b = lob2.get(mid, [])
        same = bool(set(a) & set(b))
        print(f"  msgid={mid}: {'IDENTICAL across sessions -> STABLE (replayable)' if same else 'DIFFERS across sessions -> per-connection nonce (NOT replayable)'}")
        if not same:
            print(f"      session1: {a[:2]}")
            print(f"      session2: {b[:2]}")
    print("\n  If all lobby msgids are STABLE -> active path ALIVE (capture-once + re-encrypt).")
    print("  If any carries per-connection nonce -> active path needs that nonce live -> DEAD for 'any network'.")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    p1 = summarize(argv[1])
    if len(argv) >= 3:
        p2 = summarize(argv[2])
        compare(p1, p2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
