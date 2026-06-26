"""
test_spectator.py — Verify spectator protocol: what data does it actually return?

Key questions:
  1. Can we connect as spectator without interfering with the phone's connection?
  2. Does the server respond to ReqRealtimeGameRecord?
  3. What data do we get? Hand tiles or only public info?

This uses the SAME sessionid as the phone (same account) but as a
spectator connection. We need room_id + game_id from the current game.

Usage:
    python scripts/test_spectator.py --sessionid <hex32> --roomid <int> --gameid <int>
    python scripts/test_spectator.py  # auto-read credentials + room info
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import struct

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
for _p in (_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CREDS_PATH = os.path.join(_ROOT, "data", "cloud_credentials.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("spectator_test")


def _ts() -> str:
    import datetime
    return datetime.datetime.now().strftime("[%H:%M:%S]")


def _print(msg: str) -> None:
    print(f"{_ts()} {msg}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessionid", default="")
    parser.add_argument("--roomid", type=int, default=0)
    parser.add_argument("--gameid", type=int, default=0)
    args = parser.parse_args()

    _print("=" * 60)
    _print("SPECTATOR PROTOCOL TEST")
    _print("=" * 60)
    print()

    # ── Get sessionid ───────────────────────────────────────────────
    sessionid = args.sessionid
    if not sessionid and os.path.isfile(CREDS_PATH):
        with open(CREDS_PATH, "r", encoding="utf-8") as f:
            creds = json.load(f)
        sessionid = creds.get("srs_sessionid", "")
        if not args.roomid:
            args.roomid = creds.get("room_id", 0) or 0
        if not args.gameid:
            args.gameid = creds.get("game_id", 0) or 0

    if not sessionid:
        _print("[ERROR] No sessionid. Run capture_credentials.py first.")
        sys.exit(1)

    _print(f"  Sessionid: {sessionid[:8]}...{sessionid[-4:]}")
    _print(f"  Room ID:   {args.roomid}")
    _print(f"  Game ID:   {args.gameid}")
    print()

    if not args.roomid:
        _print("[WARN] No room_id. Need to capture one from a live game.")
        _print("  Run capture_credentials.py while phone enters a game,")
        _print("  then re-run this script with --roomid <id> --gameid <id>")
        print()

    # ── Connect as spectator ────────────────────────────────────────
    _print("Connecting to game server as spectator...")

    from remote.srs_spectator.client import SRSClient

    handshake_done = False
    got_frames = []
    got_records = []
    got_disconnected = False

    def on_frame(msg_type, payload):
        nonlocal handshake_done
        name = {1: "EncryptVer", 3: "ReqKey", 4: "HandshakeRsp",
                5: "PlayerConnect", 6: "PlayerData", 23: "ReqPlusData",
                24: "RespPlusData", 3001: "SpectatorResp"}.get(msg_type, f"0x{msg_type:04X}")
        _print(f"  Frame: {name} ({len(payload)}B) hex={payload[:32].hex()}...")
        got_frames.append((msg_type, len(payload), payload[:32].hex()))

    def on_handshake_done_cb():
        nonlocal handshake_done
        handshake_done = True
        _print("  Handshake complete!")

        if args.roomid:
            _print(f"  Requesting spectator data: roomid={args.roomid} gameid={args.gameid}")
            client.request_spectator(args.roomid, args.gameid)
        else:
            _print("  No roomid - just listening for all frames...")

    def on_disconnect():
        nonlocal got_disconnected
        got_disconnected = True
        _print("  Disconnected from server.")

    def on_record(data):
        _print(f"  *** GOT SPECTATOR RECORD: {len(data)} bytes ***")
        # Try to parse the data
        _print(f"  First 64 bytes hex: {data[:64].hex()}")
        # Try to interpret as various formats
        try:
            text = data.decode("utf-8", errors="replace")
            if any(c.isalpha() for c in text[:50]):
                _print(f"  As text: {text[:200]}")
        except Exception:
            pass
        # Try protobuf-like parsing
        _print(f"  Raw bytes (first 100): {list(data[:100])}")
        got_records.append(data)

    client = SRSClient(
        host="47.96.0.227",
        port=7777,
        auth_token="",
        handshake_blob="",
        srs_sessionid=sessionid,
        userid="newpt1084306678",
    )

    client.on_frame(on_frame)
    client.on_handshake_done(on_handshake_done_cb)
    client.on_disconnect(on_disconnect)
    client.on_spectator_record(on_record)

    connected = client.connect(timeout=10.0)
    if not connected:
        _print("[ERROR] Failed to connect to game server.")
        sys.exit(1)

    _print("  TCP connected. Waiting for handshake...")

    # Wait up to 30 seconds for activity
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline and not got_disconnected:
            time.sleep(1)
            if handshake_done and got_records:
                # Got data, wait a bit more for additional records
                time.sleep(5)
                break
    except KeyboardInterrupt:
        pass

    client.disconnect()

    # ── Results ─────────────────────────────────────────────────────
    print()
    _print("=" * 60)
    _print("RESULTS")
    _print("=" * 60)
    _print(f"  Handshake completed: {handshake_done}")
    _print(f"  Frames received:    {len(got_frames)}")
    _print(f"  Spectator records:  {len(got_records)}")
    _print(f"  Disconnected:       {got_disconnected}")
    print()

    if got_records:
        _print("  Spectator record details:")
        for i, rec in enumerate(got_records):
            _print(f"    Record {i}: {len(rec)} bytes")
            _print(f"      First 64 hex: {rec[:64].hex()}")
    elif handshake_done and args.roomid:
        _print("  No spectator records received.")
        _print("  Possible reasons:")
        _print("    - Room ID / Game ID is wrong or expired")
        _print("    - Server doesn't respond to spectator requests from this connection type")
        _print("    - Spectator data is only available during active games")
    elif handshake_done and not args.roomid:
        _print("  No room_id provided - could not request spectator data.")
        _print("  However, we confirmed that the SRS connection works!")
        _print("  Frame summary:")
        for msg_type, size, hex_preview in got_frames:
            name = {1: "EncryptVer", 3: "ReqKey", 4: "HandshakeRsp",
                    6: "PlayerData", 24: "RespPlusData"}.get(msg_type, f"0x{msg_type:04X}")
            _print(f"    {name}: {size}B")

    # Check if phone gets kicked
    print()
    _print("IMPORTANT: Check your phone - is the game still connected?")
    _print("  If yes → spectator connection doesn't interfere with phone!")
    _print("  If no  → same-account spectator also kicks phone (互踢)")

    print()
    _print("Test complete.")


if __name__ == "__main__":
    main()
