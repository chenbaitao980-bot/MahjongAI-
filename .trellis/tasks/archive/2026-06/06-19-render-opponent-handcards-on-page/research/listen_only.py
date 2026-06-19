"""PoC: 仅 connect + handshake, 不发任何 3000, 听 30s 看服务端是否主动推 3001."""
import argparse, logging, sys, time
ECS_ROOT = "/opt/mahjong-remote"
if ECS_ROOT not in sys.path: sys.path.insert(0, ECS_ROOT)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("listen")

p = argparse.ArgumentParser()
p.add_argument("--srs-sessionid", required=True)
p.add_argument("--userid", default="newpt1084306678")
p.add_argument("--lobby-host", default="47.96.101.155")
p.add_argument("--lobby-port", type=int, default=5748)
p.add_argument("--listen-secs", type=int, default=30)
args = p.parse_args()

from remote.srs_spectator.client import SRSClient

frames_seen = []
def on_frame(mt, payload):
    frames_seen.append(mt)
    if mt == 3001:
        logger.warning("<< 0x0bb9 (RespRealtimeGameRecord) %dB head=%s",
                       len(payload), payload[:48].hex())
    elif mt > 100:
        logger.info("<< msg=0x%04x (%d) %dB", mt, mt, len(payload))

def on_ready():
    logger.warning("=== handshake done, listening %ds, NO 3000 sent ===", args.listen_secs)

c = SRSClient(host=args.lobby_host, port=args.lobby_port,
              auth_token="", handshake_blob="",
              srs_sessionid=args.srs_sessionid, userid=args.userid)
c.on_frame(on_frame)
c.on_handshake_done(on_ready)
c.connect(timeout=10.0)
time.sleep(args.listen_secs)
c.disconnect()

from collections import Counter
print("Frame counts:", Counter(frames_seen))
print("3001 count:", frames_seen.count(3001))
