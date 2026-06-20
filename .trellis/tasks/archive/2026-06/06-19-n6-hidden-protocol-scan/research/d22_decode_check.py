"""D22 deep-dive: dump FULL round_start / deal bodies, and decode each false-positive
'hand block' candidate to prove what those bytes actually are (IP strings / protobuf).

Offline, read-only. Run after d22_frame_dump.py.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stable.protocol import HDR_LEN, MJProtocol, PcapParser  # noqa: E402

PORT = 7777


def iter_frames(path: Path):
    parser = PcapParser()
    proto = MJProtocol(server_port=PORT)
    # reuse process_packet but we want raw frames; re-do minimal framing
    stream_bufs = {}
    stream_next = {}
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            for pkt in parser.feed(chunk):
                sp, dp = int(pkt["src_port"]), int(pkt["dst_port"])
                if not (sp == PORT or dp == PORT):
                    continue
                payload = bytes(pkt["payload"])
                key = (str(pkt["src"]), str(pkt["dst"]))
                buf = stream_bufs.get(key, b"") + payload
                while len(buf) >= HDR_LEN:
                    if buf[1] not in (0x40, 0x80):
                        buf = buf[1:]
                        continue
                    plen = struct.unpack("<H", buf[2:4])[0]
                    total = HDR_LEN + plen
                    if len(buf) < total:
                        break
                    frame = buf[:total]
                    buf = buf[total:]
                    yield frame
                stream_bufs[key] = buf


def show_ascii(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


def main():
    path = REPO_ROOT / "data/stable_reader/raw_20260517_193242.pcap"
    print(f"PCAP: {path}\n")
    for frame in iter_frames(path):
        mt = struct.unpack("<H", frame[4:6])[0]
        body = frame[HDR_LEN:]
        if mt == 0x2BC0:
            sub = struct.unpack("<H", body[0:2])[0]
            if sub in (0x0003, 0x0004):  # deal / round_start
                inner = body[4:]
                print(f"== 0x2BC0 sub={sub:#06x} ({'deal' if sub==3 else 'round_start'}) "
                      f"inner_len={len(inner)} ==")
                print(f"  hex={inner.hex()}")
                print(f"  ascii={show_ascii(inner)}")
                # highlight 0x3c runs
                runs = inner.count(0x3c)
                print(f"  0x3c (HIDDEN placeholder) byte count in body = {runs}")
                print()
        elif mt == 0x0007:  # room_info -> prove the 'hit' bytes are an IP string
            print(f"== room_info(0x0007) body_len={len(body)} ==")
            print(f"  hex={body.hex()}")
            print(f"  ascii={show_ascii(body)}")
            print(f"  -> bytes at offset 29.. = {show_ascii(body[29:])!r}")
            print()
        elif mt == 0xC355:  # the other 'hit'
            print(f"== type_0xc355 body_len={len(body)} (player roster protobuf) ==")
            print(f"  ascii={show_ascii(body)}")
            print()


if __name__ == "__main__":
    main()
