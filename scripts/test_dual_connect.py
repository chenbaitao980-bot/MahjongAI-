"""
test_dual_connect.py — Verify the "disconnect-window dual-connect" mechanism.

Background:
    When the phone's TCP connection is abruptly interrupted (e.g. WiFi toggle),
    the game server enters a grace period.  If cloud_player connects within that
    window, it is treated as "player reconnect" and a persistent dual connection
    is established: the phone can reconnect too, both connections co-exist, and
    cloud_player keeps receiving 0x2bc0 hand-tile frames for the entire game.

Usage:
    1. Enter a mahjong game on the phone.
    2. Run:  python scripts/test_dual_connect.py
    3. Toggle the phone's WiFi off for ~3 seconds, then back on.
    4. Watch the terminal — when the script prints "Dual connect established!",
       the current hand tiles will appear and continue updating.
    5. Ctrl-C to quit.

Requirements:
    - data/cloud_credentials.json  (produced by grab_credentials.bat / capture_credentials.py)
      Keys used: srs_sessionid, and optionally userid.

Dual-connect detection:
    The connection is considered "established" (not just a quick kick) when a
    0x2bc0 frame is received and the connection has been alive for >= 10 seconds.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading
from datetime import datetime

# ── path setup so we can import remote/ and stable/ without installing ────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
for _p in (_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── constants ─────────────────────────────────────────────────────────────────
CREDS_PATH = os.path.join(_ROOT, "data", "cloud_credentials.json")
RETRY_DELAY_SECONDS = 2          # seconds to wait between failed attempts
DUAL_CONNECT_MIN_ALIVE = 10      # connection must survive at least this long
                                  # before we consider it a dual-connect, not a kick

# ── logging (minimal — we print human-readable lines ourselves) ───────────────
logging.basicConfig(
    level=logging.INFO,  # DEBUG: show all frames
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _ts() -> str:
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def _print(msg: str) -> None:
    print(f"{_ts()} {msg}", flush=True)


# ── credential loading ────────────────────────────────────────────────────────

def load_credentials(path: str) -> dict:
    """Load credentials from JSON file.  Exits with a clear message on failure."""
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        print(f"\n[ERROR] Credentials file not found: {abs_path}")
        print("  Please run grab_credentials.bat (or capture_credentials.py) first")
        print("  to capture a fresh sessionid while the phone is in a game.\n")
        sys.exit(1)

    with open(abs_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not data.get("srs_sessionid"):
        print(f"\n[ERROR] 'srs_sessionid' is missing or empty in {abs_path}")
        print("  Re-run grab_credentials.bat to capture fresh credentials.\n")
        sys.exit(1)

    return data


# ── hand formatting ───────────────────────────────────────────────────────────

def _format_hand(state: dict) -> str:
    """Extract and format the local player's hand from a tracker snapshot."""
    local = state.get("local_player", 1)
    players = state.get("players", {})
    # tracker keys may be int or str depending on implementation
    player_info = players.get(local) or players.get(str(local)) or {}
    hand = player_info.get("hand", [])
    if not hand:
        return "(empty)"
    return " ".join(str(t) for t in hand)


# ── credential hot-reload (watch mode) ───────────────────────────────────────

# Connections that disconnect within this many seconds WITHOUT triggering
# on_connected are treated as flag-rejected (e.g. flag=72 sessionid expired).
_FLAG_REJECT_MAX_ALIVE = 5.0


def _wait_for_fresh_creds(creds_path: str, current_sessionid: str,
                          stop_event: threading.Event) -> dict | None:
    """Block until cloud_credentials.json is updated with a new sessionid.

    Returns the new credentials dict, or None if stop_event is set.
    """
    _print("[等待新凭证] 请让手机连接 PC 热点并进入游戏...")
    last_mtime = os.path.getmtime(creds_path) if os.path.exists(creds_path) else 0.0
    while not stop_event.is_set():
        stop_event.wait(timeout=2.0)
        if not os.path.exists(creds_path):
            continue
        try:
            mtime = os.path.getmtime(creds_path)
        except OSError:
            continue
        if mtime > last_mtime:
            try:
                new_creds = load_credentials(creds_path)
            except SystemExit:
                # load_credentials calls sys.exit on bad file; treat as not-ready
                last_mtime = mtime
                continue
            if new_creds.get("srs_sessionid") != current_sessionid:
                _print("[新凭证] sessionid 已更新，重试连接...")
                return new_creds
            last_mtime = mtime
    return None


# ── main dual-connect loop ────────────────────────────────────────────────────

def run(creds: dict) -> None:
    """Continuously attempt connections until a dual-connect is established,
    then keep printing hand updates until the user presses Ctrl-C.

    If a connection is rejected quickly (flag=72 / sessionid expired), the loop
    enters watch mode: it polls cloud_credentials.json for an updated sessionid
    and retries automatically once the file changes.
    """

    # Import here so path is set up already
    from remote.cloud_player import SRSPlayerClient, _GAME_SERVER_HOST, _GAME_SERVER_PORT

    sessionid: str = creds["srs_sessionid"]
    userid: str = creds.get("userid", "") or "newpt1084306678"

    _print("Starting dual-connect test — reconnecting until grace-period window is hit...")
    _print("Hint: enter a mahjong game on your phone, then toggle WiFi off 3s and back on.")
    _print(f"Game server: {_GAME_SERVER_HOST}:{_GAME_SERVER_PORT}  sessionid={sessionid[:8]}...")
    print()

    attempt = 0
    dual_connected = False
    stop_event = threading.Event()

    # Shared state written from the SRSPlayerClient callbacks
    _state: dict = {}
    _connect_time: list[float] = [0.0]   # mutable cell so closure can write it
    _first_frame_time: list[float] = [0.0]
    _last_hand: list[str] = [""]
    # Tracks whether on_connected fired for the current attempt (flag=0 path)
    _got_connected: list[bool] = [False]

    def on_state_update(state: dict) -> None:
        nonlocal dual_connected

        now = time.monotonic()
        hand_str = _format_hand(state)
        _state.update(state)

        if _first_frame_time[0] == 0.0:
            _first_frame_time[0] = now

        alive_for = now - _connect_time[0]

        if not dual_connected and alive_for >= DUAL_CONNECT_MIN_ALIVE:
            dual_connected = True
            _print(f"Dual connect established! (connection alive {alive_for:.1f}s)")
            _print(f"Hand: {hand_str}")
            _last_hand[0] = hand_str
            return

        if dual_connected:
            if hand_str != _last_hand[0]:
                phase = state.get("phase", "?")
                last_event = state.get("last_event", "")
                label = "draw" if "draw" in str(last_event).lower() else (
                    "discard" if "discard" in str(last_event).lower() else "update"
                )
                _print(f"Hand ({label}): {hand_str}")
                _last_hand[0] = hand_str

    def on_connected() -> None:
        _got_connected[0] = True  # flag=0 path confirmed

    def on_disconnected() -> None:
        pass  # outer loop handles reconnect printing

    while not stop_event.is_set():
        attempt += 1
        _print(f"Attempting connection... (attempt #{attempt})")
        _connect_time[0] = time.monotonic()
        _first_frame_time[0] = 0.0
        _got_connected[0] = False
        dual_connected_before = dual_connected

        client = SRSPlayerClient(
            srs_sessionid=sessionid,
            userid=userid,
            on_state_update=on_state_update,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )

        # Patch _run to single-attempt (avoid the built-in 2-attempt loop which
        # adds an 8-second delay we don't want here).
        client.start(block=False)

        # Wait for the background thread to exit (connection dropped / kicked)
        client.wait(timeout=None)   # blocks until thread finishes naturally

        if stop_event.is_set():
            break

        elapsed = time.monotonic() - _connect_time[0]

        # ── flag-rejection detection ──────────────────────────────────────────
        # If on_connected never fired AND the connection died very quickly, the
        # server rejected us (likely flag=72: sessionid expired). Enter watch
        # mode and wait for cloud_credentials.json to be refreshed.
        if not _got_connected[0] and elapsed < _FLAG_REJECT_MAX_ALIVE:
            _print(
                f"Connection rejected after {elapsed:.1f}s (sessionid likely expired, flag=72)."
            )
            new_creds = _wait_for_fresh_creds(CREDS_PATH, sessionid, stop_event)
            if new_creds is None:
                # stop_event was set (Ctrl-C)
                break
            sessionid = new_creds["srs_sessionid"]
            userid = new_creds.get("userid", "") or userid
            _print(f"Resuming with new sessionid={sessionid[:8]}...")
            # Reset attempt counter so numbering is intuitive after credential reload
            attempt = 0
            continue

        # ── normal reconnect logic ────────────────────────────────────────────
        if dual_connected and not dual_connected_before:
            # We just got kicked after establishing dual connect — unusual, re-connect quickly
            _print(f"Dual connect dropped after {elapsed:.1f}s — reconnecting immediately...")
            # Don't reset dual_connected; the next connection should pick up mid-game
            continue

        if dual_connected:
            # Was already in dual-connect mode and connection dropped again
            _print(f"Connection dropped after {elapsed:.1f}s — reconnecting in {RETRY_DELAY_SECONDS}s...")
        else:
            _print(f"Kicked (survived {elapsed:.1f}s) — waiting {RETRY_DELAY_SECONDS}s before retry...")

        # Interruptible sleep
        stop_event.wait(timeout=RETRY_DELAY_SECONDS)

    _print("Stopped.")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    creds = load_credentials(CREDS_PATH)

    try:
        run(creds)
    except KeyboardInterrupt:
        print()
        _print("Ctrl-C received — exiting.")


if __name__ == "__main__":
    main()
