"""PoC v4: 改连 lobby 5045 而不是 game 7777，发 ReqRealtimeGameRecord(3000)
看是否回 RespRealtimeGameRecord(3001) 的 zip payload"""
from __future__ import annotations

import logging, sys, time
from pathlib import Path

ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path:
    sys.path.insert(0, ECS_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a4v4")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--srs-sessionid", required=True)
    p.add_argument("--userid", default="newpt1084306678")
    p.add_argument("--lobby-host", default="47.96.0.227", help="lobby host (default 真服)")
    p.add_argument("--lobby-port", type=int, default=5045, help="lobby port")
    p.add_argument("--room-id", type=int, required=True)
    p.add_argument("--game-id", type=int, required=True)
    p.add_argument("--listen-secs", type=int, default=30)
    args = p.parse_args()

    from remote.srs_spectator.client import SRSClient

    received_payload = []
    all_frames = []

    def on_record(data):
        logger.warning("=== 🎯 SPECTATOR RECORD: %d bytes (zip-decompressed) ===", len(data))
        received_payload.append(data)
        out = Path(f"/tmp/a4v4_record_{int(time.time())}.bin")
        out.write_bytes(data)
        logger.info("[saved] %s", out)
        # 解析所有 0x2BC0/0x2BC1 帧并打印 player_id + sub_cmd
        offset = 0; cnt = 0
        while offset + 12 <= len(data) and cnt < 100:
            head = data[offset:offset+12]
            pay_len = int.from_bytes(head[2:4], "little")
            mt = int.from_bytes(head[4:6], "little")
            if pay_len > 0 and offset+12+pay_len <= len(data) and mt in (0x2BC0, 0x2BC1):
                body = data[offset+12:offset+12+pay_len]
                if len(body) >= 4:
                    sc = int.from_bytes(body[0:2], "little")
                    dl = int.from_bytes(body[2:4], "little")
                    sub_body = body[4:4+dl]
                    if sc == 0x0003 and len(sub_body) >= 13:
                        h13 = list(sub_body[:13])
                        logger.warning("    🔥 DEAL frame body[:13]=%s has_3c=%s", h13, 0x3c in h13)
                    elif sc == 0x0216 and len(sub_body) >= 3:
                        pl, _, ct = sub_body[0], sub_body[1], sub_body[2]
                        if 0 < ct <= 20 and len(sub_body) >= 3+ct:
                            h = list(sub_body[3:3+ct])
                            logger.warning("    🔥 HAND_UPDATE player=%d count=%d hand=%s has_3c=%s",
                                           pl, ct, h, 0x3c in h)
            offset += 12 + max(0, pay_len)
            cnt += 1

    def on_frame(msg_type, payload):
        all_frames.append((msg_type, payload))
        logger.info("<< 0x%04x %dB head=%s", msg_type, len(payload), payload[:40].hex())

    def on_handshake_done():
        logger.warning("=== handshake done, sending ReqRealtimeGameRecord(3000) ===")
        time.sleep(0.5)
        client.request_spectator(args.room_id, args.game_id)

    client = SRSClient(
        host=args.lobby_host, port=args.lobby_port,
        auth_token="", handshake_blob="",
        srs_sessionid=args.srs_sessionid,
        userid=args.userid,
    )
    client.on_spectator_record(on_record)
    client.on_frame(on_frame)
    client.on_handshake_done(on_handshake_done)

    if not client.connect(timeout=10.0):
        logger.error("connect failed")
        return 1

    deadline = time.time() + args.listen_secs
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            if received_payload:
                logger.info("got %d records, exit early", len(received_payload))
                break
    except KeyboardInterrupt:
        pass
    client.disconnect()

    logger.warning("=== Total %d frames, %d records ===", len(all_frames), len(received_payload))
    return 0 if received_payload else 2


if __name__ == "__main__":
    sys.exit(main())
