"""SRS handshake state machine.

Implements the 4-step SRS handshake:
  1. C→S msgid=1 payload=fa60a522 (EncryptVer)
  2. S→C msgid=1 (response)
  3. C→S msgid=3 payload=0B (ReqKey)
  4. S→C msgid=4 payload=25B (handshake_rsp)
  5. C→S msgid=5 payload=80B encrypted (PlayerConnect)
  6. S→C msgid=6 (PlayerData, contains sessionid)
  7. C→S msgid=23 payload=0B (ReqPlayerPlusData)
  8. S→C msgid=24 (RespPlayerPlusData, contains m_key)
"""
import struct
import logging

from .frame import (
    pack_frame, MSG_ENCRYPT_VER, MSG_REQ_KEY, MSG_HANDSHAKE_RSP,
    MSG_PLAYER_CONNECT, MSG_PLAYER_DATA, MSG_REQ_PLUS_DATA,
    MSG_RESP_PLUS_DATA,
)
from .crypto import SRSCrypto, DEFAULT_KEY

logger = logging.getLogger(__name__)

ENCRYPT_VER_PAYLOAD = bytes.fromhex("fa60a522")  # 4 bytes


class HandshakeState:
    """Tracks SRS handshake progress."""

    STEPS = [
        "init",
        "encrypt_ver_sent",
        "encrypt_ver_ack",
        "req_key_sent",
        "handshake_rsp_rcvd",
        "player_connect_sent",
        "player_data_rcvd",
        "plus_data_sent",
        "done",
    ]

    def __init__(self):
        self.step = 0
        self.handshake_rsp = b""
        self.sessionid = b""
        self.m_key = b""
        self.player_data = {}

    @property
    def is_done(self) -> bool:
        return self.step >= 8

    def advance(self, expected_step: str) -> None:
        self.step += 1
        actual = self.STEPS[self.step] if self.step < len(self.STEPS) else "?"
        if actual != expected_step:
            logger.warning(f"Handshake step mismatch: expected {expected_step}, got {actual}")


def build_encrypt_ver() -> bytes:
    """Build EncryptVer frame (msgid=1)."""
    return pack_frame(MSG_ENCRYPT_VER, ENCRYPT_VER_PAYLOAD)


def build_req_key() -> bytes:
    """Build ReqKey frame (msgid=3)."""
    return pack_frame(MSG_REQ_KEY, b"")


def build_player_connect(
    userid: str,
    sessionid: bytes,
    identify: str,
    channelid: int,
    n_game_id: int,
    areaid: int = 0,
    ver: int = 0,
    osver: int = 0,
    crypto: SRSCrypto = None,
) -> bytes:
    """Build PlayerConnect frame (msgid=5).

    Constructs the binary PlayerConnect struct as defined in SRSProtocol.lua,
    then encrypts it with AES-256-CTR.

    usertype=SESSION(7) means pwd is a 16-byte sessionid.
    """
    if crypto is None:
        crypto = SRSCrypto()

    # Build the plaintext PlayerConnect struct
    # clienttype: MOBILE=2
    # usertype: SESSION=7
    bos = bytearray()
    bos.append(2)   # clienttype = MOBILE
    bos.append(7)   # usertype = SESSION
    bos += struct.pack("<I", areaid)  # areaid (uint32)

    # userid: writeString = uint16 length + string
    uid_bytes = userid.encode("utf-8")
    bos += struct.pack("<H", len(uid_bytes))
    bos += uid_bytes

    # pwd: for SESSION type, write 16 raw bytes
    bos += sessionid[:16].ljust(16, b"\x00")

    # identify: writeString
    id_bytes = identify.encode("utf-8")
    bos += struct.pack("<H", len(id_bytes))
    bos += id_bytes

    # ver, channelid, osver (int32 each)
    bos += struct.pack("<i", ver)
    bos += struct.pack("<i", channelid)
    bos += struct.pack("<i", osver)

    # identify again (writeString)
    bos += struct.pack("<H", len(id_bytes))
    bos += id_bytes

    # nGameID (int32)
    bos += struct.pack("<i", n_game_id)

    plaintext = bytes(bos)
    logger.debug(f"PlayerConnect plaintext: {len(plaintext)} bytes")

    # Encrypt
    ciphertext = crypto.encrypt_frame_payload(plaintext)
    return pack_frame(MSG_PLAYER_CONNECT, ciphertext)


def build_req_plus_data() -> bytes:
    """Build ReqPlayerPlusData frame (msgid=23)."""
    return pack_frame(MSG_REQ_PLUS_DATA, b"")


def parse_player_data(payload: bytes) -> dict:
    """Parse PlayerData response (msgid=6).

    Structure from SRSProtocol.lua:
      flag(u8) areaid(i32) numid(i32) nickname(str) protecturl(str)
      [if flag==1: msg(str)]
      [sessionid(16B)]
    """
    if len(payload) < 9:
        return {"error": "payload too short"}

    offset = 0
    flag = payload[offset]; offset += 1
    areaid = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    numid = struct.unpack_from("<i", payload, offset)[0]; offset += 4

    # nickname (uint16 length + string)
    nick_len = struct.unpack_from("<H", payload, offset)[0]; offset += 2
    nickname = payload[offset:offset+nick_len].decode("utf-8", errors="replace")
    offset += nick_len

    # protecturl
    url_len = struct.unpack_from("<H", payload, offset)[0]; offset += 2
    protecturl = payload[offset:offset+url_len].decode("utf-8", errors="replace")
    offset += url_len

    msg = ""
    if flag == 1 and offset + 2 <= len(payload):
        msg_len = struct.unpack_from("<H", payload, offset)[0]; offset += 2
        msg = payload[offset:offset+msg_len].decode("utf-8", errors="replace")
        offset += msg_len

    sessionid = b""
    if offset + 16 <= len(payload):
        sessionid = payload[offset:offset+16]

    return {
        "flag": flag,
        "areaid": areaid,
        "numid": numid,
        "nickname": nickname,
        "protecturl": protecturl,
        "msg": msg,
        "sessionid": sessionid,
    }


def parse_resp_plus_data(payload: bytes) -> dict:
    """Parse RespPlayerPlusData (msgid=24).

    Contains user info + m_key (AES key for subsequent encryption).
    """
    result = {}
    offset = 0

    def read_str(data, off):
        if off + 2 > len(data):
            return "", off
        slen = struct.unpack_from("<H", data, off)[0]
        off += 2
        if off + slen > len(data):
            return "", off
        s = data[off:off+slen].decode("utf-8", errors="replace")
        return s, off + slen

    result["userid"], offset = read_str(payload, offset)
    result["ptid"], offset = read_str(payload, offset)
    result["ptnumid"], offset = read_str(payload, offset)
    result["nickname"], offset = read_str(payload, offset)
    result["identify"], offset = read_str(payload, offset)

    if offset + 25 > len(payload):
        return result

    result["sex"] = payload[offset]; offset += 1
    result["head"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["right"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["regtime"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["vipid"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["vipendtime"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["ip"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["osver"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    result["clienttype"] = struct.unpack_from("<i", payload, offset)[0]; offset += 4

    # m_key
    if offset < len(payload):
        result["keylen"] = payload[offset]; offset += 1
        if result["keylen"] > 0 and offset + result["keylen"] <= len(payload):
            result["key"] = payload[offset:offset + result["keylen"]]
            offset += result["keylen"]

    return result
