from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
import struct
from typing import Any

_LOGGER = logging.getLogger("mahjongai.stable.protocol")


HDR_LEN = 12
GAME_SERVER_PORT = 7777
HIDDEN_TILE = 0x3C
TILE_CONTEXT_INSTANCE = "instance"
TILE_CONTEXT_STABLE = "stable"
TILE_CONTEXT_UNTRUSTED_DEAL = "untrusted_deal"
DRAW_CONCEALED_MARKER = 0x72
SOURCE_UNTRUSTED_ROUND_MARKER = "untrusted_round_marker"
SOURCE_TRUSTED_HAND = "trusted_hand"
SOURCE_TRUSTED_ACTION = "trusted_action"


MSG_TYPES = {
    0x0001: "handshake",
    0x0003: "heartbeat_req",
    0x0004: "handshake_rsp",
    0x0005: "auth_req",
    0x0006: "auth_rsp",
    0x0007: "room_info",
    0x000A: "player_info",
    0x000F: "unknown_0f",
    0x0010: "room_state",
    0x0014: "join_req",
    0x0015: "join_rsp",
    0x0016: "ready_req",
    0x0017: "player_detail",
    0x0018: "heartbeat",
    0x0019: "score_update",
    0x2BC0: "game_event",
    0x2C2E: "player_action",
    0x2C2F: "action_rsp",
    0x2F1D: "match_req",
    0x2F1E: "match_rsp",
    0x620C: "unknown_620c",
    0x620D: "unknown_620d",
}


GAME_SUB_NAMES = {
    0x0003: "deal",
    0x0004: "round_start",
    0x0016: "action_notify",
    0x0206: "stat_update",
    0x0208: "stat_update2",
    0x0216: "hand_update",
    0x0218: "baida_update",
    0x021A: "draw",
    0x021B: "discard",
    0x021F: "meld",
    0x0220: "win",
    0x022B: "round_result",
    0x4E88: "player_info",
}


@dataclass
class ProtocolMessage:
    ts: str
    direction: str
    msg_type: int
    type_name: str
    sub_type: int
    extra: str
    size: int
    pay_len: int
    game: dict[str, Any] | None = None
    raw_hex: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "ts": self.ts,
            "dir": self.direction,
            "type": self.msg_type,
            "type_name": self.type_name,
            "sub": self.sub_type,
            "extra": self.extra,
            "size": self.size,
            "pay_len": self.pay_len,
        }
        if self.game is not None:
            data["game"] = self.game
        if self.raw_hex:
            data["raw_hex"] = self.raw_hex
        return data


def build_tcpdump_command(
    adb_path: str,
    device_serial: str,
    interface: str = "wlan0",
    port: int = GAME_SERVER_PORT,
    disguise_name: str = ".sys_health",
) -> list[str]:
    disguised_path = f"/data/local/tmp/{disguise_name}"
    return [
        adb_path,
        "-s",
        device_serial,
        "exec-out",
        (
            f"su -c '"
            f"[ ! -f {disguised_path} ] && cp /system/bin/tcpdump {disguised_path} 2>/dev/null; "
            f"{disguised_path} -i {interface} -w - -U -s 0 port {int(port)} 2>/dev/null'"
        ),
    ]


def raw_key(context: str, value: int) -> str:
    return f"{context}:0x{int(value) & 0xFF:02x}"


def is_hidden_tile(value: int) -> bool:
    return int(value) == HIDDEN_TILE


def instance_tile_index(value: int) -> int | None:
    value = int(value)
    if 1 <= value <= 136:
        return (value - 1) // 4
    return None


def stable_tile_id(value: int) -> str | None:
    value = int(value)
    suit = (value >> 4) & 0x0F
    rank = value & 0x0F
    if suit == 1 and 1 <= rank <= 9:
        return f"{rank}m"
    if suit == 2 and 1 <= rank <= 9:
        return f"{rank}s"
    if suit == 3 and 1 <= rank <= 9:
        return f"{rank}p"
    if suit == 4 and 1 <= rank <= 4:
        return f"{rank}z"
    if suit == 5 and 1 <= rank <= 3:
        return f"{rank + 4}z"
    return None


class PcapParser:
    """Incremental pcap parser for tcpdump stdout."""

    def __init__(self):
        self.buf = b""
        self.initialized = False
        self.endian = "<"
        self.network = 1

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self.buf += data
        packets: list[dict[str, Any]] = []
        if not self.initialized:
            if len(self.buf) < 24:
                return packets
            magic_bytes = self.buf[:4]
            if magic_bytes in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
                self.endian = "<"
            elif magic_bytes in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
                self.endian = ">"
            else:
                raise ValueError(f"unknown pcap magic: {magic_bytes.hex()}")
            _magic, _major, _minor, _tz, _sig, _snap, self.network = struct.unpack(
                self.endian + "IHHIIII", self.buf[:24]
            )
            self.buf = self.buf[24:]
            self.initialized = True

        while len(self.buf) >= 16:
            ts_sec, ts_usec, caplen, _origlen = struct.unpack(self.endian + "IIII", self.buf[:16])
            if caplen <= 0 or caplen > 16 * 1024 * 1024:
                raise ValueError(f"invalid pcap caplen: {caplen}")
            if len(self.buf) < 16 + caplen:
                break
            raw = self.buf[16 : 16 + caplen]
            self.buf = self.buf[16 + caplen :]
            pkt = self._parse_packet(raw)
            if pkt is not None:
                pkt["ts"] = ts_sec + ts_usec / 1_000_000
                packets.append(pkt)
        return packets

    def _parse_packet(self, data: bytes) -> dict[str, Any] | None:
        if self.network == 1:
            return self._parse_ethernet_ip_tcp(data)
        if self.network in (101, 228):
            return self._parse_ip_tcp(data)
        return self._parse_ethernet_ip_tcp(data) or self._parse_ip_tcp(data)

    def _parse_ethernet_ip_tcp(self, data: bytes) -> dict[str, Any] | None:
        if len(data) < 14:
            return None
        eth_type = struct.unpack(">H", data[12:14])[0]
        if eth_type != 0x0800:
            return None
        return self._parse_ip_tcp(data[14:])

    def _parse_ip_tcp(self, ip: bytes) -> dict[str, Any] | None:
        return PcapParser._parse_ip_tcp_static(ip)

    @staticmethod
    def _parse_ip_tcp_static(ip: bytes) -> dict[str, Any] | None:
        if len(ip) < 20 or (ip[0] >> 4) != 4 or ip[9] != 6:
            return None
        ihl = (ip[0] & 0x0F) * 4
        if ihl < 20 or len(ip) < ihl + 20:
            return None
        src_ip = ".".join(str(b) for b in ip[12:16])
        dst_ip = ".".join(str(b) for b in ip[16:20])
        tcp = ip[ihl:]
        src_port = struct.unpack(">H", tcp[0:2])[0]
        dst_port = struct.unpack(">H", tcp[2:4])[0]
        seq = struct.unpack(">I", tcp[4:8])[0]
        tcp_hlen = ((tcp[12] >> 4) & 0x0F) * 4
        if tcp_hlen < 20 or len(tcp) < tcp_hlen:
            return None
        payload = tcp[tcp_hlen:]
        if not payload:
            return None
        return {
            "src": f"{src_ip}:{src_port}",
            "dst": f"{dst_ip}:{dst_port}",
            "src_port": src_port,
            "dst_port": dst_port,
            "seq": seq,
            "payload": payload,
        }


class MJProtocol:
    """Decode MahjongAI game protocol frames from TCP packets."""

    def __init__(self, server_port: int = GAME_SERVER_PORT, auto_detect_frames: bool = False):
        self.server_port = int(server_port)
        self.auto_detect_frames = bool(auto_detect_frames)
        self.stream_bufs: dict[tuple[str, str], bytes] = {}
        self.stream_next_seq: dict[tuple[str, str], int] = {}

    def process_packet(self, pkt: dict[str, Any]) -> list[ProtocolMessage]:
        src_port = int(pkt["src_port"])
        dst_port = int(pkt["dst_port"])
        payload = bytes(pkt["payload"])
        port_matches = src_port == self.server_port or dst_port == self.server_port
        if not port_matches and not (self.auto_detect_frames and self._looks_like_frame(payload)):
            return []

        direction = "S->C" if self.server_port <= 0 or src_port == self.server_port else "C->S"
        key = (str(pkt["src"]), str(pkt["dst"]))
        if "seq" in pkt:
            seq = int(pkt["seq"]) & 0xFFFFFFFF
            prev_next = self.stream_next_seq.get(key)
            if prev_next is not None:
                end_seq = (seq + len(payload)) & 0xFFFFFFFF
                if self._seq_le(end_seq, prev_next):
                    return []
                if self._seq_lt(seq, prev_next):
                    offset = (prev_next - seq) & 0xFFFFFFFF
                    payload = payload[offset:]
                    seq = prev_next
            self.stream_next_seq[key] = (seq + len(payload)) & 0xFFFFFFFF
        buf = self.stream_bufs.get(key, b"") + payload

        messages: list[ProtocolMessage] = []
        while len(buf) >= HDR_LEN:
            if not self._looks_like_frame(buf):
                buf = buf[1:]
                continue
            pay_len = struct.unpack("<H", buf[2:4])[0]
            total = HDR_LEN + pay_len
            if len(buf) < total:
                break
            frame = buf[:total]
            buf = buf[total:]
            msg = self._decode_frame(frame, direction, float(pkt.get("ts") or 0))
            if msg is not None:
                messages.append(msg)

        self.stream_bufs[key] = buf
        return messages

    @staticmethod
    def _seq_lt(a: int, b: int) -> bool:
        a &= 0xFFFFFFFF
        b &= 0xFFFFFFFF
        return a != b and ((a - b) & 0x80000000) != 0

    @staticmethod
    def _seq_le(a: int, b: int) -> bool:
        a &= 0xFFFFFFFF
        b &= 0xFFFFFFFF
        return a == b or MJProtocol._seq_lt(a, b)

    @staticmethod
    def _looks_like_frame(buf: bytes) -> bool:
        if len(buf) < HDR_LEN:
            return False
        if buf[1] not in (0x40, 0x80):
            return False
        pay_len = struct.unpack("<H", buf[2:4])[0]
        return pay_len <= 65535

    def _decode_frame(self, frame: bytes, direction: str, ts: float) -> ProtocolMessage | None:
        if len(frame) < HDR_LEN:
            return None
        pay_len = struct.unpack("<H", frame[2:4])[0]
        msg_type = struct.unpack("<H", frame[4:6])[0]
        sub_type = struct.unpack("<H", frame[6:8])[0]
        payload = frame[HDR_LEN:]
        type_name = MSG_TYPES.get(msg_type, f"type_{msg_type:#06x}")

        if ts > 0:
            ts_text = datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
        else:
            ts_text = datetime.now().isoformat(timespec="milliseconds")

        game = None
        if msg_type == 0x2BC0 and len(payload) >= 4:
            game = self._decode_game_event(payload)

        return ProtocolMessage(
            ts=ts_text,
            direction=direction,
            msg_type=msg_type,
            type_name=type_name,
            sub_type=sub_type,
            extra=frame[8:12].hex(),
            size=len(frame),
            pay_len=pay_len,
            game=game,
            raw_hex=frame[: min(len(frame), 96)].hex(),
        )

    def _decode_game_event(self, payload: bytes) -> dict[str, Any]:
        sub_cmd = struct.unpack("<H", payload[0:2])[0]
        data_len = struct.unpack("<H", payload[2:4])[0]
        body = payload[4 : 4 + data_len] if 4 + data_len <= len(payload) else payload[4:]
        result: dict[str, Any] = {
            "sub_cmd": sub_cmd,
            "sub_name": GAME_SUB_NAMES.get(sub_cmd, f"sub_{sub_cmd:#06x}"),
            "data_len": data_len,
            "body_hex": body[:64].hex(),
        }

        if sub_cmd == 0x0003:
            result.update(
                {
                    "event": "deal",
                    "source": SOURCE_UNTRUSTED_ROUND_MARKER,
                    "trusted": False,
                }
            )
            if len(body) >= 13:
                result["untrusted_hand_raw_candidate"] = list(body[:13])
                result["untrusted_hand_context"] = TILE_CONTEXT_UNTRUSTED_DEAL
            if len(body) >= 18 and body[17] not in (0, HIDDEN_TILE):
                result["untrusted_baida_raw_candidate"] = int(body[17])
                result["untrusted_baida_context"] = TILE_CONTEXT_UNTRUSTED_DEAL
        elif sub_cmd == 0x0016:
            optional = self._extract_optional_action(body)
            if optional:
                result.update(optional)
        elif sub_cmd == 0x0216 and len(body) >= 3:
            player = int(body[0])
            count = int(body[2])
            if 0 < count <= 20 and len(body) >= 3 + count:
                hand_raw = list(body[3 : 3 + count])
                tail = list(body[3 + count :])
                if self._looks_like_meld_summary(count, tail):
                    result.update(
                        {
                            "event": "meld_summary",
                            "player": player,
                            "hand_count_raw": count,
                            "hand_tail_raw": tail,
                            "source": SOURCE_TRUSTED_ACTION,
                            "trusted": False,
                            "hand_incomplete_reason": "meld_summary_packet",
                        }
                    )
                    return result
                extra_raw = self._extract_hand_tail_tile(count, tail)
                if extra_raw is not None:
                    hand_raw.append(extra_raw)
                result.update(
                    {
                        "event": "hand_update",
                        "player": player,
                        "hand_raw": hand_raw,
                        "hand_context": TILE_CONTEXT_STABLE,
                        "hand_count_raw": count,
                        "source": SOURCE_TRUSTED_HAND,
                        "trusted": True,
                    }
                )
                if extra_raw is not None:
                    result["hand_extra_raw"] = extra_raw
                if tail:
                    result["hand_tail_raw"] = tail
                    marked = self._extract_marked_tail_tiles(tail)
                    if marked:
                        result["marked_tiles_raw"] = marked
        elif sub_cmd == 0x021B and len(body) >= 2:
            result.update(
                {
                    "event": "discard",
                    "player": int(body[0]),
                    "tile_raw": int(body[1]),
                    "tile_offset": 1,
                    "tile_context": TILE_CONTEXT_STABLE,
                    "source": SOURCE_TRUSTED_ACTION,
                    "trusted": True,
                }
            )
        elif sub_cmd == 0x021A and len(body) >= 2:
            result.update(
                {
                    "event": "draw",
                    "player": int(body[0]),
                    "source": SOURCE_TRUSTED_ACTION,
                    "trusted": True,
                }
            )
            tile_raw = self._extract_draw_tile(body)
            if tile_raw is not None:
                result["tile_raw"] = tile_raw[1]
                result["tile_offset"] = tile_raw[0]
                result["tile_context"] = TILE_CONTEXT_STABLE
        elif sub_cmd == 0x0218 and len(body) >= 2 and int(body[0]) == 0x01:
            baida_raw = int(body[1])
            if baida_raw not in (0, HIDDEN_TILE):
                result.update(
                    {
                        "event": "baida_update",
                        "baida_raw": baida_raw,
                        "baida_context": TILE_CONTEXT_STABLE,
                        "baida_trusted": True,
                        "source": SOURCE_TRUSTED_ACTION,
                        "trusted": True,
                    }
                )
        elif sub_cmd == 0x021F and len(body) >= 2:
            player_id = int(body[0]) if body[0] <= 3 else None
            meld_info = self._extract_meld_info(body)
            meld_type = str(meld_info.get("meld_type") or "")
            if meld_type == "chi":
                event_name = "chi"
            elif meld_type == "pon":
                event_name = "pon"
            else:
                event_name = "kong"
            result.update(
                {
                    "event": event_name,
                    "player": player_id,
                    "source": SOURCE_TRUSTED_ACTION,
                    "trusted": True,
                }
            )
            if event_name == "kong":
                tile_raw = self._extract_kong_tile(body)
                if tile_raw is not None:
                    result.update(
                        {
                            "tile_raw": tile_raw,
                            "tile_context": TILE_CONTEXT_STABLE,
                        }
                    )
            else:
                # chi/pon: claimed tile is at body[8]
                if len(body) >= 9:
                    claimed = int(body[8])
                    if claimed not in (0, HIDDEN_TILE):
                        result["tile_raw"] = claimed
                        result["tile_context"] = TILE_CONTEXT_STABLE
            if meld_info:
                result.update(meld_info)
            elif event_name != "kong":
                # Should not happen given event_name is chi/pon
                pass
            else:
                # Unrecognized meld body (e.g. body[4]=0x53 wildcard / 财神替代）
                _LOGGER.warning(
                    "meld 0x021F not recognized, body_hex=%s",
                    body[: min(len(body), 20)].hex(),
                )
        elif sub_cmd == 0x0220:
            result["event"] = "win"
            result["source"] = SOURCE_TRUSTED_ACTION
            result["trusted"] = True
            if len(body) >= 1 and body[0] <= 3:
                result["player"] = int(body[0])
            if len(body) >= 14 and body[13] not in (0, HIDDEN_TILE):
                result["tile_raw"] = int(body[13])
                result["tile_offset"] = 13
                result["tile_context"] = TILE_CONTEXT_STABLE

        return result

    @staticmethod
    def _extract_draw_tile(body: bytes) -> tuple[int, int] | None:
        candidates: list[tuple[int, int]] = []
        if len(body) >= 2:
            candidates.append((1, int(body[1])))
        if len(body) >= 3:
            candidates.append((2, int(body[2])))

        if len(body) >= 2 and int(body[1]) == DRAW_CONCEALED_MARKER:
            return None

        for offset, raw in candidates:
            if raw in (0, HIDDEN_TILE):
                continue
            if stable_tile_id(raw) is not None:
                return offset, raw

        for offset, raw in candidates:
            if raw not in (0, HIDDEN_TILE, DRAW_CONCEALED_MARKER):
                return offset, raw
        return None

    @staticmethod
    def _extract_hand_tail_tile(count: int, tail: list[int]) -> int | None:
        if count != 13 or len(tail) < 2:
            return None
        marker, raw = int(tail[0]), int(tail[1])
        if marker != 0x01:
            return None
        if raw in (0, HIDDEN_TILE):
            return None
        if stable_tile_id(raw) is None:
            return None
        return raw

    @staticmethod
    def _looks_like_meld_summary(count: int, tail: list[int]) -> bool:
        if count >= 13 or len(tail) < 12:
            return False
        group_markers = 0
        for idx in range(0, max(0, len(tail) - 5)):
            if int(tail[idx]) in (0x03, 0x04) and int(tail[idx + 4]) in (0x00, 0x01, 0x02, 0x03):
                tiles = [int(v) for v in tail[idx + 1 : idx + 4]]
                if all(v == 0 or stable_tile_id(v) is not None for v in tiles):
                    group_markers += 1
        return group_markers >= 2

    @staticmethod
    def _extract_marked_tail_tiles(tail: list[int]) -> list[int]:
        marked: list[int] = []
        for idx in range(0, max(0, len(tail) - 3)):
            if int(tail[idx]) != 0x09:
                continue
            raw_count = int(tail[idx + 2])
            if not 1 <= raw_count <= 4:
                continue
            values = [int(v) for v in tail[idx + 3 : idx + 3 + raw_count]]
            if len(values) != raw_count:
                continue
            marked.extend(v for v in values if stable_tile_id(v) is not None)
        return marked

    @staticmethod
    def _extract_optional_action(body: bytes) -> dict[str, Any]:
        if len(body) < 3 or b"\xff\xff" in body[:4]:
            return {}
        player = int(body[0]) if body[0] <= 3 else None
        bit_actions = [("chi", 0x01), ("pon", 0x02), ("kong", 0x04), ("hu", 0x08), ("pass", 0x10)]
        opcode_actions = {0x01: "chi", 0x02: "pon", 0x03: "kong", 0x04: "hu", 0x05: "pass"}
        label_map = {"chi": "吃", "pon": "碰", "kong": "杠", "hu": "胡", "pass": "过"}

        options: list[str] = []
        mask = int(body[1]) if len(body) > 1 else 0
        for action, bit in bit_actions:
            if mask & bit:
                options.append(action)
        if not options:
            for raw in body[1: min(len(body), 8)]:
                action = opcode_actions.get(int(raw))
                if action and action not in options:
                    options.append(action)
        if options and "pass" not in options:
            options.append("pass")
        if not options:
            return {}

        result: dict[str, Any] = {
            "event": "optional_action",
            "options": options,
            "option_labels": [label_map.get(action, action) for action in options],
            "source": SOURCE_TRUSTED_ACTION,
            "trusted": True,
        }
        if player is not None:
            result["player"] = player
        tile_candidates = [int(raw) for raw in body[2:8] if stable_tile_id(int(raw)) is not None]
        if tile_candidates:
            result["tile_raw"] = tile_candidates[0]
            result["tile_context"] = TILE_CONTEXT_STABLE
        return result

    @staticmethod
    def _extract_kong_tile(body: bytes) -> int | None:
        if len(body) >= 8:
            four_tiles = [int(body[i]) for i in (4, 5, 6, 7)]
            stable_tiles = [stable_tile_id(raw) for raw in four_tiles if raw not in (0, HIDDEN_TILE)]
            if stable_tiles and len(stable_tiles) == 4 and len(set(stable_tiles)) == 1:
                return four_tiles[0]
        if len(body) >= 9:
            meld_bytes = [int(body[i]) for i in (4, 5, 6, 8)]
            claimed = meld_bytes[-1]
            if stable_tile_id(claimed) is not None:
                return claimed
            stable_tiles = [stable_tile_id(raw) for raw in meld_bytes if raw not in (0, HIDDEN_TILE)]
            if stable_tiles and len(set(stable_tiles)) == 1:
                return meld_bytes[0]
            meld_indexes = [instance_tile_index(raw) for raw in meld_bytes if raw not in (0, HIDDEN_TILE)]
            if meld_indexes and len(set(meld_indexes)) == 1:
                return meld_bytes[0]

        counts: dict[int, tuple[int, int]] = {}
        for raw in body[1:]:
            if raw in (0, HIDDEN_TILE):
                continue
            idx = instance_tile_index(raw)
            if idx is None:
                continue
            count, first_raw = counts.get(idx, (0, int(raw)))
            counts[idx] = (count + 1, first_raw)
        for _idx, (count, first_raw) in sorted(counts.items(), key=lambda item: item[1][0], reverse=True):
            if count >= 4:
                return first_raw
        return None

    @staticmethod
    def _extract_meld_info(body: bytes) -> dict[str, Any]:
        if len(body) < 9:
            return {}
        meld_count = int(body[3])
        exposed = [int(body[i]) for i in (4, 5, 6)]
        claimed = int(body[8])
        if any(stable_tile_id(raw) is None for raw in exposed):
            return {}

        if meld_count >= 4:
            for indexes in ((4, 5, 6, 7), (4, 5, 6, 8)):
                tiles_raw = [int(body[i]) for i in indexes]
                if len({stable_tile_id(raw) for raw in tiles_raw}) == 1:
                    return {"meld_type": "kan_open", "meld_tiles_raw": tiles_raw}
            return {}
        if stable_tile_id(claimed) is None:
            return {}
        if len(set(exposed)) == 1:
            return {"meld_type": "pon", "meld_tiles_raw": exposed}
        if MJProtocol._is_stable_sequence(exposed):
            return {"meld_type": "chi", "meld_tiles_raw": exposed}
        if MJProtocol._is_stable_sequence_with_substitute(exposed, claimed):
            return {"meld_type": "chi", "meld_tiles_raw": exposed, "meld_note": "contains_substitute"}
        return {}

    @staticmethod
    def _is_stable_sequence(raw_values: list[int]) -> bool:
        tiles = [stable_tile_id(raw) for raw in raw_values]
        if any(tile is None for tile in tiles):
            return False
        suits = [str(tile)[-1] for tile in tiles]
        if len(set(suits)) != 1 or suits[0] == "z":
            return False
        ranks = sorted(int(str(tile)[:-1]) for tile in tiles)
        return ranks[1] == ranks[0] + 1 and ranks[2] == ranks[1] + 1

    @staticmethod
    def _is_stable_sequence_with_substitute(raw_values: list[int], claimed: int) -> bool:
        natural_tiles = [stable_tile_id(raw) for raw in raw_values if int(raw) != int(claimed)]
        natural_tiles = [tile for tile in natural_tiles if tile is not None]
        if len(natural_tiles) < 2:
            return False
        suits = [str(tile)[-1] for tile in natural_tiles]
        if len(set(suits)) != 1 or suits[0] == "z":
            return False
        ranks = sorted(int(str(tile)[:-1]) for tile in natural_tiles)
        return ranks[-1] - ranks[0] <= 2


class NpcapCapture:
    """主机侧抓包，使用 scapy + npcap。

    在 Windows 主机网络栈上捕获游戏流量，模拟器内无任何进程。
    数据以原始 IP 字节交付，兼容 ``PcapParser``（network type 101 / raw-IP）。
    """

    def __init__(
        self,
        server_port: int = GAME_SERVER_PORT,
        iface: str | None = None,
    ):
        self.server_port = int(server_port)
        self.iface = iface or None
        self._running = False
        self._sock = None

    def sniff(self, callback, port_filter: int | None = None):
        """阻塞式嗅探，每个包调用 *callback(raw_ip_bytes)*。"""
        import scapy.config

        try:
            scapy.config.conf.use_npcap = True
        except Exception:
            pass

        from scapy.all import sniff as scapy_sniff

        self._running = True
        port = int(self.server_port if port_filter is None else port_filter)

        def dispatch_packet(pkt):
            self._dispatch(pkt, callback, port)

        use_l3 = False
        # 先尝试 L2（支持 BPF 硬件过滤，性能最优）
        try:
            kw = dict(
                filter=f"tcp port {port}" if port > 0 else "tcp",
                prn=dispatch_packet,
                stop_filter=lambda _: not self._running,
                store=False,
            )
            if self.iface:
                kw["iface"] = self.iface
            scapy_sniff(**kw)
            # L2 正常返回但 _running 仍为 True → L2 静默失败，需回退
            if self._running:
                use_l3 = True
        except (OSError, RuntimeError):
            use_l3 = True

        if use_l3 and self._running:
            # L3 回退：带 timeout 循环，保证 stop() 2 秒内响应
            sock = scapy.config.conf.L3socket(
                iface=self.iface or scapy.config.conf.iface
            )
            self._sock = sock
            try:
                while self._running:
                    scapy_sniff(
                        opened_socket=sock,
                        prn=dispatch_packet,
                        stop_filter=lambda _: not self._running,
                        timeout=2,
                        store=False,
                    )
            finally:
                self._sock = None
                try:
                    sock.close()
                except Exception:
                    pass

    def stop(self):
        self._running = False
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _dispatch(pkt, callback, port_filter: int = 0):
        # 从 scapy 包对象提取 IP 层
        try:
            from scapy.layers.inet import IP, TCP
            if IP in pkt:
                if port_filter and TCP in pkt:
                    tcp = pkt[TCP]
                    if tcp.sport != port_filter and tcp.dport != port_filter:
                        return
                callback(bytes(pkt[IP]))
                return
        except Exception:
            pass
        # 回退：手动解析原始字节
        raw = bytes(pkt)
        if len(raw) > 14 and (raw[14] >> 4) == 4:
            callback(raw[14:])
        elif len(raw) > 0 and (raw[0] >> 4) == 4:
            callback(raw)
