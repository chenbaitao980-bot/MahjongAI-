"""D22 verification: dump ALL wire frame types (incl. non-0x2BC0) from main-account
live 7777 pcaps, and scan every non-game-event frame body for opponent hand_raw blocks.

Hypothesis (D22): at round start, the server may push the full table roster
(player_detail / player_info / unknown_0f / round_start) containing opponents' hand_raw,
which the client caches but the UI never renders. If true => H16 (server view filter) is
bypassed on the main account's own real-time stream.

Pass criterion: ANY non-game frame body contains >=1 contiguous 13-byte block of
legal opponent tile values that is NOT 0x3c placeholder / 0x72 mask AND not an ASCII
text run (IP / nickname / avatar URL). 4-player game => possibly 2-3 such blocks.

Offline, read-only. Reuses stable.protocol without modifying it.
Use: python .trellis/tasks/.../research/d22_frame_dump.py
"""
from __future__ import annotations

import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stable.protocol import (  # noqa: E402
    HDR_LEN,
    MSG_TYPES,
    GAME_SUB_NAMES,
    HIDDEN_TILE,
    DRAW_CONCEALED_MARKER,
    PcapParser,
    instance_tile_index,
    stable_tile_id,
)

PORT = 7777

PCAPS = [
    "data/phone_7777.pcap",
    "data/stable_reader/raw_20260517_193242.pcap",
    "data/stable_reader/raw_20260517_195618.pcap",
    "data/stable_reader/raw_20260517_195549.pcap",
]

PHONE_FULL = "data/phone_full.pcap"
PHONE_FULL_BYTE_CAP = 8 * 1024 * 1024  # only read first 8 MB


def is_legal_stable_tile(v: int) -> bool:
    return stable_tile_id(int(v)) is not None


def is_legal_instance_tile(v: int) -> bool:
    return instance_tile_index(int(v)) is not None


def scan_hand_blocks(body: bytes, block: int = 13):
    """Find every <block>-byte window that looks like a REAL opponent hand.

    Returns list of (offset, encoding, [tile_ids]). A window qualifies only if:
      - no 0x3c (HIDDEN) / 0x72 (draw-mask) byte present (that is exactly what H16 leaves)
      - not all-zero / all-0xFF padding
      - NOT an ASCII text run (>=10/13 printable bytes => IP / nickname / avatar URL in
        roster frames; these collide with the instance-id range [1..136] but are not tiles)
      - all bytes legal under one encoding AND >=5 distinct byte values (a real 13-tile
        starting hand has decent diversity, not 13x the same byte)
    """
    hits = []
    n = len(body)
    for off in range(0, n - block + 1):
        win = body[off : off + block]
        if any(b in (HIDDEN_TILE, DRAW_CONCEALED_MARKER) for b in win):
            continue
        if all(b in (0, 0xFF) for b in win):
            continue
        printable = sum(1 for b in win if 32 <= b < 127)
        if printable >= 10:  # ASCII string (IP / nick / URL), not a tile block
            continue
        if all(is_legal_stable_tile(b) for b in win) and len(set(win)) >= 5:
            hits.append((off, "stable", [stable_tile_id(b) for b in win]))
            continue
        if all(is_legal_instance_tile(b) for b in win) and len(set(win)) >= 5:
            hits.append((off, "instance", [instance_tile_index(b) for b in win]))
    return hits


def decode_inner_sub(frame: bytes):
    if len(frame) < HDR_LEN + 4:
        return None
    return struct.unpack("<H", frame[HDR_LEN : HDR_LEN + 2])[0]


def iter_raw_frames(path: Path, port: int, byte_cap: int | None = None):
    """Yield (ts, direction, frame_bytes) for every reassembled wire frame.

    Mirrors MJProtocol.process_packet framing but exposes raw frame bytes so we can
    inspect non-0x2BC0 payloads ourselves (process_packet only decodes 0x2BC0 bodies).
    """
    parser = PcapParser()
    stream_bufs: dict = defaultdict(bytes)
    stream_next_seq: dict = {}
    read = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            read += len(chunk)
            for pkt in parser.feed(chunk):
                src_port = int(pkt["src_port"])
                dst_port = int(pkt["dst_port"])
                if not (src_port == port or dst_port == port):
                    continue
                payload = bytes(pkt["payload"])
                direction = "S->C" if src_port == port else "C->S"
                key = (str(pkt["src"]), str(pkt["dst"]))
                if "seq" in pkt:
                    seq = int(pkt["seq"]) & 0xFFFFFFFF
                    prev = stream_next_seq.get(key)
                    if prev is not None:
                        end = (seq + len(payload)) & 0xFFFFFFFF
                        if _le(end, prev):
                            continue
                        if _lt(seq, prev):
                            off = (prev - seq) & 0xFFFFFFFF
                            payload = payload[off:]
                            seq = prev
                    stream_next_seq[key] = (seq + len(payload)) & 0xFFFFFFFF
                buf = stream_bufs[key] + payload
                ts = float(pkt.get("ts") or 0)
                while len(buf) >= HDR_LEN:
                    if not _looks_like_frame(buf):
                        buf = buf[1:]
                        continue
                    pay_len = struct.unpack("<H", buf[2:4])[0]
                    total = HDR_LEN + pay_len
                    if len(buf) < total:
                        break
                    frame = buf[:total]
                    buf = buf[total:]
                    yield ts, direction, frame
                stream_bufs[key] = buf
            if byte_cap is not None and read >= byte_cap:
                break


def _looks_like_frame(buf: bytes) -> bool:
    if len(buf) < HDR_LEN:
        return False
    if buf[1] not in (0x40, 0x80):
        return False
    return struct.unpack("<H", buf[2:4])[0] <= 65535


def _lt(a: int, b: int) -> bool:
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    return a != b and ((a - b) & 0x80000000) != 0


def _le(a: int, b: int) -> bool:
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    return a == b or _lt(a, b)


def msg_label(msg_type: int) -> str:
    return MSG_TYPES.get(msg_type, f"type_{msg_type:#06x}")


def sub_label(sub: int) -> str:
    return GAME_SUB_NAMES.get(sub, f"sub_{sub:#06x}")


def analyse(path: Path, byte_cap: int | None = None, label: str = ""):
    print("=" * 78)
    print(f"PCAP: {path}  {label}")
    print("=" * 78)

    hist = defaultdict(int)
    first_sample = {}
    nongame = []   # (ts, direction, msg_type, frame)
    timeline = []  # (ts, direction, msg_type, inner_sub, frame_len)

    total_frames = 0
    for ts, direction, frame in iter_raw_frames(path, PORT, byte_cap=byte_cap):
        total_frames += 1
        msg_type = struct.unpack("<H", frame[4:6])[0]
        inner_sub = decode_inner_sub(frame) if msg_type == 0x2BC0 else None
        key = (msg_type, inner_sub)
        hist[key] += 1
        if key not in first_sample:
            first_sample[key] = (len(frame), frame[HDR_LEN:][:128].hex())
        timeline.append((ts, direction, msg_type, inner_sub, len(frame)))
        if msg_type != 0x2BC0:
            nongame.append((ts, direction, msg_type, frame))

    print(f"\ntotal reassembled frames: {total_frames}")
    print("\n-- frame-type histogram (msg_type / inner 0x2BC0 sub_cmd) --")
    for (msg_type, inner_sub), count in sorted(hist.items(), key=lambda kv: -kv[1]):
        flen, bhex = first_sample[(msg_type, inner_sub)]
        if inner_sub is not None:
            name = f"0x2BC0/{sub_label(inner_sub)}({inner_sub:#06x})"
        else:
            name = f"{msg_label(msg_type)}({msg_type:#06x})"
        print(f"  {name:<42} count={count:<5} first_frame_len={flen:<5} "
              f"first_body[:128]={bhex}")

    # ---- non-game-event hand_raw scan ----
    print("\n-- non-0x2BC0 frame body scan for REAL 13B opponent hand blocks --")
    big_nongame = 0
    hand_hits_total = 0
    seen_types = defaultdict(int)
    for ts, direction, msg_type, frame in nongame:
        body = frame[HDR_LEN:]
        seen_types[msg_type] += 1
        if len(body) > 50:
            big_nongame += 1
        hits = scan_hand_blocks(body)
        if hits:
            hand_hits_total += len(hits)
            print(f"  [HIT] ts={ts:.3f} dir={direction} "
                  f"{msg_label(msg_type)}({msg_type:#06x}) body_len={len(body)}")
            for off, enc, tiles in hits[:6]:
                print(f"        off={off} enc={enc} tiles={tiles}")
            print(f"        full_body_hex={body[:160].hex()}")
    print(f"\n  non-game frame types seen: "
          f"{ {msg_label(t): c for t, c in seen_types.items()} }")
    print(f"  big (>50B) non-game frames: {big_nongame}")
    print(f"  REAL 13B hand-block hits in non-game frames: {hand_hits_total}")

    # ---- round-start neighbourhood dump ----
    print("\n-- frames around deal/round_start (0x2BC0 sub 0x0003/0x0004) --")
    deal_idx = [
        i for i, (_, _, mt, sub, _) in enumerate(timeline)
        if mt == 0x2BC0 and sub in (0x0003, 0x0004)
    ]
    if not deal_idx:
        print("  (no deal/round_start frame seen in this pcap)")
    for di in deal_idx[:3]:
        lo = max(0, di - 8)
        hi = min(len(timeline), di + 4)
        print(f"  --- window around timeline idx {di} ---")
        for j in range(lo, hi):
            ts, direction, mt, sub, flen = timeline[j]
            marker = " <== DEAL/ROUND_START" if j == di else ""
            nm = f"0x2BC0/{sub_label(sub)}" if mt == 0x2BC0 else msg_label(mt)
            print(f"    idx={j:<5} ts={ts:.3f} {direction} {nm:<30} "
                  f"frame_len={flen}{marker}")

    return {
        "frames": total_frames,
        "hand_hits": hand_hits_total,
        "big_nongame": big_nongame,
        "nongame_types": dict(seen_types),
    }


def main():
    summary = {}
    for p in PCAPS:
        path = REPO_ROOT / p
        if not path.exists() or path.stat().st_size == 0:
            print(f"SKIP missing/empty: {p}")
            continue
        summary[p] = analyse(path)

    pf = REPO_ROOT / PHONE_FULL
    if pf.exists():
        summary[PHONE_FULL] = analyse(
            pf, byte_cap=PHONE_FULL_BYTE_CAP,
            label=f"(first {PHONE_FULL_BYTE_CAP // (1024*1024)} MB only)",
        )

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for p, s in summary.items():
        verdict = "REAL HAND BLOCK FOUND" if s["hand_hits"] else "no opponent hand block"
        print(f"  {p}: frames={s['frames']} nongame_big={s['big_nongame']} "
              f"real_hand_hits={s['hand_hits']} => {verdict}")


if __name__ == "__main__":
    main()
