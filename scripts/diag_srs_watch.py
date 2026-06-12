"""Diagnostic: after flag=0 auth, does the server push the live board to US?

Completes the FULL SRS handshake against the live server using the freshly
captured 80B PlayerConnect template (scripts/_srs_capture.json):
  EncryptVer -> ReqKey -> HandshakeRsp -> PlayerConnect(flag=0)
  -> ReqPlayerPlusData(23) -> RespPlayerPlusData(24, m_key)
Then LISTENS for N seconds and logs every S->C frame, flagging game-data
frames (0x2bc0/0x2bc1). This answers the make-or-break question for the
"one-time hotspot -> cloud shows the board" goal: does an independent authed
connection actually receive the user's live game data?

Throwaway diagnostic. Connects as the user's own account (may kick the phone).
"""
from __future__ import annotations

import socket
import sys
import time
import json
from collections import Counter
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
LISTEN_SECONDS = 20

_cap = REPO_ROOT / "scripts" / "_srs_capture.json"
_rec = json.loads(_cap.read_text(encoding="utf-8"))
PC_PLAIN = bytes.fromhex(_rec["template_hex"])
print(f"[fresh template pwd={_rec['pwd']} ts={_rec.get('ts')}]")


def _enc(key):
    return Cipher(algorithms.AES(key), CFB(IV)).encryptor()


def _dec(key):
    return Cipher(algorithms.AES(key), CFB(IV)).decryptor()


def main() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((HOST, PORT))
    print(f"connected {HOST}:{PORT}")
    s.sendall(pack_frame(1, _enc(KEY).update(b"\x01\x00\x00\x00")))

    session_key = None
    buf = bytearray()
    s.settimeout(2)
    sent_reqkey = sent_pc = sent_plus = False
    auth_flag = None
    msg_counter = Counter()
    deadline = time.time() + 12  # handshake phase deadline
    listen_until = None

    while True:
        now = time.time()
        if listen_until is None and now > deadline:
            print("handshake did not complete in time")
            break
        if listen_until is not None and now > listen_until:
            print(f"\nlisten window ({LISTEN_SECONDS}s) elapsed")
            break
        try:
            data = s.recv(65536)
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
            name = MSG_NAMES.get(mt, f"0x{mt:04x}")
            msg_counter[mt] += 1

            if mt == 1 and not sent_reqkey:
                s.sendall(pack_frame(3, b""))
                sent_reqkey = True
            elif mt == 4 and not sent_pc:
                hs = _dec(KEY).update(pl)
                session_key = hs[1:1 + hs[0]]
                s.sendall(pack_frame(5, _enc(session_key).update(PC_PLAIN)))
                sent_pc = True
                print(f"-> PlayerConnect sent (session_key {session_key.hex()[:16]}...)")
            elif mt == 6:
                pd = _dec(session_key).update(pl)
                auth_flag = pd[0] if pd else -1
                print(f"<- PlayerData flag={auth_flag}", "SUCCESS" if auth_flag == 0 else "")
                if auth_flag == 0 and not sent_plus:
                    s.sendall(pack_frame(23, b""))  # ReqPlayerPlusData
                    sent_plus = True
                    print("-> ReqPlayerPlusData")
                elif auth_flag != 0:
                    print("auth failed, stop")
                    deadline = 0
            elif mt == 24:
                _ = _dec(session_key).update(pl)
                print(f"<- RespPlayerPlusData ({len(pl)}B) — handshake complete")
                print("   === entering LISTEN window; watching for game frames ===")
                listen_until = time.time() + LISTEN_SECONDS
            else:
                tag = ""
                if mt in (0x2bc0, 0x2bc1):
                    tag = "  <-- GAME DATA FRAME!"
                print(f"<- {name} ({len(pl)}B) {pl[:24].hex()}{tag}")

    s.close()
    print("\n=== frame tally ===")
    for mt, c in msg_counter.most_common():
        print(f"  {MSG_NAMES.get(mt, f'0x{mt:04x}')}: {c}")
    got_game = any(mt in (0x2bc0, 0x2bc1) for mt in msg_counter)
    print("\nVERDICT:",
          "GAME DATA RECEIVED on the cloud-style connection (OK)" if got_game
          else "no 0x2bc0/0x2bc1 game frames — board NOT pushed to this connection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
