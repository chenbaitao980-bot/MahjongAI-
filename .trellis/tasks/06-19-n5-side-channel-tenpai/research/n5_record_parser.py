"""N5 record event parser.

Reverse-engineered record format (offline replay sample, NOT wire frame):

    [ascii_header:32B][sub_cmd:2B LE][data_len:2B LE][body:data_len][trailer]

The ascii_header is 32 decimal-digit bytes: '0000000000' + '<10-digit ts>' +
'0112' + '00000000'. The 10-digit field is a unix-second timestamp, giving us
real per-event timing (a side-channel input). Events are walked by anchoring on
this 32B all-digit header immediately preceding a known sub_cmd, which cleanly
disambiguates the high-frequency 0x0206 stat_update spam.

Pure offline. Reuses stable.protocol.stable_tile_id only for decoding.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from stable.protocol import GAME_SUB_NAMES, HIDDEN_TILE, stable_tile_id  # noqa: E402

DRAW_CONCEALED_MARKER = 0x72
HEADER_LEN = 32
KNOWN_SUBS = set(GAME_SUB_NAMES.keys())


@dataclass
class RecordEvent:
    seq: int
    offset: int
    ts: int
    sub_cmd: int
    sub_name: str
    body_len: int
    body_hex: str
    player: int | None = None
    tile_or_count: dict[str, Any] = field(default_factory=dict)
    body: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "seq": self.seq,
            "offset": self.offset,
            "ts": self.ts,
            "sub_cmd": f"0x{self.sub_cmd:04x}",
            "sub_name": self.sub_name,
            "body_len": self.body_len,
            "body_hex": self.body_hex,
        }
        if self.player is not None:
            d["player"] = self.player
        if self.tile_or_count:
            d["tile_or_count"] = self.tile_or_count
        return d


def _ascii_header_ts(chunk: bytes) -> int | None:
    """Return the 10-digit timestamp if chunk is a valid 32B all-digit header."""
    if len(chunk) != HEADER_LEN:
        return None
    if not all(0x30 <= b <= 0x39 for b in chunk):
        return None
    try:
        return int(chunk[10:20])
    except ValueError:
        return None


def _player_byte(sub_cmd: int, body: bytes) -> int | None:
    """body[0] is the actor for discard/draw/meld/hand_update/win."""
    if not body:
        return None
    if sub_cmd in (0x021A, 0x021B, 0x021F, 0x0216, 0x0220, 0x0016):
        p = int(body[0])
        return p if p <= 3 else None
    return None


def _tile_or_count(sub_cmd: int, body: bytes) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if sub_cmd == 0x021B and len(body) >= 2:  # discard
        raw = int(body[1])
        info["tile_raw"] = f"0x{raw:02x}"
        info["tile"] = stable_tile_id(raw)
    elif sub_cmd == 0x021A and len(body) >= 2:  # draw
        raw = int(body[1])
        info["concealed"] = raw == DRAW_CONCEALED_MARKER
        if raw not in (0, HIDDEN_TILE, DRAW_CONCEALED_MARKER):
            info["tile_raw"] = f"0x{raw:02x}"
            info["tile"] = stable_tile_id(raw)
    elif sub_cmd == 0x0216 and len(body) >= 3:  # hand_update
        info["count"] = int(body[2])
    elif sub_cmd == 0x021F:  # meld -> expose exposed tiles
        exposed = [int(b) for b in body[4:9]]
        info["exposed_raw"] = [f"0x{b:02x}" for b in exposed]
        info["exposed_tiles"] = [stable_tile_id(b) for b in exposed]
    elif sub_cmd == 0x0003 and len(body) >= 13:  # deal (own hand, untrusted)
        info["deal_first13_raw"] = [f"0x{b:02x}" for b in body[:13]]
    return info


def parse_record(data: bytes) -> list[RecordEvent]:
    """Walk the record event stream anchored on the 32B ascii header."""
    events: list[RecordEvent] = []
    off = 0
    seq = 0
    n = len(data)
    while off + 4 <= n:
        if off < HEADER_LEN:
            off += 1
            continue
        sub_cmd = struct.unpack("<H", data[off : off + 2])[0]
        body_len = struct.unpack("<H", data[off + 2 : off + 4])[0]
        if (
            sub_cmd in KNOWN_SUBS
            and body_len < 1024
            and off + 4 + body_len <= n
        ):
            ts = _ascii_header_ts(data[off - HEADER_LEN : off])
            if ts is not None:
                body = data[off + 4 : off + 4 + body_len]
                ev = RecordEvent(
                    seq=seq,
                    offset=off,
                    ts=ts,
                    sub_cmd=sub_cmd,
                    sub_name=GAME_SUB_NAMES.get(sub_cmd, f"sub_{sub_cmd:#06x}"),
                    body_len=body_len,
                    body_hex=body[:48].hex(),
                    player=_player_byte(sub_cmd, body),
                    tile_or_count=_tile_or_count(sub_cmd, body),
                    body=body,
                )
                events.append(ev)
                seq += 1
                off += 4 + body_len
                continue
        off += 1
    return events


def parse_file(path: str) -> list[RecordEvent]:
    return parse_record(Path(path).read_bytes())


def _main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("usage: python n5_record_parser.py <record.bin>")
        return
    events = parse_file(argv[1])
    from collections import Counter

    hist = Counter(e.sub_name for e in events)
    print(f"== total events: {len(events)} ==")
    for name in sorted(hist):
        print(f"  {name:16s} x{hist[name]}")

    # player-split for actor events
    print("\n== player split (actor events) ==")
    for tag, subs in (("discard", {0x021B}), ("draw", {0x021A}),
                      ("meld", {0x021F}), ("hand_update", {0x0216})):
        p0 = sum(1 for e in events if e.sub_cmd in subs and e.player == 0)
        p1 = sum(1 for e in events if e.sub_cmd in subs and e.player == 1)
        print(f"  {tag:12s} self(0)={p0}  opp(1)={p1}")

    print("\n== first 30 events ==")
    for e in events[:30]:
        extra = ""
        if e.player is not None:
            extra += f" player={e.player}"
        if e.tile_or_count:
            extra += f" {e.tile_or_count}"
        print(f"  seq={e.seq:3d} @{e.offset:5d} ts={e.ts} {e.sub_name:16s}"
              f" len={e.body_len:3d}{extra}")


if __name__ == "__main__":
    _main(sys.argv)
