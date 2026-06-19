# ECS 三轮 sweep — spectator forensic + 协议代码

## S1 spectator_forensic.jsonl 大小 + 头尾

```
-rw-r--r-- 1 197108 197121 1.1M Jun 12 21:22 /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl
5904 /opt/mahjong-remote/remote/extractor/spectator_forensic.jsonl
---HEAD---
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "S->C", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "S->C", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
---TAIL---
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "S->C", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "0.0", "dir": "S->C", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 1, "msg_type_hex": "0x0001", "sub_type": 1147, "sub_type_hex": "0x047b", "extra": "00000000", "pay_len": 19, "kind": "frame_head"}
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
```

## S2 srs_spectator 模块清单

```
total 88
drwxr-xr-x 3 197108 197121  4096 Jun 13 20:45 .
drwxr-xr-x 8 197108 197121  4096 Jun 14 17:15 ..
-rw-r--r-- 1 197108 197121 10969 Jun 14 13:45 client.py
-rw-r--r-- 1 197108 197121   314 Jun 11 16:54 config.yaml
-rw-r--r-- 1 197108 197121  5493 Jun 17 08:38 crypto.py
-rw-r--r-- 1 197108 197121 10279 Jun 13 19:56 decrypt_validate.py
-rw-r--r-- 1 197108 197121  3743 Jun 17 08:38 frame.py
-rw-r--r-- 1 197108 197121  6044 Jun 17 10:55 handshake.py
-rw-r--r-- 1 197108 197121   223 Jun 13 19:56 __init__.py
-rw-r--r-- 1 197108 197121  6435 Jun 18 16:36 main.py
-rw-r--r-- 1 197108 197121  2389 Jun 14 13:45 player_connect.py
drwxr-xr-x 2 root   root    4096 Jun 18 16:36 __pycache__
-rw-r--r-- 1 197108 197121    61 Jun 11 17:41 requirements.txt
-rw-r--r-- 1 197108 197121  5952 Jun 13 19:56 spectator.py
---
  256 /opt/mahjong-remote/remote/srs_spectator/client.py
  124 /opt/mahjong-remote/remote/srs_spectator/crypto.py
  275 /opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py
   90 /opt/mahjong-remote/remote/srs_spectator/frame.py
  172 /opt/mahjong-remote/remote/srs_spectator/handshake.py
    7 /opt/mahjong-remote/remote/srs_spectator/__init__.py
  197 /opt/mahjong-remote/remote/srs_spectator/main.py
   73 /opt/mahjong-remote/remote/srs_spectator/player_connect.py
  147 /opt/mahjong-remote/remote/srs_spectator/spectator.py
 1341 total
```

## S3 spectator.py 全文（关键文件，可能含订阅/旁观协议实现）

```
"""Spectator protocol — ReqRealtimeGameRecord.

Requests real-time game record data from the server via the SRS connection.
The server responds with zlib-compressed fragments. After all fragments arrive,
merge and decompress to get the full game record.
"""
import struct
import zlib
import logging

from .frame import pack_frame

logger = logging.getLogger(__name__)

# Protocol message IDs (from IMProtocol.lua / MatchLinkProtocol.lua)
# These are the XY_ID values for spectator messages
# We use IMProtocol by default; the server may use MatchLinkProtocol (watch1006 mode)
# XY_ID 在两套协议里完全相同（3000/3001），区分两套靠 frame 的 processid（100 vs 1006）。
SPECTATOR_REQ_MSGID = 3000   # ReqRealtimeGameRecord, IMProtocol.lua:73 确认值 (0xBB8)
SPECTATOR_RESP_MSGID = 3001  # RespRealtimeGameRecord, IMProtocol.lua:74 (0xBB9)


class SpectatorClient:
    """Handles spectator protocol over an established SRS connection."""

    def __init__(self, send_callback):
        self._send = send_callback  # callback(bytes) → sends raw frame on SRS connection
        self._fragments = {}        # askid → {total, parts: {index: bytes}}
        self._on_record = None      # callback(record_bytes) when complete record arrives

    def on_record(self, callback):
        """Set callback for when a complete game record is received."""
        self._on_record = callback

    def request_record(self, roomid: int, gameid: int, offset: int = 0,
                       askid: int = None, before_round: int = 0) -> int:
        """Request real-time game record.

        Args:
            roomid: Room ID to watch
            gameid: Game ID
            offset: Starting offset (0 for beginning)
            askid: Request ID (auto-generated if None)
            before_round: 1 for replay before current round

        Returns:
            askid used for matching response fragments
        """
        if askid is None:
            import time
            askid = int(time.time()) & 0x7FFFFFFF

        # Build request payload per IMProtocol.ReqRealtimeGameRecord
        # Fields: askid(int32), room_id(int32), offset(int32), before_round(int32)
        payload = struct.pack("<iiii", askid, roomid, offset, before_round)

        # The actual msgid for spectator request depends on the connection type.
        # IMProtocol uses one set of IDs, MatchLinkProtocol uses another.
        # We try IMProtocol first; the server will respond with the matching ID.
        frame = pack_frame(SPECTATOR_REQ_MSGID, payload)

        self._fragments[askid] = {"total": 0, "parts": {}}
        self._send(frame)
        logger.info(f"Spectator request: roomid={roomid} gameid={gameid} askid={askid}")
        return askid

    def handle_response(self, payload: bytes) -> bool:
        """Process a spectator response fragment.

        Returns True if the record is complete.
        """
        if len(payload) < 32:
            logger.warning(f"Spectator response too short: {len(payload)} bytes")
            return False

        # Parse response per IMProtocol.RespRealtimeGameRecord
        # Fields: askid, flag, room_id, max_offset, current, total, zip, payload_size, payload
        askid, flag, room_id, max_offset = struct.unpack_from("<iiii", payload, 0)
        current, total, zip_flag, payload_size = struct.unpack_from("<iiii", payload, 16)

        if askid not in self._fragments:
            logger.debug(f"Ignoring spectator response for unknown askid={askid}")
            return False

        # flag == FLAG.NOT_GOOD(1) 表示数据不完整，直接丢弃
        # (IMProtocol.lua:1860-1862, ReqRealtimeGameRecord.lua:65-69)
        if flag == 1:
            logger.warning(f"Spectator response flag=NOT_GOOD, data incomplete: askid={askid}")
            return False

        # zip != 1 不是回放协议（是其他推送），直接丢弃，不进分片缓冲
        # (ReqRealtimeGameRecord.lua:72 `if msgData.zip ~= 1 then return end`)
        if zip_flag != 1:
            logger.debug(f"Spectator response zip={zip_flag} != 1, not replay data, dropping")
            return False

        # total == 0 表示旁观数据不存在 (ReqRealtimeGameRecord.lua:81-87)
        if total == 0:
            logger.warning(f"Spectator response total=0, no replay data: askid={askid}")
            return False

        frag = self._fragments[askid]
        frag["total"] = total
        frag["room_id"] = room_id
        frag["max_offset"] = max_offset
        frag["zip"] = zip_flag

        if payload_size > 0 and len(payload) >= 32 + payload_size:
            data = payload[32:32 + payload_size]
            frag["parts"][current] = data
            logger.debug(f"Spectator fragment: {current}/{total} ({payload_size}B)")

        # Check if all fragments received
        if total > 0 and len(frag["parts"]) >= total:
            self._merge_and_deliver(askid)
            return True

        return False

    def _merge_and_deliver(self, askid: int) -> None:
        """Merge all fragments and deliver the complete record."""
        frag = self._fragments.pop(askid)
        total = frag["total"]

        # Merge fragments in order
        merged = bytearray()
        for i in range(1, total + 1):
            if i in frag["parts"]:
                merged += frag["parts"][i]
            else:
                logger.error(f"Missing fragment {i}/{total} for askid={askid}")
                return

        data = bytes(merged)

        # Decompress if zlib-compressed
        if frag.get("zip") == 1:
            try:
                data = zlib.decompress(data)
                logger.info(f"Decompressed record: {len(data)} bytes")
            except zlib.error as e:
                logger.error(f"Zlib decompress failed: {e}")
                return

        logger.info(f"Complete record: {len(data)} bytes, askid={askid}")
        if self._on_record:
            self._on_record(data)
```

## S4 decrypt_validate.py 全文

```
"""SRS ciphertext decryption validator — close the loop on one real capture.

Once you have ONE real SRS ciphertext sample on the wire, this tool brute-tries
the plausible (key, hex-order) combinations and prints each candidate plaintext
so you can eyeball which combination decrypted correctly. It reuses the verified
AES-CFB128 parameters from crypto.py (default key, fixed IV) — no AES is
re-implemented here.

------------------------------------------------------------------------------
How to obtain a sample to feed in
------------------------------------------------------------------------------
The Frida hook `frida/hook_srs.js` writes /data/local/tmp/.srs_dump.jsonl on the
phone. Useful record types:
  - {"type":"wire_send", ...,"data":"<hex>"}  -> encrypted bytes the client SENT
  - {"type":"tcp_recv",  ...,"data":"<hex>"}  -> raw bytes RECEIVED from server
  - {"type":"encrypt",   "plaintext":"<hex>"} -> the PLAINTEXT before encrypt()
        (use this to confirm a wire_send decrypts back to it)
  - {"type":"setAesKey", "key":"<hex>","len":N} -> the session key (may be the
        anti-tamper-scrubbed all-zero value; the REAL key comes from RespKey).

Pull it off the device, then:
  1. Strip the 12-byte frame header (see frame.py) if you want to decrypt just
     the payload, or feed the whole frame — the heuristic looks for the 0x4001
     flag either way.
  2. Pass the hex via positional arg, --hex, or --file.
  3. If you captured a RespKey session key, pass it via --session-key <hex>.

Examples:
  python remote/srs_spectator/decrypt_validate.py 01400a00...
  python remote/srs_spectator/decrypt_validate.py --hex 01400a00... \
      --session-key f362120513e389ff...
  python remote/srs_spectator/decrypt_validate.py --file sample.hex
------------------------------------------------------------------------------
"""
import argparse
import string
import sys

try:
    # When run as a module: python -m remote.srs_spectator.decrypt_validate
    from .crypto import SRSCrypto, SRS_DEFAULT_KEY, SRS_IV
except ImportError:
    # When run as a script: python remote/srs_spectator/decrypt_validate.py
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from crypto import SRSCrypto, SRS_DEFAULT_KEY, SRS_IV  # type: ignore


_PRINTABLE = set(bytes(string.printable, "ascii"))
SRS_FRAME_FLAG_LE = b"\x01\x40"  # 0x4001 little-endian on the wire


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clean_hex(s: str) -> str:
    """Strip whitespace/0x prefixes/colons so loose pasted hex still parses."""
    s = s.strip().replace("0x", "").replace("0X", "")
    for ch in (" ", "\n", "\r", "\t", ":", ",", "-"):
        s = s.replace(ch, "")
    return s


def _ascii_preview(data: bytes, limit: int = 64) -> str:
    out = []
    for b in data[:limit]:
        out.append(chr(b) if 32 <= b < 127 else ".")
    tail = "..." if len(data) > limit else ""
    return "".join(out) + tail


def _printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    good = sum(1 for b in data if b in _PRINTABLE)
    return good / len(data)


def _looks_like_srs_frame(data: bytes) -> bool:
    """0x4001 flag at the very start (decrypted a full frame)."""
    return data[:2] == SRS_FRAME_FLAG_LE


def _has_frame_flag_anywhere(data: bytes) -> bool:
    return SRS_FRAME_FLAG_LE in data


def _looks_like_protobuf(data: bytes) -> bool:
    """Very loose protobuf sniff: first byte is a plausible field tag and at
    least the first couple of varint fields parse without running off the end.
    """
    if len(data) < 2:
        return False
    pos = 0
    fields = 0
    while pos < len(data) and fields < 3:
        tag = data[pos]
        pos += 1
        field_no = tag >> 3
        wire = tag & 0x07
        if field_no == 0 or wire in (6, 7):
            return False
        if wire == 0:  # varint
            shift = 0
            while pos < len(data) and (data[pos] & 0x80):
                pos += 1
                shift += 1
                if shift > 9:
                    return False
            pos += 1
        elif wire == 2:  # length-delimited
            if pos >= len(data):
                return False
            ln = data[pos]
            pos += 1
            if ln & 0x80:  # multi-byte length varint — give up cheaply
                return False
            pos += ln
        elif wire == 5:  # 32-bit
            pos += 4
        elif wire == 1:  # 64-bit
            pos += 8
        else:
            return False
        fields += 1
    return fields >= 1 and pos <= len(data) + 1


def _score(data: bytes) -> tuple:
    """Heuristic score: higher = more likely correct. Returns (score, reasons)."""
    score = 0.0
    reasons = []
    if _looks_like_srs_frame(data):
        score += 100
        reasons.append("starts with 0x4001 frame flag")
    elif _has_frame_flag_anywhere(data):
        score += 30
        reasons.append("contains 0x4001 flag")
    pr = _printable_ratio(data)
    score += pr * 20
    if pr > 0.7:
        reasons.append(f"high ascii ratio {pr:.0%}")
    if _looks_like_protobuf(data):
        score += 15
        reasons.append("plausible protobuf varint structure")
    return score, reasons


# --------------------------------------------------------------------------- #
# candidate generators (each returns bytes or None on failure)
# --------------------------------------------------------------------------- #
def _cfb_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    return SRSCrypto(key=key, iv=iv).decrypt_payload(ct)


def _combo_direct(key, iv, ct):
    """CFB128 decrypt, use the plaintext as-is."""
    return _cfb_decrypt(key, iv, ct)


def _combo_hex_after(key, iv, ct):
    """hex-after-AES: decrypt, then the plaintext is ascii-hex -> hex-decode."""
    pt = _cfb_decrypt(key, iv, ct)
    return bytes.fromhex(pt.decode("ascii"))


def _combo_hex_before(key, iv, ct):
    """hex-before: the CIPHERTEXT is ascii-hex -> hex-decode it, then CFB decrypt."""
    raw_ct = bytes.fromhex(ct.decode("ascii"))
    return _cfb_decrypt(key, iv, raw_ct)


_COMBOS = [
    ("CFB128, direct decrypt", _combo_direct),
    ("CFB128, hex-decode AFTER decrypt (hex-after-AES)", _combo_hex_after),
    ("CFB128, hex-decode ciphertext BEFORE decrypt (hex-before)", _combo_hex_before),
]


def _run_key(label: str, key: bytes, iv: bytes, ct: bytes):
    results = []
    print(f"\n=== {label} (AES-{len(key) * 8}, key={key.hex()[:16]}...) ===")
    for name, fn in _COMBOS:
        try:
            pt = fn(key, iv, ct)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  [{name}]")
            print(f"      -> FAILED: {type(exc).__name__}: {exc}")
            continue
        score, reasons = _score(pt)
        results.append((score, label, name, pt, reasons))
        print(f"  [{name}]")
        print(f"      hex   : {pt.hex()}")
        print(f"      ascii : {_ascii_preview(pt)}")
        tag = ", ".join(reasons) if reasons else "(no positive signals)"
        print(f"      score : {score:.1f}  ({tag})")
    return results


# --------------------------------------------------------------------------- #
```

## S5 player_connect.py 全文

```
"""
SRS protocol C->S messages — build PlayerConnect with correct format.

Format confirmed 2026-06-14 from live pcap:
  IStream.writeString / OStream.readString uses 1-byte length prefix
  (not uint16 BE as previously assumed from Lua comment).

PlayerConnect binary layout (IStream, writeString=1-byte len+data):
  [0]    uint8   clienttype  (2=MOBILE)
  [1]    uint8   usertype    (7=SESSION)
  [2:6]  uint32  areaid      (LE)
  [6:7]  uint8   uid_len + uid bytes
  pwd:  16 bytes raw (SESSION mode)
  ident: uint8 len + data
  ver:   int32 LE
  chan:  int32 LE
  osver: int32 LE
  ident: uint8 len + data (yes, repeated)
  ngid:  int32 LE

Encryption:
  - EncryptVer  = AES-CFB128(default_key, iv).encrypt(b'\x01\x00\x00\x00')
  - HandshakeRsp received, S2C decrypt with default key -> session_key (bytes[1:1+key_len])
  - PlayerConnect = AES-CFB128(session_key, iv).encrypt(raw_binary)  # NO hex encoding!
"""
import struct


ENCRYPT_VER_PLAINTEXT = b"\x01\x00\x00\x00"   # LE32=1
ENCRYPT_VER_PAYLOAD = bytes.fromhex("fa60a522")  # ciphertext


def _write_istring(data: bytes) -> bytes:
    """IStream.writeString: 1-byte length + data (for strings <= 255)."""
    return bytes([len(data)]) + data


def build_player_connect_raw(
    *,
    clienttype: int = 2,
    usertype: int = 7,
    areaid: int = 7109,
    userid: bytes = b"newpt1084306678",
    pwd: bytes = b" \x43\xd2\xe6\x47\x62\x46\xdc\x99\x15\x78\x3a\x11\x96\xef\x78",
    identify: bytes = b"020000000000",
    ver: int = 0,
    channelid: int = 0,
    osver: int = 0,
    n_game_id: int = 0,
) -> bytes:
    """Build PlayerConnect binary matching C++ IStream encoding.

    Confirmed 2026-06-12 from live pcap + server test:
    writeUInt32 = exactly 4 bytes LE, NO padding byte.
    Total plaintext = 80 bytes (not 81).
    """
    bos = bytearray()
    bos.append(clienttype)
    bos.append(usertype)
    bos += struct.pack("<I", areaid)
    # NO padding byte after areaid — writeUInt32 is exactly 4 bytes
    bos += _write_istring(userid)
    if usertype == 7:          # SESSION
        bos += pwd[:16].ljust(16, b"\x00")
    else:
        bos += _write_istring(pwd)
    bos += _write_istring(identify)
    bos += struct.pack("<i", ver)
    bos += struct.pack("<i", channelid)
    bos += struct.pack("<i", osver)
    bos += _write_istring(identify)
    bos += struct.pack("<i", n_game_id)
    return bytes(bos)
```

## S6 frame.py 关键部分（看协议解析）

```
4:    Offset 0-1:  flag       (uint16, 0x4001)
14:FLAG = 0x4001  # Always 0x4001 on wire
17:def pack_frame(msg_type: int, payload: bytes = b"", sub_type: int = 0,
23:def unpack_frame(data: bytes) -> dict:
39:def read_frame_from_stream(buf: bytearray) -> tuple:
71:MSG_SPECTATOR_REQ = 3000    # ReqRealtimeGameRecord (0xBB8)
72:MSG_SPECTATOR_RESP = 3001   # RespRealtimeGameRecord (0xBB9)
73:MSG_UNWATCH_REQ = 3002      # ReqUnwatchRealtimeGameRecord (0xBBA)
74:MSG_UNWATCH_RESP = 3003     # RespUnwatchRealtimeGameRecord (0xBBB)
76:MSG_NAMES = {
86:    MSG_SPECTATOR_REQ: "ReqRealtimeGameRecord",
87:    MSG_SPECTATOR_RESP: "RespRealtimeGameRecord",
88:    MSG_UNWATCH_REQ: "ReqUnwatchRealtimeGameRecord",
89:    MSG_UNWATCH_RESP: "RespUnwatchRealtimeGameRecord",
```

## S7 noconfig spectator.py

```

```

## S8 grep 0x3c / HIDDEN_TILE / opp_hand 全 ECS 代码库

```
/opt/mahjong-remote/remote/cloud_player.py:9:       Uses srs_sessionid to authenticate and receive 0x2bc0 game frames,
/opt/mahjong-remote/remote/cloud_player.py:136:      4. Receive 0x2bc0 game event frames continuously
/opt/mahjong-remote/remote/cloud_player.py:357:            from remote.srs_spectator.client import SRSClient
/opt/mahjong-remote/remote/cloud_player.py:359:            from srs_spectator.client import SRSClient
/opt/mahjong-remote/remote/cloud_player.py:388:        # if no 0x2bc0 frames arrive within IDLE_GAME_TIMEOUT, disconnect proactively.
/opt/mahjong-remote/remote/cloud_player.py:419:        the 0x2bc0 game event stream is not additionally encrypted).
/opt/mahjong-remote/remote/cloud_player.py:448:        """Decode a raw 0x2bc0 payload and feed to tracker."""
/opt/mahjong-remote/remote/hotspot/app.py:5:职责：仅包含热点模式相关端点，不含 spectator 子进程、/register-room、VPN 页面等。
/opt/mahjong-remote/remote/hotspot/app.py:17:  - 不包含 spectator 子进程管理、/register-room、/watch-info、VPN setup 页面
/opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py:29:  python remote/srs_spectator/decrypt_validate.py 01400a00...
/opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py:30:  python remote/srs_spectator/decrypt_validate.py --hex 01400a00... \
/opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py:32:  python remote/srs_spectator/decrypt_validate.py --file sample.hex
/opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py:40:    # When run as a module: python -m remote.srs_spectator.decrypt_validate
/opt/mahjong-remote/remote/srs_spectator/decrypt_validate.py:43:    # When run as a script: python remote/srs_spectator/decrypt_validate.py
/opt/mahjong-remote/remote/srs_spectator/__init__.py:4:    extractor (hotspot) → relay :8000 → srs_spectator :8003 → game server
/opt/mahjong-remote/remote/srs_spectator/main.py:1:"""srs_spectator service — listens for roomid/gameid and watches games.
/opt/mahjong-remote/remote/srs_spectator/main.py:10:    GET  /status — check spectator status
/opt/mahjong-remote/remote/srs_spectator/main.py:13:    srs_spectator pushes game data to relay:8000 via POST /push
/opt/mahjong-remote/remote/srs_spectator/main.py:110:            logger.info("Handshake done, requesting spectator data...")
/opt/mahjong-remote/remote/srs_spectator/main.py:111:            client.request_spectator(roomid, gameid)
/opt/mahjong-remote/remote/srs_spectator/main.py:128:        client.on_spectator_record(on_record)
/opt/mahjong-remote/remote/srs_spectator/frame.py:71:MSG_SPECTATOR_REQ = 3000    # ReqRealtimeGameRecord (0xBB8)
/opt/mahjong-remote/remote/srs_spectator/frame.py:72:MSG_SPECTATOR_RESP = 3001   # RespRealtimeGameRecord (0xBB9)
/opt/mahjong-remote/remote/srs_spectator/frame.py:73:MSG_UNWATCH_REQ = 3002      # ReqUnwatchRealtimeGameRecord (0xBBA)
/opt/mahjong-remote/remote/srs_spectator/frame.py:74:MSG_UNWATCH_RESP = 3003     # RespUnwatchRealtimeGameRecord (0xBBB)
/opt/mahjong-remote/remote/srs_spectator/frame.py:86:    MSG_SPECTATOR_REQ: "ReqRealtimeGameRecord",
/opt/mahjong-remote/remote/srs_spectator/frame.py:87:    MSG_SPECTATOR_RESP: "RespRealtimeGameRecord",
/opt/mahjong-remote/remote/srs_spectator/frame.py:88:    MSG_UNWATCH_REQ: "ReqUnwatchRealtimeGameRecord",
/opt/mahjong-remote/remote/srs_spectator/frame.py:89:    MSG_UNWATCH_RESP: "RespUnwatchRealtimeGameRecord",
/opt/mahjong-remote/remote/srs_spectator/config.yaml:1:# srs_spectator 配置
/opt/mahjong-remote/remote/srs_spectator/spectator.py:1:"""Spectator protocol — ReqRealtimeGameRecord.
/opt/mahjong-remote/remote/srs_spectator/spectator.py:16:# These are the XY_ID values for spectator messages
/opt/mahjong-remote/remote/srs_spectator/spectator.py:19:SPECTATOR_REQ_MSGID = 3000   # ReqRealtimeGameRecord, IMProtocol.lua:73 确认值 (0xBB8)
/opt/mahjong-remote/remote/srs_spectator/spectator.py:20:SPECTATOR_RESP_MSGID = 3001  # RespRealtimeGameRecord, IMProtocol.lua:74 (0xBB9)
/opt/mahjong-remote/remote/srs_spectator/spectator.py:24:    """Handles spectator protocol over an established SRS connection."""
/opt/mahjong-remote/remote/srs_spectator/spectator.py:53:        # Build request payload per IMProtocol.ReqRealtimeGameRecord
/opt/mahjong-remote/remote/srs_spectator/spectator.py:57:        # The actual msgid for spectator request depends on the connection type.
/opt/mahjong-remote/remote/srs_spectator/spectator.py:68:        """Process a spectator response fragment.
/opt/mahjong-remote/remote/srs_spectator/spectator.py:76:        # Parse response per IMProtocol.RespRealtimeGameRecord
/opt/mahjong-remote/remote/srs_spectator/spectator.py:82:            logger.debug(f"Ignoring spectator response for unknown askid={askid}")
/opt/mahjong-remote/remote/srs_spectator/spectator.py:86:        # (IMProtocol.lua:1860-1862, ReqRealtimeGameRecord.lua:65-69)
/opt/mahjong-remote/remote/srs_spectator/spectator.py:92:        # (ReqRealtimeGameRecord.lua:72 `if msgData.zip ~= 1 then return end`)
/opt/mahjong-remote/remote/srs_spectator/spectator.py:97:        # total == 0 表示旁观数据不存在 (ReqRealtimeGameRecord.lua:81-87)
/opt/mahjong-remote/remote/srs_spectator/client.py:6:    client.request_spectator(roomid, gameid)
/opt/mahjong-remote/remote/srs_spectator/client.py:28:    from .spectator import SpectatorClient
/opt/mahjong-remote/remote/srs_spectator/client.py:41:    from spectator import SpectatorClient
/opt/mahjong-remote/remote/srs_spectator/client.py:51:    """SRS protocol client with handshake and spectator support."""
/opt/mahjong-remote/remote/srs_spectator/client.py:69:        self._spectator: SpectatorClient | None = None
/opt/mahjong-remote/remote/srs_spectator/client.py:121:    def request_spectator(self, roomid: int, gameid: int) -> int:
/opt/mahjong-remote/remote/srs_spectator/client.py:122:        """Request spectator data for a game room."""
/opt/mahjong-remote/remote/srs_spectator/client.py:123:        if not self._spectator:
/opt/mahjong-remote/remote/srs_spectator/client.py:124:            self._spectator = SpectatorClient(self._send_raw)
/opt/mahjong-remote/remote/srs_spectator/client.py:125:        return self._spectator.request_record(roomid, gameid)
/opt/mahjong-remote/remote/srs_spectator/client.py:127:    def on_spectator_record(self, callback):
/opt/mahjong-remote/remote/srs_spectator/client.py:128:        """Set callback for complete spectator records."""
/opt/mahjong-remote/remote/srs_spectator/client.py:129:        if not self._spectator:
/opt/mahjong-remote/remote/srs_spectator/client.py:130:            self._spectator = SpectatorClient(self._send_raw)
/opt/mahjong-remote/remote/srs_spectator/client.py:131:        self._spectator.on_record(callback)
/opt/mahjong-remote/remote/srs_spectator/client.py:227:                logger.warning(f"Auth warning: flag={flag} (non-zero, may still work for spectator)")
/opt/mahjong-remote/remote/srs_spectator/client.py:251:        elif self._spectator and msg_type == MSG_SPECTATOR_RESP:
```

## S9 stable/protocol.py 在 ECS 上的版本

```
14:HIDDEN_TILE = 0x3C
62:    0x022B: "round_result",
124:    return int(value) == HIDDEN_TILE
368:        sub_cmd = struct.unpack("<H", payload[0:2])[0]
372:            "sub_cmd": sub_cmd,
373:            "sub_name": GAME_SUB_NAMES.get(sub_cmd, f"sub_{sub_cmd:#06x}"),
378:        if sub_cmd == 0x0003:
389:            if len(body) >= 18 and body[17] not in (0, HIDDEN_TILE):
392:        elif sub_cmd == 0x0016:
396:        elif sub_cmd == 0x0216 and len(body) >= 3:
436:        elif sub_cmd == 0x021B and len(body) >= 2:
448:        elif sub_cmd == 0x021A and len(body) >= 2:
462:        elif sub_cmd == 0x0218 and len(body) >= 2 and int(body[0]) == 0x01:
464:            if baida_raw not in (0, HIDDEN_TILE):
475:        elif sub_cmd == 0x021F and len(body) >= 2:
506:                    if claimed not in (0, HIDDEN_TILE):
520:        elif sub_cmd == 0x0220:
526:            if len(body) >= 14 and body[13] not in (0, HIDDEN_TILE):
545:            if raw in (0, HIDDEN_TILE):
551:            if raw not in (0, HIDDEN_TILE, DRAW_CONCEALED_MARKER):
562:        if raw in (0, HIDDEN_TILE):
638:            stable_tiles = [stable_tile_id(raw) for raw in four_tiles if raw not in (0, HIDDEN_TILE)]
646:            stable_tiles = [stable_tile_id(raw) for raw in meld_bytes if raw not in (0, HIDDEN_TILE)]
649:            meld_indexes = [instance_tile_index(raw) for raw in meld_bytes if raw not in (0, HIDDEN_TILE)]
655:            if raw in (0, HIDDEN_TILE):
```

## S10 spectator_forensic.jsonl 字段名分布

```
    200 ts
    200 sub_type_hex
    200 sub_type
    200 pay_len
    200 msg_type_hex
    200 msg_type
    200 kind
    200 frame_head
    200 extra
    200 dir
    134 S->C
    113 0x0001
    110 38564c05
     86 0x2bc0
     66 C->S
     64 0x0054
     56 00000000
     31 0x0018
     30 0x0019
     17 0x047b
     15 0.0
     13 00340000
     12 0x2bc1
     10 01340000
      8 ab2d0000
      8 0x0000
      7 0x0006
      6 0x0093
      4 2026-06-12T07:45:53.877
      4 2026-06-12T07:45:53.874
      3 2026-06-12T07:45:53.674
      3 2026-06-12T07:45:53.673
      3 2026-06-12T07:45:53.671
      2 2026-06-12T07:45:53.883
      2 2026-06-12T07:45:53.881
      2 2026-06-12T07:45:53.880
      2 2026-06-12T07:45:53.879
      2 2026-06-12T07:45:53.876
      2 2026-06-12T07:45:53.875
      2 2026-06-12T07:45:53.873
```

## S11 spectator_forensic.jsonl 任意中间一行（看完整 schema）

```
{"ts": "0.0", "dir": "C->S", "msg_type": 6, "msg_type_hex": "0x0006", "sub_type": 147, "sub_type_hex": "0x0093", "extra": "00000000", "pay_len": 16, "kind": "frame_head"}
{"ts": "2026-06-12T07:45:52.918", "dir": "S->C", "msg_type": 11321, "msg_type_hex": "0x2c39", "sub_type": 1, "sub_type_hex": "0x0001", "extra": "38564c05", "pay_len": 46, "kind": "frame_head"}
{"ts": "2026-06-12T07:46:02.217", "dir": "S->C", "msg_type": 11200, "msg_type_hex": "0x2bc0", "sub_type": 1, "sub_type_hex": "0x0001", "extra": "38564c05", "pay_len": 17, "kind": "frame_head"}
{"ts": "2026-06-12T08:21:54.467", "dir": "S->C", "msg_type": 11200, "msg_type_hex": "0x2bc0", "sub_type": 1, "sub_type_hex": "0x0001", "extra": "38564c05", "pay_len": 17, "kind": "frame_head"}
```

## S12 noconfig multiuser app.py 入口

```
4:无配置模式独立 FastAPI app。
11:  POST /push           — 接收 extractor 推送的 snapshot（extractor 上线时停止 spectator）
14:  GET  /watch-info     — 返回当前房间信息
15:  GET  /admin          — 后台管理页面（用户列表 + 搜索 + 手牌展示）
52:from fastapi import FastAPI, HTTPException, Query, Request
62:# ─── FastAPI app ────────────────────────────────────────────────
64:app = FastAPI(title="MahjongAI Noconfig Relay (Multi-User)")
78:def configure(cfg: dict, cfg_path: str = "") -> None:
152:def _check_api_token(token: str):
158:def _admin_username() -> str:
162:def _admin_password() -> str:
166:def _admin_cookie_secret() -> str:
170:def _is_admin_configured() -> bool:
174:def _make_admin_cookie_value(username: str, ttl_seconds: int) -> str:
185:def _read_admin_cookie(request: Request) -> Optional[str]:
209:def _set_admin_cookie(response: JSONResponse | RedirectResponse, username: str, remember: bool) -> None:
220:def _clear_admin_cookie(response: RedirectResponse) -> None:
224:def _get_or_create_user(user_id: str, name: str = "") -> "User":
232:def _get_existing_user_or_404(user_id: str) -> "User":
240:def _persist_credentials(handshake_hex: str, auth_hex: str, srs_sid: str = ""):
264:def _ensure_spectator_running(user: "User"):
302:def _start_srs_spectator(user: "User"):
355:def _stop_spectator(user: "User"):
367:def _notify_spectator(user: "User", room_id: int, game_id: int):
372:    def _do_notify():
377:                f"{spectator_url}/watch",
398:@app.get("/", response_class=HTMLResponse)
399:async def index():
400:    """首页 — 重定向到 /admin"""
404:<meta http-equiv="refresh" content="0;url=/admin">
406:<body><p>正在跳转到 <a href="/admin">管理页面</a>...</p></body>
410:@app.get("/state")
411:async def get_state(
429:@app.post("/register")
430:async def register(req: RegisterRequest):
463:def _auto_fill_credentials(user: "User", fallback_srs_sid: str = "") -> None:
481:@app.post("/push")
482:async def push(req: PushRequest):
502:@app.post("/presence")
503:async def presence(req: PresenceRequest):
506:    与 /push 的区别：presence 不带手牌快照，仅标记"该用户当前活跃"，用于
507:    "进大厅即显示在线"。手牌数据仍走 /push（依赖 0x2bc0 解码）。
538:@app.post("/register-room")
539:async def register_room(req: RegisterRoomRequest):
558:@app.get("/watch-info")
559:async def get_watch_info(
569:@app.get("/mode")
570:async def get_mode():
585:@app.get("/api/users")
586:async def get_users(token: str = Query(..., description="鉴权 token")):
```

