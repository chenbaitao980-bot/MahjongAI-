"""Diagnostic: faithfully replay the captured PlayerConnect against the LIVE server.

Connects to the real game server, runs the SRS handshake
(EncryptVer -> ReqKey -> HandshakeRsp), derives a FRESH session key, then
encrypts the EXACT 80-byte PlayerConnect plaintext decoded from phone_srs.pcap
and sends it. Reads PlayerData and prints the auth flag.

Purpose: isolate the flag=41 cause. If a byte-perfect (but stale-credential)
PlayerConnect still returns 41, the only remaining gap is credential freshness.
Any OTHER failure means the wire format is still off.

Throwaway diagnostic — connects to the user's own game account. Safe to delete.
"""
from __future__ import annotations

import socket
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

from remote.srs_spectator.frame import pack_frame, read_frame_from_stream, MSG_NAMES

HOST, PORT = "47.96.0.227", 7777
KEY = bytes.fromhex("f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b")
IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")

# PlayerConnect plaintext (80 bytes). Prefer a freshly-captured template from
# scripts/_srs_capture.json (written by capture_srs_sessionid.py); else fall back
# to the stale one decoded from phone_srs.pcap (pwd a269e12a... -> flag=72).
import json as _json

_STALE = (
    "0207c51b00000f6e6577707431303834333036363738"
    "a269e12a1ca5442db00ec625a0d0e619"
    "0c303230303030303030303030"
    "00000000f4140100b0270000"
    "0c303230303030303030303030"
    "b7bb0d00"
)
_cap = REPO_ROOT / "scripts" / "_srs_capture.json"
if _cap.is_file():
    _rec = _json.loads(_cap.read_text(encoding="utf-8"))
    PC_PLAIN = bytes.fromhex(_rec["template_hex"])
    print(f"[using FRESH captured template: pwd={_rec['pwd']} ts={_rec.get('ts')}]")
else:
    PC_PLAIN = bytes.fromhex(_STALE)
    print("[using STALE template from pcap]")


def _enc(key: bytes):
    return Cipher(algorithms.AES(key), CFB(IV)).encryptor()


def _dec(key: bytes):
    return Cipher(algorithms.AES(key), CFB(IV)).decryptor()


def main() -> int:
    assert len(PC_PLAIN) == 80, f"PC_PLAIN must be 80B, got {len(PC_PLAIN)}"
    print(f"Connecting to {HOST}:{PORT} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((HOST, PORT))
    print("connected")

    # EncryptVer
    ev_ct = _enc(KEY).update(b"\x01\x00\x00\x00")
    sock.sendall(pack_frame(1, ev_ct))
    print(f"-> EncryptVer ct={ev_ct.hex()}")

    session_key = None
    buf = bytearray()
    sock.settimeout(2)
    deadline = time.time() + 12
    sent_reqkey = False
    sent_pc = False

    while time.time() < deadline:
        try:
            data = sock.recv(65536)
        except socket.timeout:
            continue
        if not data:
            print("server closed connection")
            break
        buf += data
        while True:
            frame, buf = read_frame_from_stream(buf)
            if frame is None:
                break
            mt = frame["msg_type"]
            pl = frame["payload"]
            name = MSG_NAMES.get(mt, f"msg_{mt}")
            print(f"<- {name} ({len(pl)}B) {pl[:40].hex()}")

            if mt == 1 and not sent_reqkey:  # EncryptVer echo -> ReqKey
                sock.sendall(pack_frame(3, b""))
                sent_reqkey = True
                print("-> ReqKey")
            elif mt == 4 and not sent_pc:  # HandshakeRsp -> derive key, send PC
                hs = _dec(KEY).update(pl)
                kl = hs[0]
                session_key = hs[1:1 + kl]
                print(f"   session_key({kl}B,AES-{kl*8}) = {session_key.hex()}")
                pc_ct = _enc(session_key).update(PC_PLAIN)
                sock.sendall(pack_frame(5, pc_ct))
                sent_pc = True
                print(f"-> PlayerConnect ({len(PC_PLAIN)}B plain -> {len(pc_ct)}B ct)")
            elif mt == 6:  # PlayerData -> read flag
                if session_key is not None:
                    pd = _dec(session_key).update(pl)
                    flag = pd[0] if pd else -1
                    print(f"   PlayerData plain = {pd.hex()}")
                    print(f"\n   *** PlayerData FLAG = {flag} ***")
                    if flag == 0:
                        print("   >>> AUTH SUCCESS (flag=0)")
                    elif flag == 41:
                        print("   >>> ACCOUNT_ERR (flag=41) — format OK, credential stale/invalid")
                    else:
                        print(f"   >>> other flag {flag}")
                sock.close()
                return 0

    print("\n(no PlayerData received before timeout)")
    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
