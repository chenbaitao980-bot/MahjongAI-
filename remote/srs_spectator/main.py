"""srs_spectator service — listens for roomid/gameid and watches games.

Runs on the cloud ECS (port 8001). Receives roomid/gameid from the relay
(which got them from the local extractor). Then connects to the game server,
completes SRS handshake, and begins watching.

Endpoints:
    POST /watch — start watching a game room
      body: {"roomid": 123, "gameid": 456, "api_token": "..."}
    GET  /status — check spectator status

Relay integration:
    srs_spectator pushes game data to relay:8000 via POST /push
"""
import os
import sys
import json
import logging
import threading
import time
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Set up sys.path for shared modules
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from .client import SRSClient

logger = logging.getLogger(__name__)

app = FastAPI(title="SRS Spectator", version="0.1.0")

# Configuration
GAME_SERVER_IP = os.environ.get("GAME_SERVER_IP", "47.96.0.227")
GAME_SERVER_PORT = int(os.environ.get("GAME_SERVER_PORT", "7777"))
RELAY_URL = os.environ.get("RELAY_URL", "http://127.0.0.1:8000")
API_TOKEN = os.environ.get("API_TOKEN", "")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN_12B", "")
HANDSHAKE_BLOB = os.environ.get("HANDSHAKE_BLOB", "")
SRS_SESSIONID = os.environ.get("SRS_SESSIONID", "")  # SRS PlayerConnect pwd (16B hex)
USERID = os.environ.get("USERID", "newpt1084306678")  # SRS PlayerConnect userid
BIND_HOST = os.environ.get("BIND_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("BIND_PORT", "8001"))


class WatchRequest(BaseModel):
    roomid: int
    gameid: int
    api_token: str


class WatchState:
    """Tracks active watch sessions."""

    def __init__(self):
        self.active_roomid: Optional[int] = None
        self.active_gameid: Optional[int] = None
        self.client: Optional[SRSClient] = None
        self.watching = False
        self.lock = threading.Lock()

    def start_watch(self, roomid: int, gameid: int) -> bool:
        with self.lock:
            if self.watching and self.active_roomid == roomid and self.active_gameid == gameid:
                return True

            self.stop_watch()

            if not AUTH_TOKEN or not HANDSHAKE_BLOB:
                logger.error("Missing AUTH_TOKEN_12B or HANDSHAKE_BLOB")
                return False

            logger.info(f"Starting watch: roomid={roomid} gameid={gameid}")
            client = SRSClient(
                GAME_SERVER_IP, GAME_SERVER_PORT,
                AUTH_TOKEN, HANDSHAKE_BLOB, SRS_SESSIONID,
                userid=USERID,
            )

            def on_record(data: bytes):
                """Called when a complete game record arrives."""
                logger.info(f"Game record: {len(data)} bytes")
                try:
                    self._push_to_relay(data)
                except Exception as e:
                    logger.error(f"Push failed: {e}")

            def on_handshake_done():
                logger.info("Handshake done, requesting spectator data...")
                client.request_spectator(roomid, gameid)

            client.on_spectator_record(on_record)
            client.on_handshake_done(on_handshake_done)

            if not client.connect(timeout=10.0):
                logger.error("Failed to connect to game server")
                return False

            self.client = client
            self.active_roomid = roomid
            self.active_gameid = gameid
            self.watching = True
            return True

    def stop_watch(self):
        if self.client:
            self.client.disconnect()
            self.client = None
        self.active_roomid = None
        self.active_gameid = None
        self.watching = False

    def _push_to_relay(self, data: bytes):
        """Push game record data to relay."""
        try:
            resp = requests.post(
                f"{RELAY_URL}/push",
                json={"snapshot": {"raw_data": data.hex()}, "api_token": API_TOKEN},
                timeout=5,
            )
            logger.debug(f"Push response: {resp.status_code}")
        except Exception as e:
            logger.error(f"Push to relay failed: {e}")


state = WatchState()


@app.post("/watch")
def start_watch(req: WatchRequest):
    if req.api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid api_token")

    ok = state.start_watch(req.roomid, req.gameid)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to start watch")
    return {"status": "watching", "roomid": req.roomid, "gameid": req.gameid}


@app.get("/status")
def get_status():
    return {
        "watching": state.watching,
        "roomid": state.active_roomid,
        "gameid": state.active_gameid,
    }


@app.post("/stop")
def stop_watch():
    state.stop_watch()
    return {"status": "stopped"}


def main():
    import uvicorn
    uvicorn.run(app, host=BIND_HOST, port=BIND_PORT)


if __name__ == "__main__":
    main()
