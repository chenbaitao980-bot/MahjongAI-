"""Scan record samples for 0x022B/0x2BC0/0x3c-run markers."""
import re, sys

FILES = [
    ".trellis/tasks/06-19-render-opponent-handcards-on-page/research/sample_record_26k.bin",
    ".trellis/tasks/06-19-render-opponent-handcards-on-page/research/sample_record_33k_before_round.bin",
]

for fn in FILES:
    print("==", fn)
    d = open(fn, "rb").read()
    print(" total=%d" % len(d))
    p022 = [m.start() for m in re.finditer(re.escape(b"\x2b\x02"), d)]
    print(" 0x022b LE markers: %d, first10=%s" % (len(p022), p022[:10]))
    p2bc0 = [m.start() for m in re.finditer(re.escape(b"\xc0\x2b"), d)]
    print(" 0x2bc0 LE markers: %d" % len(p2bc0))
    p3c = [m.start() for m in re.finditer(b"(?:\x3c){4,}", d)]
    print(" 4+ 0x3c runs: %d positions, first10=%s" % (len(p3c), p3c[:10]))
    # Walk the file as a stream of [sub_cmd:2][data_len:2][data] inner frames embedded inside packets.
    # That's too generic; just print first context around 0x022b candidates if present.
    for off in p022[:5]:
        ctx = d[max(0, off - 4):off + 32]
        print(f"  @{off}: prev4+32 = {ctx.hex()}")
