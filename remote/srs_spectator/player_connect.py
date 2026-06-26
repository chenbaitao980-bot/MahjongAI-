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
