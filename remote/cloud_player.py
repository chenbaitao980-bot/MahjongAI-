"""
remote/cloud_player.py — Cloud Player: connect to game server as local player (Path C)

Two entry points:
  1. extract_credentials_from_pcap(pcap_path) -> dict
       Reads a pcap file and extracts srs_sessionid and room_id.

  2. SRSPlayerClient class
       Uses srs_sessionid to authenticate and receive 0x2bc0 game frames,
       feeding them to stable/tracker.py for BattleState reconstruction.

CLI usage:
    # Extract credentials from pcap file
    python remote/cloud_player.py --pcap path/to/capture.pcap

    # Connect directly with a known sessionid
    python remote/cloud_player.py --sessionid <hex16>

Dependencies (pip install scapy) required for pcap mode.
"""
from __future__ import annotations

import argparse
import logging
import os
import struct
import sys
import threading
import time
from typing import Any, Callable

# ── sys.path setup (same convention as other remote/ modules) ──────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")
for _p in (_ROOT, _RELAY_DIR, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

# Game server address (from spec: game_server_ip in config_hotspot.yaml)
_GAME_SERVER_HOST = "47.96.0.227"
_GAME_SERVER_PORT = 7777

# Default player identity (known-good from live pcap)
_DEFAULT_USERID = "newpt1084306678"
_DEFAULT_AREAID = 7109
_DEFAULT_IDENTIFY = b"020000000000"
_DEFAULT_CHANNELID = 70900
_DEFAULT_OSVER = 10160
_DEFAULT_N_GAME_ID = 900535


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — Credential extraction from pcap
# ─────────────────────────────────────────────────────────────────────────────

def extract_credentials_from_pcap(pcap_path: str) -> dict:
    """Extract srs_sessionid and room_id from a captured pcap file.

    Requires ``pip install scapy`` for pcap parsing.

    The function locates:
      - srs_sessionid: decrypted from SRS HandshakeRsp (S->C, msg=4) +
        PlayerConnect (C->S, msg=5) using AES-256-CFB128 with the static
        default key (from libcocos2dlua.so .rodata).
      - room_id / game_id: from RespJoinTable (S->C, msg=14, RoomProtocol)
        at payload offsets [17..20] and [21..24] (LE int32).

    Returns a dict with keys:
        srs_sessionid: str  (hex, 32 chars = 16 bytes)  or ""
        room_id:       int  or None
        game_id:       int  or None
        identify:      str  (hex) or ""
        handshake_blob: str (hex) or ""
        auth_token_12b: str (hex) or ""

    Raises FileNotFoundError if pcap_path does not exist.
    Raises ImportError if scapy is not installed (pcap parsing dependency).
    """
    if not os.path.isfile(pcap_path):
        raise FileNotFoundError(f"pcap file not found: {pcap_path}")

    from stable.protocol import MJProtocol, PcapParser
    from remote.extractor.token_extractor import TokenExtractor, SRSSessionExtractor

    parser = PcapParser()
    protocol = MJProtocol(server_port=_GAME_SERVER_PORT)
    token_ext = TokenExtractor()
    srs_ext = SRSSessionExtractor()

    logger.info("Parsing pcap: %s", pcap_path)
    with open(pcap_path, "rb") as fh:
        data = fh.read()

    packets = parser.feed(data)
    logger.info("Parsed %d packets", len(packets))

    for pkt in packets:
        messages = protocol.process_packet(pkt)
        for msg in messages:
            token_ext.feed(msg)
            srs_ext.feed(msg)

    result: dict[str, Any] = {
        "srs_sessionid": srs_ext.sessionid.hex() if srs_ext.sessionid else "",
        "room_id": token_ext.room_id,
        "game_id": token_ext.game_id,
        "identify": srs_ext.identify.hex() if srs_ext.identify else "",
        "handshake_blob": token_ext.handshake_blob.hex() if token_ext.handshake_blob else "",
        "auth_token_12b": token_ext.auth_token_12b.hex() if token_ext.auth_token_12b else "",
    }

    logger.info(
        "Extraction complete: sessionid=%s room_id=%s game_id=%s",
        result["srs_sessionid"][:16] + "..." if result["srs_sessionid"] else "(none)",
        result["room_id"],
        result["game_id"],
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — SRSPlayerClient: cloud-side player connection
# ─────────────────────────────────────────────────────────────────────────────

class SRSPlayerClient:
    """Connect to the game server as the local player using a srs_sessionid.

    Flow:
      1. TCP connect to game server port 7777
      2. SRS handshake: EncryptVer -> ReqKey <- HandshakeRsp -> PlayerConnect
         <- PlayerData (flag=0 = success)
      3. Send ReqPlayerPlusData <- RespPlayerPlusData (m_key)
      4. Receive 0x2bc0 game event frames continuously
      5. Feed frames into MJProtocol + PacketStateTracker for BattleState

    Usage:
        client = SRSPlayerClient(
            srs_sessionid="a269e12a1ca5442db00ec625a0d0e619",
            on_state_update=my_callback,   # called on each BattleState change
        )
        client.start()
        # ... blocks or runs in background ...
        client.stop()
    """

    # How many seconds to wait between reconnect attempts in continuous mode.
    RETRY_DELAY_SECONDS = 2

    def __init__(
        self,
        srs_sessionid: str,
        host: str = _GAME_SERVER_HOST,
        port: int = _GAME_SERVER_PORT,
        userid: str = _DEFAULT_USERID,
        areaid: int = _DEFAULT_AREAID,
        identify: bytes = _DEFAULT_IDENTIFY,
        channelid: int = _DEFAULT_CHANNELID,
        osver: int = _DEFAULT_OSVER,
        n_game_id: int = _DEFAULT_N_GAME_ID,
        on_state_update: Callable | None = None,
        on_connected: Callable | None = None,
        on_disconnected: Callable | None = None,
        continuous: bool = False,
    ):
        """
        Args:
            srs_sessionid: Hex string (32 chars = 16 bytes). The player's
                           current session token, extracted from pcap or
                           passed manually.
            host:          Game server host (default 47.96.0.227).
            port:          Game server port (default 7777).
            userid:        Account user ID string.
            areaid:        Area/server ID (default 7109).
            identify:      Device fingerprint bytes (default known-good value).
            channelid:     Channel ID (default 70900).
            osver:         OS version field (default 10160).
            n_game_id:     Game ID field (default 900535).
            on_state_update: Callback(battle_state: BattleState) on each change.
            on_connected:    Callback() when handshake succeeds (flag=0).
            on_disconnected: Callback() when connection drops.
            continuous:      If True, reconnect indefinitely after disconnect
                             (RETRY_DELAY_SECONDS between attempts). Suitable for
                             the "disconnect-window dual-connect" pattern.
                             If False (default), use the legacy 2-attempt behavior.
        """
        self.continuous = continuous
        self.host = host
        self.port = port
        self.srs_sessionid = bytes.fromhex(srs_sessionid) if srs_sessionid else b"\x00" * 16
        self.userid = userid
        self.areaid = areaid
        self.identify = identify
        self.channelid = channelid
        self.osver = osver
        self.n_game_id = n_game_id
        self._on_state_update = on_state_update
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        self._stop_requested = False
        self._thread: threading.Thread | None = None

        # Lazy-initialised per-connection state (rebuilt on each reconnect)
        self._client = None       # SRSClient instance
        self._protocol = None     # MJProtocol instance
        self._tracker = None      # PacketStateTracker instance
        self._auth_flag = -1      # last PlayerData flag received

    # ── public API ────────────────────────────────────────────────────────

    def start(self, block: bool = False) -> None:
        """Start the client in a background thread (or blocking if block=True)."""
        self._stop_requested = False
        if block:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True, name="SRSPlayerClient")
            self._thread.start()

    def stop(self) -> None:
        """Signal the client to stop and disconnect."""
        self._stop_requested = True
        if self._client:
            self._client.disconnect()

    def wait(self, timeout: float | None = None) -> None:
        """Wait for the background thread to finish."""
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def battle_state(self):
        """Return the current BattleState, or None if no game in progress."""
        if self._tracker is None:
            return None
        return self._tracker.to_battle_state()

    # ── internal loop ─────────────────────────────────────────────────────

    # How long (seconds) to wait for game frames before giving up this connection.
    # Kept short so an accidental start (phone not in game yet) exits quickly
    # without holding the session and blocking the phone.
    IDLE_GAME_TIMEOUT = 60   # 1 minute

    def _run(self) -> None:
        """Connection loop.

        continuous=False (default / legacy):
            Connects once. If game frames arrive → stays alive for the whole game.
            If the connection drops mid-game → one quick reconnect attempt.
            If no game frames within IDLE_GAME_TIMEOUT → exits cleanly.
            With systemd Restart=no this service only runs when explicitly started
            via /api/start-player. No reconnect loop = no anomaly traffic.

        continuous=True:
            Reconnects indefinitely until stop() is called, with
            RETRY_DELAY_SECONDS between attempts. Designed for the
            "disconnect-window dual-connect" pattern where the phone drops
            and cloud reconnects into the server's grace period.
        """
        if self.continuous:
            self._run_continuous()
        else:
            self._run_legacy()
        logger.info("SRSPlayerClient: stopped.")

    def _run_legacy(self) -> None:
        """Legacy 2-attempt mode (continuous=False)."""
        for attempt in range(2):
            if self._stop_requested:
                break
            if attempt > 0:
                logger.info("SRSPlayerClient: mid-game reconnect in 8s (attempt 2/2)...")
                self._sleep(8)

            logger.info("SRSPlayerClient: connecting to %s:%d (attempt %d/2)...",
                        self.host, self.port, attempt + 1)
            try:
                was_in_game = self._connect_once()
            except Exception as exc:
                logger.error("SRSPlayerClient: unexpected error: %s", exc, exc_info=True)
                break

            if was_in_game is None:
                logger.warning("SRSPlayerClient: TCP connect failed, stopping")
                break
            elif was_in_game:
                # Received frames then disconnected → allow one reconnect
                logger.info("SRSPlayerClient: mid-game disconnect (%d frames received)",
                            self._game_frames_received)
                continue
            else:
                logger.info(
                    "SRSPlayerClient: no game frames in %ds — phone not in game yet. "
                    "Enter game first, then click Start Monitor.",
                    self.IDLE_GAME_TIMEOUT,
                )
                break

    def _run_continuous(self) -> None:
        """Continuous reconnect mode (continuous=True).

        Loops until stop() is called. After each disconnect (whether kicked
        immediately or after receiving frames), waits RETRY_DELAY_SECONDS
        then tries again. This matches the test_dual_connect.py outer loop.
        """
        attempt = 0
        while not self._stop_requested:
            attempt += 1
            logger.info("SRSPlayerClient [continuous]: connecting to %s:%d (attempt #%d)...",
                        self.host, self.port, attempt)
            try:
                was_in_game = self._connect_once()
            except Exception as exc:
                logger.error("SRSPlayerClient [continuous]: unexpected error: %s", exc, exc_info=True)
                # Brief sleep before retry even on unexpected errors
                self._sleep(self.RETRY_DELAY_SECONDS)
                continue

            if self._stop_requested:
                break

            if was_in_game is None:
                logger.info("SRSPlayerClient [continuous]: TCP connect failed, retrying in %ds...",
                            self.RETRY_DELAY_SECONDS)
            elif was_in_game:
                logger.info("SRSPlayerClient [continuous]: disconnected after %d frames, "
                            "retrying in %ds...",
                            self._game_frames_received, self.RETRY_DELAY_SECONDS)
            else:
                logger.info("SRSPlayerClient [continuous]: no game frames in %ds, "
                            "retrying in %ds...",
                            self.IDLE_GAME_TIMEOUT, self.RETRY_DELAY_SECONDS)

            self._sleep(self.RETRY_DELAY_SECONDS)

    def _sleep(self, seconds: float) -> None:
        """Interruptible sleep: wakes up if stop() is called."""
        deadline = time.monotonic() + seconds
        while not self._stop_requested and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    def _connect_once(self):
        """Open one TCP connection, complete handshake, receive frames until disconnect.

        Returns:
            None   — TCP connect itself failed (backoff and retry)
            False  — Connected + handshake ok, but NO game frames received within
                     IDLE_GAME_TIMEOUT seconds (phone not in game; long wait before retry)
            True   — Connected, received at least one game frame, then disconnected
                     (mid-game dropout; retry quickly)
        """
        try:
            from remote.srs_spectator.client import SRSClient
        except ImportError:
            from srs_spectator.client import SRSClient

        from stable.protocol import MJProtocol
        from stable.mapping import MappingStore

        self._protocol = MJProtocol(server_port=self.port)
        mapping_store = MappingStore(path=None)
        self._tracker = _PatchedPacketStateTracker(mapping_store)
        self._game_frames_received = 0

        self._client = SRSClient(
            host=self.host,
            port=self.port,
            auth_token="",
            handshake_blob="",
            srs_sessionid=self.srs_sessionid.hex(),
            userid=self.userid,
        )

        self._client.on_frame(self._on_frame)
        self._client.on_handshake_done(self._on_handshake_done_cb)
        self._client.on_disconnect(self._on_disconnect_cb)

        self._auth_flag = -1
        connected = self._client.connect(timeout=10.0)
        if not connected:
            return None  # TCP failed

        # Wait for recv thread to finish, but enforce an idle-game timeout:
        # if no 0x2bc0 frames arrive within IDLE_GAME_TIMEOUT, disconnect proactively.
        recv_thread = self._client._recv_thread
        if recv_thread:
            deadline = time.monotonic() + self.IDLE_GAME_TIMEOUT
            while recv_thread.is_alive():
                if self._stop_requested:
                    self._client.disconnect()
                    break
                if self._game_frames_received == 0 and time.monotonic() > deadline:
                    logger.info(
                        "SRSPlayerClient: idle timeout (%ds, no game frames) — "
                        "disconnecting to free phone game entry",
                        self.IDLE_GAME_TIMEOUT,
                    )
                    self._client.disconnect()
                    break
                recv_thread.join(timeout=1.0)

        was_in_game = self._game_frames_received > 0
        return was_in_game

    # ── frame handlers ────────────────────────────────────────────────────

    def _on_frame(self, msg_type: int, payload: bytes) -> None:
        """Receive hook for every frame from the server (post-handshake too).

        Note: payload here is the raw (still-encrypted) wire payload as delivered
        by SRSClient._recv_loop. For PlayerData (msg=6), SRSClient already logs
        the flag internally; we rely on that rather than trying to decrypt here.
        For game event frames (0x2BC0), these arrive after the handshake is complete
        and the game server sends them in plaintext (per stable/protocol.py design —
        the 0x2bc0 game event stream is not additionally encrypted).
        """
        if msg_type == 0x2BC0:
            self._game_frames_received = getattr(self, "_game_frames_received", 0) + 1
            self._handle_game_event(payload)

    def _on_handshake_done_cb(self) -> None:
        """Called when SRS handshake is complete (m_key received)."""
        logger.info(
            "SRSPlayerClient: handshake done, auth_flag=%d. Waiting for game frames...",
            self._auth_flag,
        )
        if self._on_connected:
            try:
                self._on_connected()
            except Exception as exc:
                logger.debug("on_connected callback error: %s", exc)

    def _on_disconnect_cb(self) -> None:
        """Called from recv thread on connection loss."""
        logger.info("SRSPlayerClient: disconnected.")
        if self._on_disconnected:
            try:
                self._on_disconnected()
            except Exception as exc:
                logger.debug("on_disconnected callback error: %s", exc)

    def _handle_game_event(self, payload: bytes) -> None:
        """Decode a raw 0x2bc0 payload and feed to tracker."""
        if not payload or len(payload) < 4:
            return
        if self._protocol is None or self._tracker is None:
            return

        # Reconstruct the full 12-byte MJ frame header + payload so that
        # MJProtocol.process_packet() can parse it via its normal path.
        # src_port=self.port causes direction="S->C" (server sent it to us).
        full_frame = _build_mj_frame(0x2BC0, payload)
        pkt = {
            "src": f"{self.host}:{self.port}",
            "dst": "127.0.0.1:0",
            "src_port": self.port,
            "dst_port": 0,
            "payload": full_frame,
        }
        messages = self._protocol.process_packet(pkt)
        changed = False
        for msg in messages:
            if self._tracker.apply(msg):
                changed = True

        if changed and self._on_state_update:
            try:
                state = self._tracker.to_battle_state()
                if state:
                    self._on_state_update(state)
            except Exception as exc:
                logger.debug("on_state_update callback error: %s", exc)


def _build_mj_frame(msg_type: int, payload: bytes) -> bytes:
    """Build a 12-byte MJ frame header + payload for MJProtocol parsing.

    MJ frame header (12 bytes):
      Byte 0:    direction (0x00=S->C)
      Byte 1:    frame_type (0x40=normal)
      Bytes 2-3: pay_len (LE uint16)
      Bytes 4-5: msg_type (LE uint16)
      Bytes 6-7: sub_type (LE uint16, 0)
      Bytes 8-11: extra (4 bytes, zeros)
    """
    hdr = struct.pack(
        "<BBHHHI",
        0x00,              # direction: S->C
        0x40,              # frame_type: normal
        len(payload),      # pay_len
        msg_type,          # msg_type
        0,                 # sub_type
        0,                 # extra
    )
    return hdr + payload


class _PatchedPacketStateTracker:
    """Thin wrapper around PacketStateTracker that adds a to_battle_state() helper."""

    def __init__(self, mapping_store):
        from stable.tracker import PacketStateTracker
        self._tracker = PacketStateTracker(mapping_store, local_player=1)

    def apply(self, message) -> bool:
        return self._tracker.apply(message)

    def to_battle_state(self):
        """Convert tracker state to BattleState snapshot dict (same format as snapshot())."""
        t = self._tracker
        # Return a simple snapshot dict compatible with the existing pipeline
        players = {}
        for pid, ps in t.players.items():
            players[pid] = {
                "hand": list(ps.hand),
                "hand_count": ps.hand_count,
                "discards": list(ps.discards),
                "melds": list(ps.melds),
            }
        return {
            "phase": t.phase,
            "current_turn": t.current_turn,
            "remaining_tiles": t.remaining_tiles,
            "baida_tile": t.baida_tile,
            "players": players,
            "local_player": t.local_player,
            "hand_trusted": t.hand_trusted,
            "last_event": t.last_event,
            "event_log": list(t.event_log[-10:]),
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def push_to_relay(relay_url: str, api_token: str, state: dict) -> None:
    """POST state snapshot to relay /push. Fire-and-forget; errors are logged, not raised."""
    import requests as _req
    try:
        resp = _req.post(
            f"{relay_url.rstrip('/')}/push",
            json={"snapshot": state, "api_token": api_token},
            timeout=3,
        )
        if resp.status_code != 200:
            logger.debug("relay push returned %d: %s", resp.status_code, resp.text[:120])
    except Exception as exc:
        logger.debug("relay push failed: %s", exc)


def _load_creds(creds_path: str) -> dict:
    """Load credentials from a JSON file produced by capture_credentials.py."""
    import json as _json
    path = os.path.abspath(creds_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Credentials file not found: {path}\n"
                                f"  Run grab_credentials.bat first.")
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    if not data.get("srs_sessionid"):
        raise ValueError(f"srs_sessionid missing in {path}.\n"
                         f"  Re-run grab_credentials.bat to capture fresh credentials.")
    return data


def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Cloud player client — connect as local player or extract credentials from pcap.",
    )
    parser.add_argument("--pcap", help="Path to pcap file for credential extraction.")
    parser.add_argument("--sessionid", help="SRS sessionid hex string (32 hex chars = 16 bytes).")
    parser.add_argument("--creds", default="data/cloud_credentials.json",
                        help="Path to credentials JSON from grab_credentials.bat (default: data/cloud_credentials.json).")
    parser.add_argument("--relay", default="",
                        help="Relay URL to push state updates, e.g. http://localhost:8003")
    parser.add_argument("--api-token", default="cloudmode2026",
                        help="API token for relay /push (default: cloudmode2026)")
    parser.add_argument("--userid", default=_DEFAULT_USERID, help="Account user ID.")
    parser.add_argument("--host", default=_GAME_SERVER_HOST, help="Game server host.")
    parser.add_argument("--port", type=int, default=_GAME_SERVER_PORT, help="Game server port.")
    args = parser.parse_args()

    # When running as a systemd service, credentials may not exist yet.
    # Wait until the file appears (uploaded via /api/creds by grab_credentials.bat).
    if not args.pcap and not args.sessionid:
        creds_path = os.path.abspath(args.creds)
        if not os.path.isfile(creds_path):
            print(f"[cloud_player] Credentials not found at {creds_path}")
            print(f"[cloud_player] Waiting for grab_credentials.bat to upload credentials ...")
            while not os.path.isfile(creds_path):
                time.sleep(5)
            print(f"[cloud_player] Credentials file appeared, loading ...")

    if args.pcap:
        # Mode 1: Extract credentials from pcap
        print(f"[cloud_player] Extracting credentials from: {args.pcap}")
        try:
            result = extract_credentials_from_pcap(args.pcap)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        except ImportError as e:
            print(f"[ERROR] Missing dependency: {e}")
            print("  Install with: pip install scapy")
            sys.exit(1)

        print("\n--- Extraction Results ---")
        print(f"  srs_sessionid  : {result['srs_sessionid'] or '(not found)'}")
        print(f"  room_id        : {result['room_id']}")
        print(f"  game_id        : {result['game_id']}")
        print(f"  identify       : {result['identify'] or '(not found)'}")
        print(f"  handshake_blob : {result['handshake_blob'][:16]}..." if result['handshake_blob'] else "  handshake_blob : (not found)")
        print(f"  auth_token_12b : {result['auth_token_12b'] or '(not found)'}")

        if not result["srs_sessionid"]:
            print("\n[WARN] srs_sessionid not found in pcap.")
            print("  Make sure the pcap contains a complete SRS handshake (HandshakeRsp + PlayerConnect).")

    elif args.sessionid or os.path.isfile(args.creds):
        # Mode 2: Connect as player (sessionid from --sessionid or --creds JSON)
        if args.sessionid:
            sessionid = args.sessionid.strip()
            userid = args.userid
        else:
            try:
                creds = _load_creds(args.creds)
            except (FileNotFoundError, ValueError) as e:
                print(f"[ERROR] {e}")
                sys.exit(1)
            sessionid = creds["srs_sessionid"]
            userid = creds.get("userid", args.userid) or args.userid
            print(f"[cloud_player] Loaded credentials from: {args.creds}")

        if len(sessionid) != 32:
            print(f"[ERROR] srs_sessionid must be 32 hex chars (16 bytes), got {len(sessionid)}")
            sys.exit(1)

        relay_url = args.relay.strip()
        api_token = args.api_token

        print(f"[cloud_player] Connecting as player, sessionid={sessionid[:8]}...")
        print(f"  host={args.host}:{args.port}  userid={userid}")
        if relay_url:
            print(f"  relay={relay_url}  (hand tiles will appear at {relay_url})")

        def on_state_update(state: dict):
            hand = state.get("players", {}).get(state.get("local_player", 1), {}).get("hand", [])
            print(f"[BattleState] phase={state.get('phase')} hand={hand}")
            if relay_url:
                push_to_relay(relay_url, api_token, state)

        def on_connected():
            print("[cloud_player] Handshake complete, receiving game frames...")
            if relay_url:
                print(f"[cloud_player] Open browser: {relay_url}/?token={api_token}")

        def on_disconnected():
            print("[cloud_player] Disconnected, reconnecting...")

        client = SRSPlayerClient(
            srs_sessionid=sessionid,
            host=args.host,
            port=args.port,
            userid=userid,
            on_state_update=on_state_update,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )

        print("[cloud_player] Press Ctrl+C to stop.")
        try:
            client.start(block=True)
        except KeyboardInterrupt:
            print("\n[cloud_player] Stopping...")
            client.stop()

    else:
        parser.print_help()
        print("\nExamples:")
        print("  python remote/cloud_player.py                          # auto-read data/cloud_credentials.json")
        print("  python remote/cloud_player.py --creds data/cloud_credentials.json --relay http://localhost:8003")
        print("  python remote/cloud_player.py --sessionid a269e12a1ca5442db00ec625a0d0e619")
        sys.exit(1)


if __name__ == "__main__":
    _main()
