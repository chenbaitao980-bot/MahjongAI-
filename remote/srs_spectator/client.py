"""SRS TCP client — connects to game server, completes handshake, sends/receives.

Usage:
    client = SRSClient("47.96.0.227", 7777, auth_token_12b, handshake_blob)
    client.connect()
    client.request_spectator(roomid, gameid)
    # frames arrive via on_frame callback
"""
import socket
import struct
import logging
import time
import threading
from typing import Callable

from .frame import (
    pack_frame, unpack_frame, read_frame_from_stream,
    MSG_ENCRYPT_VER, MSG_REQ_KEY, MSG_HANDSHAKE_RSP,
    MSG_PLAYER_CONNECT, MSG_PLAYER_DATA, MSG_REQ_PLUS_DATA,
    MSG_RESP_PLUS_DATA, MSG_NAMES,
)
from .crypto import SRSCrypto
from .handshake import (
    build_encrypt_ver, build_req_key, build_player_connect,
    build_req_plus_data, parse_player_data, parse_resp_plus_data,
)
from .spectator import SpectatorClient

logger = logging.getLogger(__name__)


class SRSClient:
    """SRS protocol client with handshake and spectator support."""

    def __init__(self, host: str, port: int, auth_token: str, handshake_blob: str):
        self.host = host
        self.port = port
        self.auth_token = bytes.fromhex(auth_token) if auth_token else b""
        self.handshake_blob = bytes.fromhex(handshake_blob) if handshake_blob else b""
        self._sock: socket.socket | None = None
        self._crypto = SRSCrypto()
        self._recv_buf = bytearray()
        self._running = False
        self._recv_thread: threading.Thread | None = None
        self._on_frame: Callable | None = None
        self._on_handshake_done: Callable | None = None
        self._spectator: SpectatorClient | None = None
        self.sessionid = b""
        self.m_key = b""
        self.is_authenticated = False

    def on_frame(self, callback: Callable):
        """Set callback for received frames: callback(msg_type, payload)."""
        self._on_frame = callback

    def on_handshake_done(self, callback: Callable):
        """Set callback for handshake completion."""
        self._on_handshake_done = callback

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect to game server and complete SRS handshake."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect((self.host, self.port))
            self._sock.settimeout(None)
            logger.info(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Connect failed: {e}")
            return False

        # Start receive thread
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # Step 1: EncryptVer
        logger.debug("→ EncryptVer (msgid=1)")
        self._send_raw(build_encrypt_ver())

        # Handshake continues in _handle_frame via state machine
        return True

    def disconnect(self):
        """Close the connection."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def request_spectator(self, roomid: int, gameid: int) -> int:
        """Request spectator data for a game room."""
        if not self._spectator:
            self._spectator = SpectatorClient(self._send_raw)
        return self._spectator.request_record(roomid, gameid)

    def on_spectator_record(self, callback):
        """Set callback for complete spectator records."""
        if not self._spectator:
            self._spectator = SpectatorClient(self._send_raw)
        self._spectator.on_record(callback)

    def _send_raw(self, data: bytes) -> None:
        """Send raw bytes on the TCP socket."""
        if self._sock:
            try:
                self._sock.sendall(data)
            except Exception as e:
                logger.error(f"Send error: {e}")

    def _recv_loop(self) -> None:
        """Background receive thread."""
        while self._running:
            try:
                if self._sock:
                    self._sock.settimeout(1.0)
                    data = self._sock.recv(65536)
                    if not data:
                        logger.info("Connection closed by server")
                        self._running = False
                        break
                    self._recv_buf += data
                    self._process_buffer()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Recv error: {e}")
                self._running = False
                break

    def _process_buffer(self) -> None:
        """Process accumulated receive buffer for complete frames."""
        while True:
            frame, self._recv_buf = read_frame_from_stream(self._recv_buf)
            if frame is None:
                break
            self._handle_frame(frame)

    def _handle_frame(self, frame: dict) -> None:
        """Handle a received frame."""
        msg_type = frame["msg_type"]
        payload = frame["payload"]
        name = MSG_NAMES.get(msg_type, f"msg_{msg_type:#06x}")
        logger.debug(f"← {name} ({len(payload)}B)")

        # SRS handshake handling
        if msg_type == MSG_ENCRYPT_VER:
            # Server acknowledged EncryptVer → send ReqKey
            logger.debug("→ ReqKey (msgid=3)")
            self._send_raw(build_req_key())

        elif msg_type == MSG_HANDSHAKE_RSP:
            # Received handshake_rsp (25B nonce) → send PlayerConnect
            logger.debug("→ PlayerConnect (msgid=5)")
            identify = "test_device_001"  # TODO: use real identify from config
            pc_frame = build_player_connect(
                userid="",
                sessionid=self.auth_token[:16],
                identify=identify,
                channelid=0,
                n_game_id=0,
                crypto=self._crypto,
            )
            self._send_raw(pc_frame)

        elif msg_type == MSG_PLAYER_DATA:
            # Auth result
            result = parse_player_data(payload)
            logger.info(f"PlayerData: flag={result.get('flag')}")
            if result.get("flag") == 0:
                self.sessionid = result.get("sessionid", b"")
                logger.info(f"Auth success! sessionid={self.sessionid.hex()[:16]}...")
                # Send ReqPlayerPlusData
                logger.debug("→ ReqPlayerPlusData (msgid=23)")
                self._send_raw(build_req_plus_data())
            else:
                logger.error(f"Auth failed: flag={result.get('flag')} msg={result.get('msg')}")

        elif msg_type == MSG_RESP_PLUS_DATA:
            # Received m_key
            result = parse_resp_plus_data(payload)
            self.m_key = result.get("key", b"")
            if self.m_key:
                logger.info(f"Got m_key: {len(self.m_key)} bytes")
                self._crypto.set_key(self.m_key)
            self.is_authenticated = True
            logger.info("=== Handshake complete! ===")
            if self._on_handshake_done:
                self._on_handshake_done()

        # Spectator protocol handling
        elif self._spectator and msg_type == 0x2F1D:
            self._spectator.handle_response(payload)

        # Forward to user callback
        if self._on_frame:
            self._on_frame(msg_type, payload)
