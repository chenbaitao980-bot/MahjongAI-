"""SRS TCP client - connects to game server, completes handshake, sends/receives.

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

try:
    from .frame import (
        pack_frame, unpack_frame, read_frame_from_stream,
        MSG_ENCRYPT_VER, MSG_REQ_KEY, MSG_HANDSHAKE_RSP,
        MSG_PLAYER_CONNECT, MSG_PLAYER_DATA, MSG_REQ_PLUS_DATA,
        MSG_RESP_PLUS_DATA, MSG_SPECTATOR_RESP, MSG_NAMES,
    )
    from .crypto import SRSCrypto
    from .handshake import (
        build_req_key, build_req_plus_data, parse_player_data, parse_resp_plus_data,
    )
    from .player_connect import build_player_connect_raw, ENCRYPT_VER_PLAINTEXT
    from .spectator import SpectatorClient
except ImportError:
    from frame import (
        pack_frame, unpack_frame, read_frame_from_stream,
        MSG_ENCRYPT_VER, MSG_REQ_KEY, MSG_HANDSHAKE_RSP,
        MSG_PLAYER_CONNECT, MSG_PLAYER_DATA, MSG_REQ_PLUS_DATA,
        MSG_RESP_PLUS_DATA, MSG_SPECTATOR_RESP, MSG_NAMES,
    )
    from crypto import SRSCrypto
    from handshake import (
        build_req_key, build_req_plus_data, parse_player_data, parse_resp_plus_data,
    )
    from player_connect import build_player_connect_raw, ENCRYPT_VER_PLAINTEXT
    from spectator import SpectatorClient

logger = logging.getLogger(__name__)


class SRSClient:
    """SRS protocol client with handshake and spectator support."""

    def __init__(self, host: str, port: int, auth_token: str, handshake_blob: str,
                 srs_sessionid: str = "", userid: str = "newpt1084306678"):
        self.host = host
        self.port = port
        self.auth_token = bytes.fromhex(auth_token) if auth_token else b""
        self.handshake_blob = bytes.fromhex(handshake_blob) if handshake_blob else b""
        self.srs_sessionid = bytes.fromhex(srs_sessionid) if srs_sessionid else b""
        self.userid = userid.encode("utf-8") if isinstance(userid, str) else userid
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

        # Step 1: EncryptVer - encrypt ">x01\x00\x00\x00" with default key
        logger.debug("> EncryptVer (msgid=1, crypto-encrypted)")
        ev_ct = self._crypto.encrypt_payload(ENCRYPT_VER_PLAINTEXT)
        self._send_raw(pack_frame(MSG_ENCRYPT_VER, ev_ct))

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
            # HandshakeRsp: S2C encrypted with default key, contains session key.
            # Format: [key_len(1B)] [session_key(key_len B)]  - key_len in {16,24,32}
            hs_dec = self._crypto.decrypt_payload(payload)
            key_len = hs_dec[0]
            session_key = hs_dec[1:1+key_len]
            logger.debug(f"-> Session key ({len(session_key)}B, AES-{len(session_key)*8}): {session_key.hex()}")
            self._crypto.set_key(session_key)  # reset CFB to IV

            # Build and encrypt PlayerConnect
            logger.debug("-> PlayerConnect (msgid=5, encrypted with session key)")
            pc_raw = build_player_connect_raw(
                identify=b"020000000000",  # RC4-encrypted hw fingerprint
                userid=self.userid,
                pwd=self.srs_sessionid if self.srs_sessionid else b"\x00" * 16,
            )
            pc_ct = self._crypto.encrypt_payload(pc_raw)
            logger.debug(f"  PC raw={len(pc_raw)}B ct={len(pc_ct)}B")
            self._send_raw(pack_frame(MSG_PLAYER_CONNECT, pc_ct))

        elif msg_type == MSG_PLAYER_DATA:
            # Auth result - decrypt with session key
            pd_dec = self._crypto.decrypt_payload(payload)
            flag = pd_dec[0] if pd_dec else -1
            logger.info(f"PlayerData: flag={flag}")
            result = parse_player_data(pd_dec)
            if flag == 0:
                self.sessionid = result.get("sessionid", b"")
                logger.info(f"Auth success! sessionid={self.sessionid.hex()[:16]}...")
                logger.debug("-> ReqPlayerPlusData (msgid=23)")
                self._send_raw(build_req_plus_data())
            else:
                logger.warning(f"Auth warning: flag={flag} (non-zero, may still work for spectator)")

        elif msg_type == MSG_RESP_PLUS_DATA:
            # Received m_key - first decrypt with session key
            rp_dec = self._crypto.decrypt_payload(payload)
            result = parse_resp_plus_data(rp_dec)
            self.m_key = result.get("key", b"")
            if self.m_key:
                logger.info(f"Got m_key: {len(self.m_key)} bytes")
                self._crypto.set_key(self.m_key)
            self.is_authenticated = True
            logger.info("=== Handshake complete! ===")
            if self._on_handshake_done:
                self._on_handshake_done()

        # Spectator protocol handling
        elif self._spectator and msg_type == MSG_SPECTATOR_RESP:
            self._spectator.handle_response(payload)

        # Forward to user callback
        if self._on_frame:
            self._on_frame(msg_type, payload)
