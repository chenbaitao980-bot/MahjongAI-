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
MSG_ENCRYPT_VER = 1     # EncryptVer handshake
MSG_REQ_KEY = 3         # ReqKey / heartbeat_req
MSG_HANDSHAKE_RSP = 4   # RespKey / handshake_rsp
MSG_PLAYER_CONNECT = 5  # PlayerConnect (auth)
MSG_PLAYER_DATA = 6     # PlayerData (auth result)
MSG_SRS_LOAD = 10       # ReqSRSLoad
MSG_SRS_ADDR = 14       # ReqSRSAddr
MSG_REQ_PLUS_DATA = 23  # ReqPlayerPlusData
MSG_RESP_PLUS_DATA = 24 # RespPlayerPlusData

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
}
