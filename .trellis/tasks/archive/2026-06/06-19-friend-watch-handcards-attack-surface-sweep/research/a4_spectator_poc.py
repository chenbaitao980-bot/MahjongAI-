"""PoC: 起独立 spectator 连接，订阅你当前那桌（roomid=935804, gameid=30114），
看 RespRealtimeGameRecord 的 zip payload 解开后是不是含**全员真实手牌**。

依赖：你的 srs_sessionid（用 noconfig multi-user 持久化的那个 9e86515f71cd...，
但要是新鲜的——服务端 idle timeout 120s，需要你正在打牌时跑）

流程：
  1. SSH 到 ECS 拿你的 srs_sessionid
  2. 在 ECS 上跑这个脚本（用 47.96.0.227:7777 直连游戏服）
  3. 完成 SRS 握手 -> 调 ReqRealtimeGameRecord(3000, room_id=935804)
  4. 接 RespRealtimeGameRecord fragment -> zip 解开
  5. 把 payload 喂给 stable 解码器，看 deal/hand_update 里
     player=0/2/3（不是 player=1=你）的 hand_raw 是真值还是 0x3C
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# 加 ECS 路径以便能 import remote.srs_spectator
ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path:
    sys.path.insert(0, ECS_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a4_verify")

GAME_HOST = "47.96.0.227"
GAME_PORT = 7777


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--srs-sessionid", required=True, help="你的 srs_sessionid (32 hex)")
    p.add_argument("--userid", default="newpt1084306678", help="SRS PlayerConnect userid")
    p.add_argument("--room-id", type=int, required=True)
    p.add_argument("--game-id", type=int, required=True)
    p.add_argument("--listen-secs", type=int, default=60)
    args = p.parse_args()

    from remote.srs_spectator.client import SRSClient

    received_payload = []

    def on_record(data: bytes):
        logger.info("=== Spectator record received: %d bytes (zip-decompressed) ===", len(data))
        received_payload.append(data)
        # 把原始字节落盘
        out_path = Path(f"/tmp/a4_record_{int(time.time())}.bin")
        out_path.write_bytes(data)
        logger.info("[saved] %s", out_path)

        # 用 stable 解码器解析
        try:
            from stable.protocol import MJProtocol
            proto = MJProtocol(server_port=GAME_PORT)
            # data 是 zip-decompressed payload，需要看具体格式（可能就是 0x2BC0 流的拼接）
            # 直接 hex dump 前 200 字节
            logger.info("[decode] first 200B hex: %s", data[:200].hex())

            # 尝试按 12B header 分帧
            offset = 0
            count = 0
            while offset + 12 <= len(data) and count < 50:
                head = data[offset:offset+12]
                # 假设格式跟 wire 一致：[dir(1) flag(1) pay_len(2) msg_type(2) sub_type(2) extra(4)]
                pay_len = int.from_bytes(head[2:4], "little")
                msg_type = int.from_bytes(head[4:6], "little")
                sub_type = int.from_bytes(head[6:8], "little")
                logger.info("  frame[%d] msg_type=0x%04x sub=0x%04x pay_len=%d",
                            count, msg_type, sub_type, pay_len)
                if pay_len > 0 and offset + 12 + pay_len <= len(data):
                    body = data[offset+12:offset+12+pay_len]
                    if msg_type == 0x2BC0 and len(body) >= 4:
                        sub_cmd = int.from_bytes(body[0:2], "little")
                        data_len = int.from_bytes(body[2:4], "little")
                        sub_body = body[4:4+data_len]
                        logger.info("    0x2BC0 sub_cmd=0x%04x data_len=%d body[:32]=%s",
                                    sub_cmd, data_len, sub_body[:32].hex())
                        if sub_cmd == 0x0003 and len(sub_body) >= 13:
                            hand13 = list(sub_body[:13])
                            has_3c = 0x3C in hand13
                            logger.info("    >>>>> DEAL frame: hand13=%s has_0x3C=%s",
                                        hand13, has_3c)
                        if sub_cmd == 0x0216 and len(sub_body) >= 3:
                            player = sub_body[0]
                            count_h = sub_body[2]
                            if 0 < count_h <= 20 and len(sub_body) >= 3 + count_h:
                                hand = list(sub_body[3:3+count_h])
                                has_3c = 0x3C in hand
                                logger.info("    >>>>> HAND_UPDATE player=%d count=%d hand=%s has_0x3C=%s",
                                            player, count_h, hand, has_3c)
                offset += 12 + max(0, pay_len)
                count += 1
        except Exception as e:
            logger.exception("[decode] failed: %s", e)

    def on_handshake_done():
        logger.info("=== handshake done, requesting spectator data ===")
        time.sleep(0.5)
        client.request_spectator(args.room_id, args.game_id)

    def on_disc():
        logger.info("=== disconnected ===")

    client = SRSClient(
        host=GAME_HOST, port=GAME_PORT,
        auth_token="", handshake_blob="",
        srs_sessionid=args.srs_sessionid,
        userid=args.userid,
    )
    client.on_spectator_record(on_record)
    client.on_handshake_done(on_handshake_done)
    client.on_disconnect(on_disc)

    if not client.connect(timeout=10.0):
        logger.error("connect failed")
        return 1

    logger.info("listening for %ds...", args.listen_secs)
    deadline = time.time() + args.listen_secs
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            if received_payload:
                logger.info("got record, exiting early")
                break
    except KeyboardInterrupt:
        pass
    client.disconnect()

    if not received_payload:
        logger.warning("没收到任何 spectator record (可能 sessionid 过期或 room_id 错误)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
