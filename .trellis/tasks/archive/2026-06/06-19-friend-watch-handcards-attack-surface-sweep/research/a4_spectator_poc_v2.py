"""PoC v2: 像 v1 一样发 ReqRealtimeGameRecord，但是把所有收到的帧都打印出来
（不仅仅是 MSG_SPECTATOR_RESP=3001），看服务端的真实回包/错误码/拒绝信号。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path:
    sys.path.insert(0, ECS_ROOT)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a4v2")

GAME_HOST = "47.96.0.227"
GAME_PORT = 7777


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--srs-sessionid", required=True)
    p.add_argument("--userid", default="newpt1084306678")
    p.add_argument("--room-id", type=int, required=True)
    p.add_argument("--game-id", type=int, required=True)
    p.add_argument("--listen-secs", type=int, default=30)
    args = p.parse_args()

    from remote.srs_spectator.client import SRSClient

    all_frames = []

    def on_frame(msg_type, payload):
        all_frames.append((msg_type, payload))
        logger.warning("<<< RAW FRAME msg_type=0x%04x len=%d hex=%s",
                       msg_type, len(payload), payload[:80].hex())

    def on_handshake_done():
        logger.warning("=== handshake done, requesting spectator data ===")
        time.sleep(0.3)
        client.request_spectator(args.room_id, args.game_id)

    client = SRSClient(
        host=GAME_HOST, port=GAME_PORT,
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
    except KeyboardInterrupt:
        pass
    client.disconnect()

    logger.warning("=== TOTAL %d frames received ===", len(all_frames))
    for msg_type, payload in all_frames:
        logger.warning("  msg_type=0x%04x len=%d", msg_type, len(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
