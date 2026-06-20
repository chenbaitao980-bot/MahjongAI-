"""verify_seed_hypothesis.py
Final offline test: does ANY 4/8-byte high-entropy value in round_start
repeat identically across the two captured games? A shared shuffle seed/
constant would show up as a stable high-entropy value. Player numids are
expected to repeat (same accounts); a SEED would be game-unique.
Pure offline, ASCII only.
"""
import struct

def walk(data):
    out = []; off = 0; n = len(data)
    KS = {0x0003,0x0004,0x0016,0x0206,0x0208,0x0216,0x0218,0x021a,
          0x021b,0x021f,0x0220,0x022b,0x4e88}
    while off + 4 <= n:
        sc = int.from_bytes(data[off:off+2], "little")
        ln = int.from_bytes(data[off+2:off+4], "little")
        if sc in KS and 0 < ln <= 4096 and off + 4 + ln <= n:
            out.append((off, sc, data[off+4:off+4+ln])); off += 4 + ln
        else:
            off += 1
    return out

SAMPLES = {
    "26k": r".trellis\tasks\archive\2026-06\06-19-render-opponent-handcards-on-page\research\sample_record_26k.bin",
    "33k": r".trellis\tasks\archive\2026-06\06-19-render-opponent-handcards-on-page\research\sample_record_33k_before_round.bin",
}

def high_entropy_u32s(b):
    vals = set()
    for i in range(0, len(b) - 3):
        v = int.from_bytes(b[i:i+4], "little")
        # crude entropy filter: not tiny, not 0xff-runs, has >=3 distinct bytes
        bs = b[i:i+4]
        if len(set(bs)) >= 3 and v > 0x10000 and v != 0xffffffff:
            vals.add(v)
    return vals

for tag, p in SAMPLES.items():
    data = open(p, "rb").read()
    fr = walk(data)
    rs = [b for o, s, b in fr if s == 0x0004 and len(b) > 50]
    print(f"[{tag}] full round_start frames: {len(rs)}")
    allv = set()
    for b in rs:
        allv |= high_entropy_u32s(b)
    globals()[f"set_{tag}"] = allv
    print(f"  distinct high-entropy u32 candidates: {len(allv)}")

common = set_26k & set_33k  # noqa: F821
print(f"\nHigh-entropy u32 values appearing in BOTH games: {len(common)}")
for v in sorted(common):
    print(f"  0x{v:08x} ({v})")
print("\nNote: shared values are expected to be PLAYER NUMIDs / avatar-url bytes")
print("(same accounts in both games), NOT a shuffle seed. A per-game seed")
print("would appear in only ONE game's set.")
