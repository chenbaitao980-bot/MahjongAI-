"""SRS handshake — builds and parses protocol messages."""
import struct
import logging

from .frame import pack_frame, MSG_PLAYER_CONNECT
from .crypto import SRSCrypto

logger = logging.getLogger(__name__)

ENCRYPT_VER_PAYLOAD = bytes.fromhex("fa60a522")  # 4 bytes


def build_encrypt_ver() -> bytes:
    return pack_frame(1, ENCRYPT_VER_PAYLOAD)  # msgid=1


def build_req_key() -> bytes:
    return pack_frame(3, b"")  # msgid=3


def build_player_connect(
    userid: str = "",
    sessionid: bytes = b"",
    identify: str = "test_device",
    channelid: int = 0,
    n_game_id: int = 0,
    areaid: int = 0,
    ver: int = 0,
    osver: int = 0,
    crypto: SRSCrypto = None,
) -> bytes:
    """Build and encrypt PlayerConnect (msgid=5) using AES-192 + hex transform.

    usertype=7 (SESSION), clienttype=2 (MOBILE).
    """
    if crypto is None:
        crypto = SRSCrypto()

    bos = bytearray()
    bos.append(2)   # clienttype = MOBILE
    bos.append(7)   # usertype = SESSION
    bos += struct.pack("<I", areaid)

    uid_bytes = userid.encode("utf-8") if userid else b""
    bos += struct.pack("<H", len(uid_bytes))
    bos += uid_bytes

    # pwd: 16-byte sessionid
    bos += sessionid[:16].ljust(16, b"\x00")

    id_bytes = identify.encode("utf-8") if identify else b""
    bos += struct.pack("<H", len(id_bytes))
    bos += id_bytes

    bos += struct.pack("<i", ver)
    bos += struct.pack("<i", channelid)
    bos += struct.pack("<i", osver)

    bos += struct.pack("<H", len(id_bytes))
    bos += id_bytes

    bos += struct.pack("<i", n_game_id)

    plaintext = bytes(bos)
    logger.debug(f"PlayerConnect plain: {len(plaintext)} bytes")

    # hex_encode → AES-192-CTR encrypt
    ciphertext = crypto.transform_and_encrypt(plaintext)
    logger.debug(f"PlayerConnect encrypted: {len(ciphertext)} bytes")

    return pack_frame(MSG_PLAYER_CONNECT, ciphertext)


def build_req_plus_data() -> bytes:
    return pack_frame(23, b"")  # msgid=23


def parse_player_data(payload: bytes) -> dict:
    """Parse PlayerData response (msgid=6).

    线上实测明文（手机 `LOLLAPALOOZA`）：
      00 c51b0000 f634a140 0c 4c4f4c4c4150414c4f4f5a41 00 6f588b49338f49d2ae69c38f04b2ff1c
      ^  ^^^^^^^  ^^^^^^^  ^  ^^^^^^^^^^^^^^^^^^^^^^^^ ^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      fl areaid    numid   nl   "LOLLAPALOOZA" (12B)   ul    sessionid (16B)

    nick_len / url_len / msg_len 都是 **1 字节** 长度前缀（不是 readString 的 uint16）。
    历史上误用 <H 解析，会把第一个昵称字节吃成长度高位，导致 nickname 越界 +
    sessionid 永远拿不到 → presence 上报失败。详见 [memory:srs-cfb-and-string-prefix-fix]。
    """
    if len(payload) < 9:
        return {"error": "payload too short"}

    offset = 0
    flag = payload[offset]; offset += 1
    areaid = struct.unpack_from("<i", payload, offset)[0]; offset += 4
    numid = struct.unpack_from("<i", payload, offset)[0]; offset += 4

    if offset + 1 > len(payload):
        return {"error": "nick_len missing"}
    nick_len = payload[offset]; offset += 1
    nick_end = min(offset + nick_len, len(payload))
    nickname = payload[offset:nick_end].decode("utf-8", errors="replace")
    offset = nick_end

    if offset + 1 > len(payload):
        return {"flag": flag, "areaid": areaid, "numid": numid, "nickname": nickname,
                "protecturl": "", "msg": "", "sessionid": b""}
    url_len = payload[offset]; offset += 1
    url_end = min(offset + url_len, len(payload))
    protecturl = payload[offset:url_end].decode("utf-8", errors="replace")
    offset = url_end

    msg = ""
    if flag == 1 and offset + 1 <= len(payload):
        msg_len = payload[offset]; offset += 1
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
    """Parse RespPlayerPlusData (msgid=24)."""
    result = {}
    offset = 0

    def read_str(data, off):
        if off + 2 > len(data):
            return "", off
        slen = struct.unpack_from("<H", data, off)[0]
        off += 2
        if off + slen > len(data):
            return "", off
        return data[off:off+slen].decode("utf-8", errors="replace"), off + slen

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

    if offset < len(payload):
        result["keylen"] = payload[offset]; offset += 1
        if result["keylen"] > 0 and offset + result["keylen"] <= len(payload):
            result["key"] = payload[offset:offset + result["keylen"]]

    return result
