"""Diagnostic: scan existing pcaps for a decryptable bidirectional SRS handshake.

Answers the gating question for flag=41 closure: do any captured pcaps already
contain BOTH directions of one SRS handshake (S->C HandshakeRsp msg=4 to derive
the session key, AND C->S PlayerConnect msg=5 to decrypt the pwd/sessionid)?

If yes -> we already have a live sample, no phone capture needed.
If no  -> we need a fresh bidirectional live capture.

Read-only. Throwaway diagnostic, safe to delete.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stable.protocol import MJProtocol, PcapParser
from remote.extractor.token_extractor import SRSSessionExtractor

CANDIDATES = [
    "data/phone_7777.pcap",
    "data/phone_srs.pcap",
    "data/srs_capture.pcap",
    "data/srs_capture_any.pcap",
    "data/phone_full.pcap",
]

# SRS handshake msg types of interest
MSG_HANDSHAKE_RSP = 4   # S->C, carries session key
MSG_PLAYER_CONNECT = 5  # C->S, carries pwd (= sessionid)
MSG_ENCRYPT_VER = 1
MSG_REQ_KEY = 3
MSG_PLAYER_DATA = 6


def scan(path: Path, port: int = 7777) -> None:
    parser = PcapParser()
    proto = MJProtocol(server_port=port)

    captured = {"sessionid": None, "session_key_seen": False}

    def on_sid(pwd: bytes):
        captured["sessionid"] = pwd.hex()

    srs = SRSSessionExtractor(on_sessionid=on_sid)

    total = cs = sc = 0
    msg_types_cs: dict[int, int] = {}
    msg_types_sc: dict[int, int] = {}
    has_hs_rsp_sc = False
    has_pc_cs = False

    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                for pkt in parser.feed(chunk):
                    for msg in proto.process_packet(pkt):
                        total += 1
                        d = getattr(msg, "direction", "")
                        mt = getattr(msg, "msg_type", 0) or 0
                        if d == "C->S":
                            cs += 1
                            msg_types_cs[mt] = msg_types_cs.get(mt, 0) + 1
                            if mt == MSG_PLAYER_CONNECT:
                                has_pc_cs = True
                        elif d == "S->C":
                            sc += 1
                            msg_types_sc[mt] = msg_types_sc.get(mt, 0) + 1
                            if mt == MSG_HANDSHAKE_RSP:
                                has_hs_rsp_sc = True
                        # peek if session key got derived
                        srs.feed(msg)
                        if srs._session_key is not None:
                            captured["session_key_seen"] = True
    except FileNotFoundError:
        print(f"\n### {path}  -- NOT FOUND")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"\n### {path}  -- ERROR: {type(exc).__name__}: {exc}")
        return

    size_mb = path.stat().st_size / (1 << 20)
    print(f"\n### {path}  ({size_mb:.1f} MB)")
    print(f"  messages: total={total}  C->S={cs}  S->C={sc}")
    print(f"  HandshakeRsp(msg=4,S->C) present: {has_hs_rsp_sc}")
    print(f"  PlayerConnect(msg=5,C->S) present: {has_pc_cs}")
    # show the early handshake msg types we care about
    interesting = {1: "EncryptVer", 3: "ReqKey", 4: "HandshakeRsp",
                   5: "PlayerConnect", 6: "PlayerData"}
    cs_str = ", ".join(f"{interesting.get(k, hex(k))}={msg_types_cs[k]}"
                       for k in sorted(msg_types_cs) if k in interesting)
    sc_str = ", ".join(f"{interesting.get(k, hex(k))}={msg_types_sc[k]}"
                       for k in sorted(msg_types_sc) if k in interesting)
    print(f"  C->S handshake msgs: {cs_str or '(none)'}")
    print(f"  S->C handshake msgs: {sc_str or '(none)'}")
    print(f"  >> session_key derived: {captured['session_key_seen']}")
    print(f"  >> SESSIONID (pwd) extracted: {captured['sessionid'] or 'NO'}")


def main() -> int:
    print("=" * 70)
    print("SRS sample diagnostic — scanning for decryptable bidirectional handshake")
    print("=" * 70)
    for c in CANDIDATES:
        scan(REPO_ROOT / c)
    print("\n" + "=" * 70)
    print("VERDICT: a usable sample needs BOTH 'HandshakeRsp(S->C) present: True'")
    print("AND 'SESSIONID extracted: <hex>'. If no pcap shows both, a fresh")
    print("bidirectional live capture is required.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
