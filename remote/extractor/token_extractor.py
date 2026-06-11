"""
token_extractor.py — 从协议流中提取认证凭证和房间信息

监听协议消息：
  C->S:
  - msg_type == 0x0001 → 提取 handshake_blob（payload 全部，只取第一个）
  - msg_type == 0x0006 且 len(payload)==16 → 提取 auth_token_12b（payload[4:16]）

  S->C:
  - msg_type == 14 (RespJoinTable, RoomProtocol) → 提取 roomid + gameid

两个凭证都提取到后，通过 on_registered 回调通知调用方。
roomid/gameid 提取到后，通过 on_room_info 回调通知调用方。

旁观帧取证（通道B 使能）：
  旁观请求/响应的 wire 帧头里的 sub_type/extra ↔ processid 映射公式未逆出
  （见 .trellis/tasks/06-11-srs-client-finish/research/srs-spectator-protocol.md §7）。
  真机进观战模式时，把旁观相关 wire 帧（msgid 3000-3003）的完整明文头 + payload hex
  落盘到 spectator_forensic.jsonl，供人工读出 sub_type/extra 真值。
  另外开启"全量帧头取证"——把每一帧的帧头（不含 payload）追加到同一文件，
  保证一次真机观战不漏掉任何 processid 信号线索。
"""
import json
import logging
import os
import sys
import struct

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.protocol import MJProtocol, GAME_SERVER_PORT

_LOGGER = logging.getLogger("remote.extractor.token")

# 旁观协议 msgid（真值，见 research §1；IMProtocol.lua:73-76 / MatchLinkProtocol.lua:3-6）
#   3000 (0x0BB8) ReqRealtimeGameRecord
#   3001 (0x0BB9) RespRealtimeGameRecord
#   3002 (0x0BBA) ReqUnwatchRealtimeGameRecord
#   3003 (0x0BBB) RespUnwatchRealtimeGameRecord
_SPECTATOR_MSG_TYPES = frozenset((3000, 3001, 3002, 3003))

# 取证文件默认落盘到 extractor 日志目录（与 extractor.log 同目录），不硬编码绝对路径。
_DEFAULT_FORENSIC_FILENAME = "spectator_forensic.jsonl"


class SpectatorForensicLogger:
    """旁观帧取证写盘器。

    两类记录（每行一条 JSON，jsonl 格式）：
      1. kind="frame_head"  —— 全量帧头取证（默认开），仅记录
         (direction, msg_type, sub_type, extra, pay_len)，不含 payload，保持低噪音；
         用于人工逆 sub_type/extra ↔ processid 映射。
      2. kind="spectator"   —— 旁观帧 3000-3003，额外带 payload hex。

    全量帧头取证可通过构造参数 capture_all_heads=False 关闭。
    """

    def __init__(self, path=None, capture_all_heads=True):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), _DEFAULT_FORENSIC_FILENAME)
        self._path = path
        self._capture_all_heads = capture_all_heads
        self._fh = None
        try:
            # 确保目录存在（默认就在 extractor 目录下，通常已存在）
            parent = os.path.dirname(os.path.abspath(self._path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")
            _LOGGER.info("旁观帧取证已启用，落盘: %s (全量帧头=%s)",
                         self._path, self._capture_all_heads)
        except OSError as exc:
            _LOGGER.warning("无法打开旁观取证文件 %s: %s（取证禁用）", self._path, exc)
            self._fh = None

    @property
    def path(self):
        return self._path

    def _write(self, record):
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()
        except OSError as exc:
            _LOGGER.debug("旁观取证写盘失败: %s", exc)

    def feed(self, message):
        """对每一帧调用。旁观帧带 payload，其余帧仅记录帧头（若启用全量帧头取证）。

        取证是旁路功能，绝不能影响核心 token/room 提取链路：任何字段缺失/磁盘异常
        都被 try/except 吞掉，仅记一笔 debug/warning 日志。所有字段访问用 getattr 防御，
        即便上游传来不完整的消息对象也不抛异常。
        """
        if self._fh is None:
            return

        try:
            msg_type = getattr(message, "msg_type", 0) or 0
            is_spectator = msg_type in _SPECTATOR_MSG_TYPES

            if not is_spectator and not self._capture_all_heads:
                return

            sub_type = getattr(message, "sub_type", 0) or 0
            extra = getattr(message, "extra", "")
            pay_len = getattr(message, "pay_len", 0) or 0
            raw_hex = getattr(message, "raw_hex", "") or ""

            record = {
                "ts": getattr(message, "ts", None),
                "dir": getattr(message, "direction", None),
                "msg_type": msg_type,
                "msg_type_hex": "0x%04x" % msg_type,
                "sub_type": sub_type,
                "sub_type_hex": "0x%04x" % sub_type,
                "extra": extra,                  # 4 字节 hex 字符串
                "pay_len": pay_len,
            }

            if is_spectator:
                record["kind"] = "spectator"
                # raw_hex 在 stable/protocol.py 里被截断到 96 字节（前 12B 帧头 + 最多 84B payload），
                # 因此旁观大帧的 payload 可能不完整——但 sub_type/extra 逆映射只需帧头，payload 仅作旁证。
                payload = bytes.fromhex(raw_hex)[12:] if raw_hex else b""
                record["payload_hex"] = payload.hex()
                record["payload_seen"] = len(payload)
                record["payload_truncated"] = len(payload) < pay_len
                _LOGGER.info(
                    "[旁观取证] dir=%s msg_type=0x%04x sub_type=0x%04x extra=%s pay_len=%d seen=%d",
                    record["dir"], msg_type, sub_type,
                    extra, pay_len, len(payload),
                )
            else:
                record["kind"] = "frame_head"

            self._write(record)
        except Exception as exc:  # 取证绝不上抛，保护核心提取链路
            _LOGGER.warning("旁观取证 feed 异常（已忽略，不影响提取）: %s", exc)

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


class TokenExtractor:
    """
    从 ProtocolMessage 流中提取 handshake_blob 和 auth_token_12b。

    用法：
        extractor = TokenExtractor(on_registered=my_callback)
        # 每收到一个协议消息：
        extractor.feed(message)
    """

    def __init__(self, on_registered=None, on_room_info=None,
                 forensic_logger=None, forensic_path=None,
                 capture_all_heads=True):
        """
        on_registered: callable，签名 (handshake_blob: bytes, auth_token_12b: bytes) -> None
                       两个凭证都提取到后调用一次
        on_room_info: callable，签名 (room_id: int, game_id: int) -> None
                      房间信息提取到后调用
        forensic_logger: 可选，已构造好的 SpectatorForensicLogger（测试/复用用）。
                         为 None 时按 forensic_path / capture_all_heads 自建一个。
        forensic_path: 旁观取证文件路径；None → extractor 目录下 spectator_forensic.jsonl。
        capture_all_heads: 是否开启"全量帧头取证"（默认 True）。
        """
        self._handshake_blob = None   # bytes
        self._auth_token_12b = None   # bytes
        self._registered = False
        self._seen_init = False       # 是否已见过 C->S 0x000F（init 包）
        self._on_registered = on_registered
        self._on_room_info = on_room_info

        # Room info extraction
        self._room_id = None
        self._game_id = None
        self._room_reported = False

        # 旁观帧取证（通道B 使能）
        if forensic_logger is not None:
            self._forensic = forensic_logger
        else:
            self._forensic = SpectatorForensicLogger(
                path=forensic_path, capture_all_heads=capture_all_heads)

    @property
    def handshake_blob(self):
        return self._handshake_blob

    @property
    def auth_token_12b(self):
        return self._auth_token_12b

    @property
    def room_id(self):
        return self._room_id

    @property
    def game_id(self):
        return self._game_id

    @property
    def is_complete(self):
        """是否两个凭证都已提取"""
        return self._handshake_blob is not None and self._auth_token_12b is not None

    def feed(self, message):
        """
        处理一个 ProtocolMessage，尝试提取认证凭证和房间信息。

        取证落盘与帧头日志是旁路：用 try/except 包起，任何失败只记一笔 debug，
        绝不阻断下面的 token/room 核心提取。
        """
        # 旁观帧取证：全量帧头 + 旁观帧（3000-3003）payload，落盘到 spectator_forensic.jsonl
        try:
            self._forensic.feed(message)
        except Exception as exc:  # 取证旁路异常绝不影响提取
            _LOGGER.debug("旁观取证调用异常（已忽略）: %s", exc)

        # 取证日志：无条件记录关键握手/房间消息（去掉运算符优先级歧义，去掉重复的 14）
        try:
            if getattr(message, "msg_type", None) in (0x0001, 0x0006, 0x000F, 14):
                _raw_hex = getattr(message, "raw_hex", "") or ""
                _forensic_payload = bytes.fromhex(_raw_hex)[12:] if _raw_hex else b""
                _LOGGER.info(
                    "msg_type=0x%04x sub_type=0x%04x pay_len=%d direction=%s raw_payload_len=%d head16=%s",
                    getattr(message, "msg_type", 0) or 0,
                    getattr(message, "sub_type", 0) or 0,
                    getattr(message, "pay_len", 0) or 0,
                    getattr(message, "direction", None),
                    len(_forensic_payload),
                    _forensic_payload[:16].hex(),
                )
        except Exception as exc:  # 帧头日志旁路异常绝不影响提取
            _LOGGER.debug("帧头日志异常（已忽略）: %s", exc)

        # ── C->S extraction ──────────────────────────────────
        if message.direction == "C->S":
            # 标记：已见过 C->S 0x000F（init 包）
            if message.msg_type == 0x000F:
                self._seen_init = True

            # 已注册 (两个凭证都齐全) 则不再重复提取
            if not self._registered:
                self._extract_from_cs(message)

        # ── S->C extraction: roomid/gameid from RespJoinTable ──
        elif message.direction == "S->C":
            self._extract_room_from_sc(message)

    def _extract_from_cs(self, message):
        """Extract credentials from C->S messages."""
        payload = bytes.fromhex(message.raw_hex)[12:] if message.raw_hex else b""
        pay_len = message.pay_len

        if (message.msg_type == 0x0001 and self._handshake_blob is None
                and (self._seen_init or message.sub_type == 0x047b)):
            if len(payload) >= pay_len:
                self._handshake_blob = payload[:pay_len]
            elif len(payload) > 0:
                self._handshake_blob = payload
            if self._handshake_blob:
                print("[TokenExtractor] 已提取 handshake_blob: {} bytes (sub_type=0x{:04x})".format(
                    len(self._handshake_blob), message.sub_type))
                _LOGGER.info("handshake_blob 已提取 (%d bytes)，等待 auth_token_12b (0x0006)...",
                             len(self._handshake_blob))

        elif message.msg_type == 0x0006 and self._auth_token_12b is None:
            if pay_len == 16 and len(payload) >= 16:
                self._auth_token_12b = payload[4:16]
                print("[TokenExtractor] 已提取 auth_token_12b: {}".format(
                    self._auth_token_12b.hex()))
                _LOGGER.info("auth_token_12b 已提取: %s", self._auth_token_12b.hex())

        # 两个凭证都齐全后才注册
        if self._handshake_blob is not None and self._auth_token_12b is not None and not self._registered:
            self._registered = True
            if self._on_registered is not None:
                self._on_registered(self._handshake_blob, self._auth_token_12b)

    def _extract_room_from_sc(self, message):
        """Extract roomid/gameid from S->C RespJoinTable (msgid=14, RoomProtocol)."""
        if message.msg_type != 14:
            return

        if self._room_reported:
            return

        payload = bytes.fromhex(message.raw_hex)[12:] if message.raw_hex else b""
        if len(payload) < 1 + 4 + 4 + 4 + 4 + 4 + 4:
            _LOGGER.debug("RespJoinTable too short: %d bytes", len(payload))
            return

        try:
            offset = 0
            state = payload[offset]; offset += 1
            errorcode = struct.unpack_from("<i", payload, offset)[0]; offset += 4
            askid = struct.unpack_from("<i", payload, offset)[0]; offset += 4
            roommode = struct.unpack_from("<i", payload, offset)[0]; offset += 4
            gameappid = struct.unpack_from("<i", payload, offset)[0]; offset += 4
            roomid = struct.unpack_from("<i", payload, offset)[0]; offset += 4
            gameid = struct.unpack_from("<i", payload, offset)[0]; offset += 4

            self._room_id = roomid
            self._game_id = gameid
            self._room_reported = True

            print("[TokenExtractor] 已提取 roomid={}, gameid={} (RespJoinTable, errorcode={})".format(
                roomid, gameid, errorcode))
            _LOGGER.info("Room info extracted: roomid=%d, gameid=%d", roomid, gameid)

            if self._on_room_info is not None:
                self._on_room_info(roomid, gameid)

        except (struct.error, IndexError) as e:
            _LOGGER.warning("Failed to parse RespJoinTable: %s", e)

    @property
    def forensic_path(self):
        """旁观取证文件路径（供日志/排障打印）。"""
        return self._forensic.path

    def close(self):
        """关闭取证文件句柄。"""
        self._forensic.close()
