"""RNG/seed/wall recon sweep v2 - correct record framing.
Frame: [ascii-digit header][sub_cmd:2B LE][len:2B LE][body]
Headers are variable-length ASCII digit runs. We anchor on known sub_cmd+len.
Pure offline, ASCII only.
"""
import struct
import sys

SAMPLES = {
    "26k": r".trellis\tasks\archive\2026-06\06-19-render-opponent-handcards-on-page\research\sample_record_26k.bin",
    "33k": r".trellis\tasks\archive\2026-06\06-19-render-opponent-handcards-on-page\research\sample_record_33k_before_round.bin",
}

SUB_NAMES = {
    0x0003: "deal", 0x0004: "round_start", 0x0016: "action_notify",
    0x0206: "stat_update", 0x0208: "stat_update2", 0x0216: "hand_update",
    0x0218: "baida_update", 0x021A: "draw", 0x021B: "discard",
    0x021F: "meld", 0x0220: "win", 0x022B: "round_result", 0x4E88: "player_info",
}
KNOWN_SUBS = set(SUB_NAMES)


def walk(data):
    """Scan for [sub_cmd LE][len LE][body] where sub_cmd is known and len plausible.
    Headers (ascii digits) separate frames; we slide until a valid frame appears."""
    out = []
    off = 0
    n = len(data)
    while off + 4 <= n:
        sc = int.from_bytes(data[off:off+2], "little")
        ln = int.from_bytes(data[off+2:off+4], "little")
        if sc in KNOWN_SUBS and 0 < ln <= 4096 and off + 4 + ln <= n:
            body = data[off+4:off+4+ln]
            out.append((off, sc, body))
            off += 4 + ln
        else:
            off += 1
    return out


def hd(b, base=0):
    lines = []
    for i in range(0, len(b), 16):
        c = b[i:i+16]
        hx = " ".join(f"{x:02x}" for x in c)
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in c)
        lines.append(f"  +{base+i:04d} {hx:<47} {asc}")
    return "\n".join(lines)


def read_lpstr(b, off):
    """1-byte length-prefixed string. Returns (str, next_off)."""
    if off >= len(b):
        return "", off
    ln = b[off]
    s = b[off+1:off+1+ln]
    return s, off + 1 + ln


def main():
    for tag, path in SAMPLES.items():
        try:
            data = open(path, "rb").read()
        except FileNotFoundError:
            print(f"MISSING {path}")
            continue
        print("=" * 78)
        print(f"[{tag}] {path} ({len(data)} bytes)")
        print("=" * 78)
        frames = walk(data)
        counts = {}
        for off, sc, b in frames:
            counts[sc] = counts.get(sc, 0) + 1
        for sc in sorted(counts):
            print(f"  0x{sc:04x} {SUB_NAMES.get(sc,'?'):14} x{counts[sc]}")

        for off, sc, b in frames:
            if sc == 0x0004:
                print("\n----- ROUND_START @%d len=%d -----" % (off, len(b)))
                print(hd(b))
                decode_round_start(b)
            elif sc == 0x0003:
                print("\n----- DEAL @%d len=%d -----" % (off, len(b)))
                print(hd(b))
                h13 = list(b[:13])
                print("  self_hand[:13]=%s has_3c=%s" % (h13, 0x3c in h13))
                print("  tail[13:]=%s" % b[13:].hex())


def decode_round_start(b):
    print("  -- field guess --")
    if len(b) < 8:
        return
    areaid = int.from_bytes(b[0:4], "little")
    print("  +0   areaid_LE = %d (0x%08x)" % (areaid, areaid))
    print("  +4   u32_LE    = %d (0x%08x)  [43958e40]" % (
        int.from_bytes(b[4:8], "little"), int.from_bytes(b[4:8], "little")))
    # scan all u32 LE in first 120 bytes, flag small ints and high-entropy
    print("  -- u32 LE scan (first 120B) --")
    for i in range(0, min(120, len(b) - 3), 4):
        v = int.from_bytes(b[i:i+4], "little")
        tag = ""
        if v in (13, 10, 996, 1000, 7109):
            tag = " <- small/count?"
        if 0x10000000 <= v <= 0xfffffffe and v not in (0xffffffff,):
            tag = " <- HIGH-ENTROPY (seed/numid?)"
        print("    +%-3d %-12d 0x%08x%s" % (i, v, v, tag))


if __name__ == "__main__":
    main()
