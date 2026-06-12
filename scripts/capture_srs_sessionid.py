"""Live focused capture: grab a FRESH SRS sessionid + full PlayerConnect template.

Sniffs the Windows hotspot interface (192.168.137.1) for port-7777 SRS traffic,
decrypts HandshakeRsp(msg=4,S->C) -> session key, then PlayerConnect(msg=5,C->S)
-> full 80B plaintext (pwd = live sessionid at offset 22:38).

On each capture it prints the result and rewrites scripts/_srs_capture.json with
{pwd, template_hex, session_key, count}. Keeps running so the LAST handshake (the
freshest reconnect) wins. Ctrl-C / background-stop to end.

Run this WHILE the phone (connected to the PC hotspot) reconnects the game.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
try:
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:
    from cryptography.hazmat.primitives.ciphers.modes import CFB

from stable.protocol import MJProtocol
from remote.extractor.capture import NpcapCaptureAdapter

KEY = bytes.fromhex("f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b")
IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")
OUT = REPO_ROOT / "scripts" / "_srs_capture.json"


def _dec(key: bytes, ct: bytes) -> bytes:
    return Cipher(algorithms.AES(key), CFB(IV)).decryptor().update(ct)


class Capturer:
    def __init__(self):
        self.proto = MJProtocol(server_port=7777)
        self.session_key = None
        self.count = 0

    def on_pkt(self, pkt):
        for m in self.proto.process_packet(pkt):
            raw = bytes.fromhex(m.raw_hex) if m.raw_hex else b""
            if len(raw) < 12:
                continue
            pay = raw[12:]
            mt = getattr(m, "msg_type", 0)
            d = getattr(m, "direction", "")
            if mt == 4 and d == "S->C":
                hs = _dec(KEY, pay)
                if hs and hs[0] in (16, 24, 32) and 1 + hs[0] <= len(hs):
                    self.session_key = hs[1:1 + hs[0]]
                    print(f"[{time.strftime('%H:%M:%S')}] HandshakeRsp -> session_key "
                          f"{self.session_key.hex()} (AES-{hs[0]*8})")
            elif mt == 5 and d == "C->S" and self.session_key is not None:
                pc = _dec(self.session_key, pay)
                if len(pc) < 23:
                    continue
                uid_len = pc[6]
                pwd_start = 7 + uid_len
                if pwd_start + 16 > len(pc):
                    continue
                pwd = pc[pwd_start:pwd_start + 16]
                uid = pc[7:7 + uid_len]
                self.count += 1
                rec = {
                    "pwd": pwd.hex(),
                    "template_hex": pc.hex(),
                    "session_key": self.session_key.hex(),
                    "uid": uid.decode("latin1"),
                    "template_len": len(pc),
                    "count": self.count,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                OUT.write_text(json.dumps(rec, indent=2), encoding="utf-8")
                print(f"\n[{time.strftime('%H:%M:%S')}] *** SESSIONID CAPTURED (#{self.count}) ***")
                print(f"    uid          = {rec['uid']}")
                print(f"    pwd          = {rec['pwd']}")
                print(f"    template({rec['template_len']}B) = {rec['template_hex']}")
                print(f"    -> written to {OUT}\n")


def main() -> int:
    cap = Capturer()
    adapter = NpcapCaptureAdapter(port=7777, interface="any")  # auto-selects hotspot iface
    print("Sniffing hotspot iface for SRS handshake on port 7777 ...")
    print("Now: on the phone, reconnect the game (re-enter lobby / toggle airplane mode).")
    print("Waiting for PlayerConnect ... (Ctrl-C to stop)\n")
    try:
        adapter.run(cap.on_pkt)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        adapter.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
