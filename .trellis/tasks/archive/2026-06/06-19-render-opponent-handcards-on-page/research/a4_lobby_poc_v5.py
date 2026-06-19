"""PoC v5: 修复 H3+H11+H12 三件套后试 ReqRealtimeGameRecord(3000)。

修复点（vs v4）：
- H3: pack_frame 用 sub_type=processid (默认 100=IMProtocol，回退 1006=MatchLinkProtocol)
       extra=appid (从 SvrAppidList 算或暴力穷举或命令行传)
- H11: lobby host 默认 47.96.101.155:5748（真大厅，不是游服 47.96.0.227:5045）
- H12: roomid/gameid 命令行传入最新的（建议从 ECS tcp_proxy 日志取）

关键约束：
- 不修改主仓代码；本脚本自己实现 spectator 请求帧的 wire 构造
- 不发任何破坏性请求（不发 ReqLeaveRoom / ReqUnwatch）
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
logger = logging.getLogger("a4v5")


# 重新打 wire frame：sub_type=processid, extra=appid
FLAG = 0x4001
HDR_LEN = 12

def pack_frame_v5(msg_type: int, payload: bytes, processid: int, appid: int) -> bytes:
    return struct.pack("<HHHHI", FLAG, len(payload), msg_type, processid, appid) + payload


def build_spectator_req(roomid: int, askid: int, offset: int = 0,
                        before_round: int = 0, processid: int = 100,
                        appid: int = 0) -> bytes:
    """ReqRealtimeGameRecord (msg_type=3000):
       payload = <iiii> askid, room_id, offset, before_round
       wire sub_type = processid (100=IM / 1006=MatchLink)
       wire extra    = appid (SvrAppidList[roomid % len + 1])
    """
    body = struct.pack("<iiii", askid, roomid, offset, before_round)
    return pack_frame_v5(3000, body, processid, appid)


def parse_spectator_resp(payload: bytes) -> dict | None:
    """RespRealtimeGameRecord body:
       <iiii> askid, flag, room_id, max_offset
       <iiii> current, total, zip, payload_size
       payload[32:32+payload_size] = data
    """
    if len(payload) < 32:
        return None
    askid, flag, room_id, max_offset = struct.unpack_from("<iiii", payload, 0)
    current, total, zip_flag, payload_size = struct.unpack_from("<iiii", payload, 16)
    data = payload[32:32 + payload_size] if payload_size > 0 and len(payload) >= 32 + payload_size else b""
    return {
        "askid": askid,
        "flag": flag,
        "room_id": room_id,
        "max_offset": max_offset,
        "current": current,
        "total": total,
        "zip": zip_flag,
        "payload_size": payload_size,
        "data": data,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--srs-sessionid", required=True,
                   help="主号 sessionid (32 hex)")
    p.add_argument("--userid", default="newpt1084306678")
    # H11: 默认值改为真大厅
    p.add_argument("--lobby-host", default="47.96.101.155")
    p.add_argument("--lobby-port", type=int, default=5748)
    # H12: 必须传最新的
    p.add_argument("--room-id", type=int, required=True)
    p.add_argument("--game-id", type=int, required=True)
    # H3: processid + appid 试探
    p.add_argument("--processid", type=int, default=100,
                   help="IMProtocol=100 / MatchLinkProtocol=1006")
    p.add_argument("--appid", type=int, default=0,
                   help="若 SvrAppidList 已知则按 list[roomid%%len+1] 算；否则暴力穷举")
    p.add_argument("--appid-sweep", default="",
                   help="逗号分隔暴力 appid 列表，例如 '0,1,2,3,4,5'，每个发一帧")
    p.add_argument("--listen-secs", type=int, default=30)
    p.add_argument("--retry-1006", action="store_true",
                   help="若 processid=100 没有回包，自动重试 processid=1006 一次")
    p.add_argument("--no-encrypt", action="store_true",
                   help="不加密 request body（H13 假设 payload 明文）")
    p.add_argument("--before-round", type=int, default=0,
                   help="0=实时, 1=延迟回放（局结束后）")
    p.add_argument("--offset", type=int, default=0,
                   help="起始 offset，0 从头开始")
    args = p.parse_args()

    from remote.srs_spectator.client import SRSClient

    received_records = []
    received_resp_frames = []
    all_frames = []

    def parse_record_payload(data: bytes, askid: int):
        """解析回放 payload（zlib 解压后）的内部 0x2BC0/0x2BC1 帧并打印手牌指纹"""
        offset = 0
        cnt = 0
        while offset + 12 <= len(data) and cnt < 200:
            head = data[offset:offset + 12]
            pay_len = int.from_bytes(head[2:4], "little")
            mt = int.from_bytes(head[4:6], "little")
            if pay_len > 0 and offset + 12 + pay_len <= len(data) and mt in (0x2BC0, 0x2BC1):
                body = data[offset + 12:offset + 12 + pay_len]
                if len(body) >= 4:
                    sc = int.from_bytes(body[0:2], "little")
                    dl = int.from_bytes(body[2:4], "little")
                    sub_body = body[4:4 + dl]
                    if sc == 0x0003 and len(sub_body) >= 13:
                        h13 = list(sub_body[:13])
                        logger.warning("    🔥 DEAL frame body[:13]=%s has_3c=%s",
                                       h13, 0x3c in h13)
                    elif sc == 0x0216 and len(sub_body) >= 3:
                        pl, _, ct = sub_body[0], sub_body[1], sub_body[2]
                        if 0 < ct <= 20 and len(sub_body) >= 3 + ct:
                            h = list(sub_body[3:3 + ct])
                            logger.warning("    🔥 HAND_UPDATE player=%d count=%d hand=%s has_3c=%s",
                                           pl, ct, h, 0x3c in h)
            offset += 12 + max(0, pay_len)
            cnt += 1

    # 我们手工管理分片缓冲区（不用主仓 SpectatorClient，因为我们要自己控 wire）
    fragments: dict[int, dict] = {}

    def handle_spectator_resp(payload: bytes):
        meta = parse_spectator_resp(payload)
        if not meta:
            logger.warning("[3001] 太短: %dB head=%s", len(payload), payload[:32].hex())
            return
        logger.warning("[3001] askid=%d flag=%d room_id=%d max_off=%d cur=%d total=%d zip=%d size=%d",
                       meta["askid"], meta["flag"], meta["room_id"], meta["max_offset"],
                       meta["current"], meta["total"], meta["zip"], meta["payload_size"])
        received_resp_frames.append(meta)
        if meta["flag"] == 1:
            logger.error("flag=NOT_GOOD (1) — 数据不完整")
            return
        if meta["zip"] != 1:
            logger.warning("zip=%d != 1 — 不是回放数据", meta["zip"])
            return
        if meta["total"] == 0:
            logger.warning("total=0 — 旁观数据不存在")
            return
        # 累积分片
        f = fragments.setdefault(meta["askid"], {"total": meta["total"], "parts": {}})
        f["total"] = meta["total"]
        if meta["data"]:
            f["parts"][meta["current"]] = meta["data"]
        if len(f["parts"]) >= meta["total"]:
            merged = b"".join(f["parts"][i] for i in range(1, meta["total"] + 1)
                              if i in f["parts"])
            try:
                rec = zlib.decompress(merged)
            except zlib.error as e:
                logger.error("zlib 解压失败: %s", e)
                return
            logger.warning("=== 🎯 RECORD: %d bytes (after zlib) ===", len(rec))
            received_records.append(rec)
            outp = Path(f"/tmp/a4v5_record_{int(time.time())}.bin")
            outp.write_bytes(rec)
            logger.info("[saved] %s", outp)
            parse_record_payload(rec, meta["askid"])

    def on_frame(msg_type, payload):
        all_frames.append((msg_type, payload))
        logger.info("<< 0x%04x %dB head=%s", msg_type, len(payload), payload[:40].hex())
        # H13 实测：3001 响应 payload 是 PLAINTEXT（含明文 askid/roomid/zlib magic）
        # 0x0009 错误帧仍可能是密文，但第一字段是错误码，可两种都试
        if msg_type == 3001:
            handle_spectator_resp(payload)
        elif msg_type in (9, 0x0009):
            # REPORTSRSERR 解码尝试 (先按明文，再回退密文)
            if len(payload) >= 4:
                ec_pt = int.from_bytes(payload[:4], "little", signed=True)
                logger.warning("    SRS ERR plain ec=%d, body=%s", ec_pt, payload[4:].hex())
                try:
                    client._crypto.reset_cfb()
                    dec = client._crypto.decrypt_payload(payload)
                    ec_ct = int.from_bytes(dec[:4], "little", signed=True)
                    logger.warning("    SRS ERR enc->dec ec=%d, body=%s", ec_ct, dec[4:].hex())
                except Exception:
                    pass

    sent_askids: list[int] = []

    def send_one(processid: int, appid: int, label: str, encrypt: bool = True):
        askid = int(time.time() * 1000) & 0x7FFFFFFF
        sent_askids.append(askid)
        body = struct.pack("<iiii", askid, args.room_id, args.offset, args.before_round)
        if encrypt and client._crypto.key:
            client._crypto.reset_cfb()
            enc_body = client._crypto.encrypt_payload(body)
        else:
            enc_body = body
        frame = pack_frame_v5(3000, enc_body, processid, appid)
        logger.warning("=> [%s] processid=%d appid=%d askid=%d roomid=%d offset=%d before_round=%d enc=%s wire_hex=%s",
                       label, processid, appid, askid, args.room_id, args.offset, args.before_round,
                       encrypt, frame.hex())
        client._send_raw(frame)

    def on_handshake_done():
        logger.warning("=== handshake done ===")
        time.sleep(0.5)
        encrypt = not args.no_encrypt

        # appid 穷举模式：每个 appid 发一帧（用同一 sessionid，同一 processid）
        if args.appid_sweep:
            for ap in [int(x.strip()) for x in args.appid_sweep.split(",") if x.strip()]:
                send_one(args.processid, ap, f"sweep-pid={args.processid}-app={ap}", encrypt=encrypt)
                time.sleep(0.3)
        else:
            send_one(args.processid, args.appid, f"primary-pid={args.processid}-app={args.appid}", encrypt=encrypt)

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
                logger.info("got %d complete records, exit early", len(received_records))
                break
    except KeyboardInterrupt:
        pass

    # H4 兜底：如果 100 路径完全 0 个 3001 帧 → 试 1006
    if (not received_resp_frames) and args.retry_1006 and args.processid == 100:
        logger.warning("=== fallback: retry processid=1006 (MatchLinkProtocol) ===")
        send_one(1006, 0, "fallback-pid=1006-app=0", encrypt=not args.no_encrypt)
        deadline2 = time.time() + 15
        while time.time() < deadline2:
            time.sleep(1.0)
            if received_records or received_resp_frames:
                break

    client.disconnect()

    logger.warning("=== Total %d frames, %d 3001 resp, %d records ===",
                   len(all_frames), len(received_resp_frames), len(received_records))
    return 0 if received_records else (3 if received_resp_frames else 2)


if __name__ == "__main__":
    sys.exit(main())
