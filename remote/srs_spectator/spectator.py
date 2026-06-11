"""Spectator protocol — ReqRealtimeGameRecord.

Requests real-time game record data from the server via the SRS connection.
The server responds with zlib-compressed fragments. After all fragments arrive,
merge and decompress to get the full game record.
"""
import struct
import zlib
import logging

from .frame import pack_frame

logger = logging.getLogger(__name__)

# Protocol message IDs (from IMProtocol.lua / MatchLinkProtocol.lua)
# These are the XY_ID values for spectator messages
# We use IMProtocol by default; the server may use MatchLinkProtocol (watch1006 mode)
SPECTATOR_REQ_MSGID = 0x2F1E   # ReqRealtimeGameRecord (IMProtocol - needs actual ID)
SPECTATOR_RESP_MSGID = 0x2F1D  # RespRealtimeGameRecord (needs actual ID)


class SpectatorClient:
    """Handles spectator protocol over an established SRS connection."""

    def __init__(self, send_callback):
        self._send = send_callback  # callback(bytes) → sends raw frame on SRS connection
        self._fragments = {}        # askid → {total, parts: {index: bytes}}
        self._on_record = None      # callback(record_bytes) when complete record arrives

    def on_record(self, callback):
        """Set callback for when a complete game record is received."""
        self._on_record = callback

    def request_record(self, roomid: int, gameid: int, offset: int = 0,
                       askid: int = None, before_round: int = 0) -> int:
        """Request real-time game record.

        Args:
            roomid: Room ID to watch
            gameid: Game ID
            offset: Starting offset (0 for beginning)
            askid: Request ID (auto-generated if None)
            before_round: 1 for replay before current round

        Returns:
            askid used for matching response fragments
        """
        if askid is None:
            import time
            askid = int(time.time()) & 0x7FFFFFFF

        # Build request payload per IMProtocol.ReqRealtimeGameRecord
        # Fields: askid(int32), room_id(int32), offset(int32), before_round(int32)
        payload = struct.pack("<iiii", askid, roomid, offset, before_round)

        # The actual msgid for spectator request depends on the connection type.
        # IMProtocol uses one set of IDs, MatchLinkProtocol uses another.
        # We try IMProtocol first; the server will respond with the matching ID.
        frame = pack_frame(SPECTATOR_REQ_MSGID, payload)

        self._fragments[askid] = {"total": 0, "parts": {}}
        self._send(frame)
        logger.info(f"Spectator request: roomid={roomid} gameid={gameid} askid={askid}")
        return askid

    def handle_response(self, payload: bytes) -> bool:
        """Process a spectator response fragment.

        Returns True if the record is complete.
        """
        if len(payload) < 32:
            logger.warning(f"Spectator response too short: {len(payload)} bytes")
            return False

        # Parse response per IMProtocol.RespRealtimeGameRecord
        # Fields: askid, flag, room_id, max_offset, current, total, zip, payload_size, payload
        askid, flag, room_id, max_offset = struct.unpack_from("<iiii", payload, 0)
        current, total, zip_flag, payload_size = struct.unpack_from("<iiii", payload, 16)

        if askid not in self._fragments:
            logger.debug(f"Ignoring spectator response for unknown askid={askid}")
            return False

        frag = self._fragments[askid]
        frag["total"] = total
        frag["room_id"] = room_id
        frag["max_offset"] = max_offset
        frag["zip"] = zip_flag

        if payload_size > 0 and len(payload) >= 32 + payload_size:
            data = payload[32:32 + payload_size]
            frag["parts"][current] = data
            logger.debug(f"Spectator fragment: {current}/{total} ({payload_size}B)")

        # Check if all fragments received
        if total > 0 and len(frag["parts"]) >= total:
            self._merge_and_deliver(askid)
            return True

        return False

    def _merge_and_deliver(self, askid: int) -> None:
        """Merge all fragments and deliver the complete record."""
        frag = self._fragments.pop(askid)
        total = frag["total"]

        # Merge fragments in order
        merged = bytearray()
        for i in range(1, total + 1):
            if i in frag["parts"]:
                merged += frag["parts"][i]
            else:
                logger.error(f"Missing fragment {i}/{total} for askid={askid}")
                return

        data = bytes(merged)

        # Decompress if zlib-compressed
        if frag.get("zip") == 1:
            try:
                data = zlib.decompress(data)
                logger.info(f"Decompressed record: {len(data)} bytes")
            except zlib.error as e:
                logger.error(f"Zlib decompress failed: {e}")
                return

        logger.info(f"Complete record: {len(data)} bytes, askid={askid}")
        if self._on_record:
            self._on_record(data)
