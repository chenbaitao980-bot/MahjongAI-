"""SRS wire frame format — 12-byte header.

Wire format (little-endian):
    Offset 0-1:  flag       (uint16, 0x4001)
    Offset 2-3:  payload_len (uint16 LE)
    Offset 4-5:  msg_type    (uint16 LE)
    Offset 6-7:  sub_type    (uint16 LE)
    Offset 8-11: extra       (uint32 LE)
    Offset 12+:  payload     (length = payload_len)
"""
import struct

HDR_LEN = 12
FLAG = 0x4001  # Always 0x4001 on wire


def pack_frame(msg_type: int, payload: bytes = b"", sub_type: int = 0,
               extra: int = 0) -> bytes:
    """Pack a message into wire format."""
    return struct.pack("<HHHHI", FLAG, len(payload), msg_type, sub_type, extra) + payload


def unpack_frame(data: bytes) -> dict:
    """Unpack a wire frame into its components. Returns None if invalid."""
    if len(data) < HDR_LEN:
        return None
    flag, pay_len, msg_type, sub_type, extra = struct.unpack("<HHHHI", data[:HDR_LEN])
    payload = data[HDR_LEN:HDR_LEN + pay_len]
    return {
        "flag": flag,
        "payload_len": pay_len,
        "msg_type": msg_type,
        "sub_type": sub_type,
        "extra": extra,
        "payload": payload,
    }


def read_frame_from_stream(buf: bytearray) -> tuple:
    """Try to read one complete frame from a byte buffer.
    Returns (frame_dict, remaining_buf) or (None, buf) if incomplete.
    """
    if len(buf) < HDR_LEN:
        return None, buf
    _, pay_len, _, _, _ = struct.unpack("<HHHHI", buf[:HDR_LEN])
    total = HDR_LEN + pay_len
    if len(buf) < total:
        return None, buf
    frame_data = bytes(buf[:total])
    remaining = buf[total:]
    return unpack_frame(frame_data), remaining


# Known SRS message types
# ⚠️ BLOCKER: 以下三个是 native C++ 加密协商层 (un.network.TcpConnection) 的 msgid，
# 在 SRSProtocol.lua 里查无此物（无 XY_ID=1/3/4），是 Python 侧为 native 握手起的名字。
# native 握手（EncryptVer→ReqKey→HandshakeRsp、CTR/transformStr、m_key 协商）
# 全在 libcocos2dlua.so 中实现，纯 Python 无法驱动（见 research §握手 / §0）。
MSG_ENCRYPT_VER = 1     # native 握手层 msgid，非 SRSProtocol.lua XY_ID
MSG_REQ_KEY = 3         # native 握手层 msgid，非 SRSProtocol.lua XY_ID
MSG_HANDSHAKE_RSP = 4   # native 握手层 msgid，非 SRSProtocol.lua XY_ID
MSG_PLAYER_CONNECT = 5  # PlayerConnect (auth), SRSProtocol.lua:5
MSG_PLAYER_DATA = 6     # PlayerData (auth result), SRSProtocol.lua:6
MSG_SRS_LOAD = 10       # ReqSRSLoad, SRSProtocol.lua:9
MSG_SRS_ADDR = 14       # ReqSRSAddr, SRSProtocol.lua:12（与 RoomProtocol RespJoinTable=14 撞号，靠 processid 区分）
MSG_REQ_PLUS_DATA = 23  # ReqPlayerPlusData, SRSProtocol.lua:16
MSG_RESP_PLUS_DATA = 24 # RespPlayerPlusData, SRSProtocol.lua:17

# Spectator message types (IMProtocol.lua:73-76 / MatchLinkProtocol.lua:3-6)
# XY_ID 两套协议相同；区分 IMProtocol(processid=100) vs MatchLinkProtocol(processid=1006) 靠 frame processid。
MSG_SPECTATOR_REQ = 3000    # ReqRealtimeGameRecord (0xBB8)
MSG_SPECTATOR_RESP = 3001   # RespRealtimeGameRecord (0xBB9)
MSG_UNWATCH_REQ = 3002      # ReqUnwatchRealtimeGameRecord (0xBBA)
MSG_UNWATCH_RESP = 3003     # RespUnwatchRealtimeGameRecord (0xBBB)

MSG_NAMES = {
    MSG_ENCRYPT_VER: "EncryptVer",
    MSG_REQ_KEY: "ReqKey",
    MSG_HANDSHAKE_RSP: "HandshakeRsp",
    MSG_PLAYER_CONNECT: "PlayerConnect",
    MSG_PLAYER_DATA: "PlayerData",
    MSG_SRS_LOAD: "SRSLoad",
    MSG_SRS_ADDR: "SRSAddr",
    MSG_REQ_PLUS_DATA: "ReqPlayerPlusData",
    MSG_RESP_PLUS_DATA: "RespPlayerPlusData",
    MSG_SPECTATOR_REQ: "ReqRealtimeGameRecord",
    MSG_SPECTATOR_RESP: "RespRealtimeGameRecord",
    MSG_UNWATCH_REQ: "ReqUnwatchRealtimeGameRecord",
    MSG_UNWATCH_RESP: "RespUnwatchRealtimeGameRecord",
}
