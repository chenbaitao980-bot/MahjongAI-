"""tcp_proxy.py — ECS 运行期双代理（部署到 ECS 永久跑）。

两条代理（都在 ECS 上 listen，手机经改过的 NetConf 连到 ECS）：

A. 大厅代理（默认 listen 5748/5749 → 透传到真大厅 47.96.101.155:同端口）
   在 S→C 流上识别 RespSRSAddr(msgid=15)，把其 payload 里的 szIP 改成 ECS IP
   （变长改写：readString=1B 长度前缀 + SRS 帧 payload_len 头 + 会话密钥 CFB 重加密）。
   这样游戏 SRS（动态下发的游服地址）也回流到 ECS。

B. 游服代理（默认 listen 7777 → 透传到真游服 47.96.0.227:7777）
   被动旁路解 0x2bc0（明文，sub 在 stable/protocol.py），喂 MJProtocol→PacketStateTracker
   → BattleState → 推进 remote/relay/state_store.StateStore（与 noconfig 网页共用）。
   纯被动，不改 7777 流字节。

RespSRSAddr 帧结构（逆向坐实）：
  wire frame = SRS 12B header(frame.py) + payload
    header: flag(0x4001,u16) payload_len(u16 LE) msg_type(u16 LE) sub_type(u16) extra(u32)
    payload(明文) = nAppID(u16 LE) + szIP(readString:1B len + bytes) + sPort(u16 LE)
  payload 在 S→C 方向用 **会话密钥 AES-CFB128、每帧 fresh-from-IV** 加密（crypto.py）。

会话密钥来源：握手 HandshakeRsp(msgid=4) S→C 用**默认密钥**（fresh-from-IV）加密，
  payload 解出 = keylen(1B)+key。代理在 S→C 流上看到 msgid=4 即可学到会话密钥，
  之后用它解/加 msgid=15。RespPlusData(msgid=24) 的 keylen 实测=0（m_key 不下发），
  故 key 保持会话密钥不变（见记忆 srs-cfb-and-string-prefix-fix）。

⚠ 需真机/抓包校验点（已尽量实现，但无真机 RespSRSAddr 样本时只能单元测试覆盖）：
  - RespSRSAddr 是否真用「会话密钥、fresh-from-IV」加密（与 PlayerData/RespPlusData 同规则，
    本代码按此假设）。若实际用 m_key 或连续 CFB 流，需调整 key 选择 / reset 时机。
  - msgid=15 是否可能跨多个 TCP 段拆包（read_frame_from_stream 已处理粘包/拆包，
    但 CFB 整 payload 解密要求拿到完整帧——已用帧重组保证）。

隔离：本文件全新；import 复用 frame.py/crypto.py（不改）、stable.protocol/tracker、
  relay.state_store（不改源码）。
"""
from __future__ import annotations

import logging
import os
import socket
import struct
import sys
import threading

# 允许 `python remote/noconfig/hijack/tcp_proxy.py` 直接跑自测（补 repo root 到 sys.path）。
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from remote.srs_spectator.crypto import SRSCrypto, SRS_DEFAULT_KEY
from remote.srs_spectator.frame import (
    HDR_LEN,
    pack_frame,
    read_frame_from_stream,
    unpack_frame,
    MSG_HANDSHAKE_RSP,
)

logger = logging.getLogger("remote.noconfig.hijack.tcp_proxy")

MSG_RESP_SRS_ADDR = 15  # CMDT_RESPSRSADDR (SRSProtocol.lua:13)
MSG_PLAYER_DATA = 6     # CMDT_PLAYERDATA — S→C，含 nickname + numid + sessionid（presence 源）
MSG_RESP_CREATE_TABLE = 12  # RoomProtocol.RespCreateTable
MSG_RESP_JOIN_TABLE = 14    # RoomProtocol.RespJoinTable
MSG_RESP_JOIN_GOLD = 18     # RoomProtocol.RespJoinTableWithGold

# 真服地址（默认值，可参数化）
REAL_LOBBY_IP = "47.96.101.155"
REAL_GAME_IP = "47.96.0.227"
REAL_GAME_PORT = 7777
DEFAULT_LOBBY_PORTS = (5748, 5749)

# 游服端口范围（RespSRSAddr 下发的牌局游服端口，动态 5700-5723+）
GAME_PORT_RANGE = (5700, 5799)


def _route_diag_tag(listen_port: int) -> str:
    """Return a stable diagnostic tag for a proxy listen port."""
    if listen_port == REAL_GAME_PORT:
        return "fixed_7777_compat"
    try:
        from remote.noconfig.hijack.netconf_patch import SRS50_REMAP
    except Exception:
        SRS50_REMAP = {}
    for gid, (_real_host, _real_port, ecs_listen_port) in SRS50_REMAP.items():
        if ecs_listen_port == listen_port:
            return f"srs50_gid={gid}"
    if GAME_PORT_RANGE[0] <= listen_port <= GAME_PORT_RANGE[1]:
        return "dynamic_resp_srs_addr"
    return "generic"


# ─── RespSRSAddr payload 改写（变长）────────────────────────────────────────

def parse_resp_srs_addr(payload_plain: bytes) -> dict:
    """解明文 RespSRSAddr payload → {nAppID, szIP, sPort}。"""
    if len(payload_plain) < 3:
        raise ValueError("RespSRSAddr payload too short")
    off = 0
    n_app_id = struct.unpack_from("<H", payload_plain, off)[0]; off += 2
    slen = payload_plain[off]; off += 1
    if off + slen + 2 > len(payload_plain):
        raise ValueError("RespSRSAddr szIP/sPort truncated")
    sz_ip = payload_plain[off:off + slen].decode("ascii", errors="replace"); off += slen
    s_port = struct.unpack_from("<H", payload_plain, off)[0]; off += 2
    return {"nAppID": n_app_id, "szIP": sz_ip, "sPort": s_port}


def build_resp_srs_addr(n_app_id: int, sz_ip: str, s_port: int) -> bytes:
    """重建明文 RespSRSAddr payload（readString=1B 长度前缀）。"""
    ip_bytes = sz_ip.encode("ascii")
    if len(ip_bytes) > 255:
        raise ValueError("szIP too long for 1-byte length prefix")
    return (
        struct.pack("<H", n_app_id)
        + bytes([len(ip_bytes)])
        + ip_bytes
        + struct.pack("<H", s_port)
    )


def parse_room_enter_payload(payload_plain: bytes) -> dict:
    """Parse shared fields from RoomProtocol enter-room responses."""
    if len(payload_plain) < 30:
        raise ValueError(f"room enter payload too short: {len(payload_plain)}")

    off = 0
    info = {"state": payload_plain[off], "payload_len": len(payload_plain)}
    off += 1
    for key in ("errorcode", "askid", "roommode", "gameappid", "roomid", "gameid", "tableid"):
        info[key] = struct.unpack_from("<i", payload_plain, off)[0]
        off += 4
    info["chairid"] = payload_plain[off]
    off += 1

    # Success payloads put srsgroupid immediately after chairid. Error msgbox is
    # variable-length, so avoid guessing in the side-path logger.
    if info["errorcode"] == 0 and len(payload_plain) >= off + 4:
        info["srsgroupid"] = struct.unpack_from("<i", payload_plain, off)[0]
        off += 4
    else:
        info["srsgroupid"] = None

    for key in ("teaid", "proxyid", "teaappid", "tealevel"):
        if len(payload_plain) >= off + 4:
            info[key] = struct.unpack_from("<i", payload_plain, off)[0]
            off += 4

    return info


def is_plausible_room_enter(info: dict) -> bool:
    """Heuristic guard for diagnostic parsing candidates."""
    try:
        return (
            0 <= int(info.get("state", -1)) <= 20
            and 0 <= int(info.get("errorcode", -1)) <= 300
            and 0 <= int(info.get("roommode", -1)) <= 300
            and 0 <= int(info.get("gameappid", -1)) <= 100000000
            and 0 <= int(info.get("roomid", -1)) <= 99999999
            and 0 <= int(info.get("gameid", -1)) <= 999999
            and 0 <= int(info.get("srsgroupid") or 0) <= 100000
        )
    except Exception:
        return False


def rewrite_resp_srs_addr_frame(
    frame_bytes: bytes, new_ip: str, crypto: SRSCrypto,
    lobby_ports: tuple[int, ...] = DEFAULT_LOBBY_PORTS,
    rewrite_port: int | None = None,
) -> tuple[bytes, dict | None]:
    """改写一个完整 RespSRSAddr 线缆帧：解密→换 szIP→重加密→重打帧（变长 OK）。

    frame_bytes:   完整一帧（12B header + 加密 payload）。
    crypto:        已装好**会话密钥**的 SRSCrypto；本函数按「fresh-from-IV」规则
                   在解/加密前各 reset 一次（S→C 每帧独立）。
    lobby_ports:   大厅端口列表，这些端口的条目不写（避免死循环）。
    rewrite_port:  若指定，所有非大厅端口的 sPort 也改写为此端口。
                   用途：ECS 只开一个安全组端口（如 7777），手机连 ECS:7777，
                   代理根据原始地址转发到真服的原始 IP:port。
    返回 (新帧字节, 原始地址信息dict 或 None)。
    原始地址信息 = {"orig_ip": str, "orig_port": int}，供代理按需转发。
    """
    fr = unpack_frame(frame_bytes)
    if fr is None or fr["msg_type"] != MSG_RESP_SRS_ADDR:
        return frame_bytes, None  # 非目标帧，原样返回

    enc_payload = fr["payload"]

    crypto.reset_cfb()
    plain = crypto.decrypt_payload(enc_payload)
    info = parse_resp_srs_addr(plain)

    # 不改大厅端口自身的条目（避免 5748/5749 写成 ECS 后连不上真大厅）
    if info["sPort"] in lobby_ports:
        logger.debug("RespSRSAddr: sPort=%d is lobby port, skip rewrite", info["sPort"])
        return frame_bytes, None

    # 不改已经是 ECS IP 且端口也匹配的条目（幂等）
    new_port = rewrite_port if rewrite_port is not None else info["sPort"]
    if info["szIP"] == new_ip and info["sPort"] == new_port:
        return frame_bytes, None

    orig_info = {"orig_ip": info["szIP"], "orig_port": info["sPort"]}
    logger.info("RespSRSAddr(游服): szIP %s:%d -> %s:%d",
                info["szIP"], info["sPort"], new_ip, new_port)

    new_plain = build_resp_srs_addr(info["nAppID"], new_ip, new_port)

    crypto.reset_cfb()
    new_enc = crypto.encrypt_payload(new_plain)

    # 用 frame.pack_frame 重打头：payload_len 随新长度自动正确。
    return pack_frame(
        MSG_RESP_SRS_ADDR, new_enc,
        sub_type=fr["sub_type"], extra=fr["extra"],
    ), orig_info


# ─── S→C 流改写器（学会话密钥 + 改 RespSRSAddr）──────────────────────────────

class LobbyS2CRewriter:
    """大厅 S→C 字节流改写：缓冲粘包/拆包，按帧处理。

    - 看到 HandshakeRsp(msgid=4)：用默认密钥解出会话密钥，装入 self.crypto。
    - 看到 RespSRSAddr(msgid=15)：用会话密钥变长改写 szIP→ECS IP，sPort→rewrite_port。
      改写后通知 game_proxy_manager 记录 orig_ip:orig_port，供代理转发。
    - 其余帧原样转发。
    """

    def __init__(self, ecs_ip: str, lobby_ports: tuple[int, ...] = DEFAULT_LOBBY_PORTS,
                 game_proxy_manager=None, rewrite_port: int | None = None,
                 on_player_data=None, lobby_tap=None, tap_port: int = 0,
                 source_host: str = ""):
        self.ecs_ip = ecs_ip
        self.lobby_ports = lobby_ports
        self.game_proxy_manager = game_proxy_manager  # DynamicGameProxyManager 实例
        self.rewrite_port = rewrite_port  # 所有非大厅端口改写成此端口（如 7777）
        self.crypto = SRSCrypto(key=SRS_DEFAULT_KEY)  # 先默认密钥；学到会话密钥后切换
        self._session_key_learned = False
        self._buf = bytearray()
        # presence：大厅登录后服务器下发 PlayerData(msgid=6)，含 sessionid+nickname。
        # 只读解析触发上报（不改透传），让"进大厅即在线"也能生效。
        self._on_player_data = on_player_data
        self._player_data_fired = False
        self._lobby_tap = lobby_tap
        self._tap_port = tap_port
        self._source_host = source_host or ""
        self._user_id = ""
        self._sessionid = ""

    def feed(self, data: bytes) -> bytes:
        """喂入 S→C 原始字节，返回（可能改写后的）应转发给手机的字节。

        关键：非 RespSRSAddr 帧一律**原始字节透传**，绝不 unpack→pack 重组。
        pack_frame 用固定 FLAG、重组可能与原始字节有出入，会损坏登录等复杂帧，
        导致手机卡登录。只有 msgid=15(RespSRSAddr) 才改写那一帧。
        """
        import struct
        self._buf += data
        out = bytearray()
        while len(self._buf) >= 12:
            _flag, pay_len, msg_type, _sub, _extra = struct.unpack("<HHHHI", bytes(self._buf[:12]))
            total = 12 + pay_len
            if len(self._buf) < total:
                break
            raw = bytes(self._buf[:total])
            del self._buf[:total]
            out += self._handle_frame_raw(msg_type, raw)
        return bytes(out)

    def _handle_frame_raw(self, msg_type: int, raw: bytes) -> bytes:
        """处理单个完整帧的原始字节：学密钥/改写 RespSRSAddr，其余原样透传。"""
        if msg_type == MSG_HANDSHAKE_RSP and not self._session_key_learned:
            try:
                self.crypto.reset_cfb()
                dec = self.crypto.decrypt_payload(raw[12:])  # payload = 头之后
                key_len = dec[0]
                session_key = dec[1:1 + key_len]
                if len(session_key) in (16, 24, 32):
                    self.crypto.set_key(session_key)
                    self._session_key_learned = True
                    logger.info("[lobby] session key learned from HandshakeRsp (%dB key)",
                                len(session_key))
                else:
                    logger.warning("[lobby] HandshakeRsp keylen=%d unexpected; keeping default key",
                                   len(session_key))
            except Exception as e:
                logger.warning("[lobby] HandshakeRsp parse failed: %s", e)
            return raw  # 原样透传

        if msg_type in (MSG_RESP_CREATE_TABLE, MSG_RESP_JOIN_TABLE, MSG_RESP_JOIN_GOLD):
            msg_name = {
                MSG_RESP_CREATE_TABLE: "RespCreateTable",
                MSG_RESP_JOIN_TABLE: "RespJoinTable",
                MSG_RESP_JOIN_GOLD: "RespJoinTableWithGold",
            }.get(msg_type, f"msg_{msg_type}")
            if not self._session_key_learned:
                logger.info("[lobby-enter] %s frame seen before session key (%dB); pass-through",
                            msg_name, len(raw))
                return raw
            try:
                candidates = [("raw", raw[12:])]
                self.crypto.reset_cfb()
                candidates.append(("aes", self.crypto.decrypt_payload(raw[12:])))
                parsed = []
                for codec, payload in candidates:
                    try:
                        info = parse_room_enter_payload(payload)
                        parsed.append((codec, payload, info, is_plausible_room_enter(info)))
                    except Exception as exc:
                        logger.warning("[lobby-enter] %s %s parse failed: %s payload_len=%d raw_len=%d head=%s",
                                       msg_name, codec, exc, len(payload), len(raw), payload[:48].hex())
                for codec, payload, info, plausible in parsed:
                    logger.info(
                        "[lobby-enter] %s codec=%s plausible=%s msg=%d state=%s error=%s roommode=%s "
                        "gameappid=%s roomid=%s gameid=%s tableid=%s chairid=%s "
                        "srsgroupid=%s teaid=%s proxyid=%s teaappid=%s tealevel=%s payload_len=%s head=%s",
                        msg_name, codec, plausible, msg_type,
                        info.get("state"), info.get("errorcode"), info.get("roommode"),
                        info.get("gameappid"), info.get("roomid"), info.get("gameid"),
                        info.get("tableid"), info.get("chairid"), info.get("srsgroupid"),
                        info.get("teaid"), info.get("proxyid"), info.get("teaappid"),
                        info.get("tealevel"), info.get("payload_len"), payload[:48].hex(),
                    )
            except Exception as e:
                logger.warning("[lobby-enter] %s parse failed: %s raw_len=%d",
                               msg_name, e, len(raw))
            return raw

        if msg_type == 0x2BC0 and self._lobby_tap is not None:
            try:
                pkt = {
                    "src": "server",
                    "dst": "client",
                    "src_port": self._tap_port,
                    "dst_port": 0,
                    "payload": raw,
                }
                self._lobby_tap.feed_packet(pkt)
                logger.info("[lobby-tap] 0x2bc0 on lobby_port=%d len=%d head=%s",
                            self._tap_port, len(raw),
                            raw[HDR_LEN:HDR_LEN + 24].hex())
            except Exception as exc:
                logger.warning("[lobby-tap] 0x2bc0 side tap failed on lobby_port=%d: %s",
                               self._tap_port, exc)
            return raw

        if msg_type == MSG_RESP_SRS_ADDR:
            logger.info("[lobby] RespSRSAddr frame seen (%dB), session_key_learned=%s — rewriting szIP->ECS",
                        len(raw), self._session_key_learned)
            try:
                new_frame, orig_info = rewrite_resp_srs_addr_frame(
                    raw, self.ecs_ip, self.crypto,
                    lobby_ports=self.lobby_ports,
                    rewrite_port=self.rewrite_port)
                logger.info("[lobby] RespSRSAddr rewritten: %dB -> %dB orig=%s", len(raw), len(new_frame), orig_info)
                # 通知代理管理器记录原始地址，供 7777 代理转发
                if orig_info and self.game_proxy_manager:
                    self.game_proxy_manager.register_orig_addr(
                        orig_info["orig_ip"], orig_info["orig_port"])
                return new_frame
            except Exception as e:
                logger.error("[lobby] RespSRSAddr rewrite FAILED (%s); forwarding original — "
                             "phone will connect to real game server (not ECS)", e)
                return raw

        # PlayerData(msgid=6)：只读解析 sessionid+nickname → presence 上报（不改透传）
        if (msg_type == MSG_PLAYER_DATA and self._session_key_learned
                and self._on_player_data and not self._player_data_fired):
            try:
                self.crypto.reset_cfb()  # fresh-from-IV，与 RespSRSAddr 一致
                dec = self.crypto.decrypt_payload(raw[12:])
                from remote.srs_spectator.handshake import parse_player_data
                info = parse_player_data(dec)
                if info and not info.get("error") and info.get("sessionid"):
                    self._player_data_fired = True
                    sid = info.get("sessionid")
                    numid = info.get("numid", 0)
                    # user_id 用稳定的 numid（同一账号不变），sessionid 单独保存
                    self._user_id = str(numid) if numid else ""
                    self._sessionid = sid.hex() if isinstance(sid, (bytes, bytearray)) else str(sid)
                    if self._lobby_tap is not None:
                        try:
                            self._lobby_tap.set_user_id(self._user_id, self._sessionid)
                        except Exception as exc:
                            logger.debug("[lobby] tap user_id bind failed: %s", exc)
                    if self.game_proxy_manager is not None:
                        self.game_proxy_manager.set_user_id(self._user_id, self._sessionid)
                    info = dict(info)
                    if self._source_host:
                        info.setdefault("source_host", self._source_host)
                    self._on_player_data(info)
            except Exception as e:
                logger.debug("[lobby] PlayerData parse/presence failed: %s", e)

        return raw  # 其它帧一律原样透传


# ─── S→C 流解密器（游服代理用：学密钥 + 解密 payload → 明文帧）────────────────

class GameS2CDecryptor:
    """游服 S→C 字节流解密：缓冲粘包/拆包，按帧解密。

    - 看到 HandshakeRsp(msgid=4)：用默认密钥解出会话密钥，装入 self.crypto。
    - 之后所有 S→C 帧：用会话密钥解密 payload，重新打包成明文帧输出。
    - C→S 方向不解密（原样透传，由调用方处理）。
    - 输出的是**明文帧流**（可直接喂给 MJProtocol）。
    """

    def __init__(self, on_player_data=None):
        self.crypto = SRSCrypto(key=SRS_DEFAULT_KEY)
        self._session_key_learned = False
        self._buf = bytearray()
        # presence 回调：解出 PlayerData(msgid=6) 后以 dict 回调（含 sessionid/nickname/numid）
        self._on_player_data = on_player_data
        self._player_data_fired = False  # 每条连接只上报一次 presence，避免刷屏
        # 诊断：记录已见过的 S→C msg_type（去重首见日志），统计帧数
        self._dbg_seen_types: set[int] = set()
        self._dbg_frame_count = 0

    def feed(self, data: bytes) -> bytes:
        """喂入 S→C 原始字节，返回解密后的明文帧流。"""
        self._buf += data
        out = bytearray()
        while len(self._buf) >= HDR_LEN:
            _flag, pay_len, msg_type, _sub, _extra = struct.unpack(
                "<HHHHI", bytes(self._buf[:HDR_LEN])
            )
            total = HDR_LEN + pay_len
            if len(self._buf) < total:
                break
            raw = bytes(self._buf[:total])
            del self._buf[:total]
            out += self._handle_frame_raw(msg_type, raw)
        return bytes(out)

    def _handle_frame_raw(self, msg_type: int, raw: bytes) -> bytes:
        """处理单个完整帧：学密钥 / 解密，返回明文帧字节。"""
        if msg_type == MSG_HANDSHAKE_RSP and not self._session_key_learned:
            try:
                self.crypto.reset_cfb()
                dec = self.crypto.decrypt_payload(raw[HDR_LEN:])
                key_len = dec[0]
                session_key = dec[1:1 + key_len]
                if len(session_key) in (16, 24, 32):
                    self.crypto.set_key(session_key)
                    self._session_key_learned = True
                    logger.info("[game-decrypt] session key learned from HandshakeRsp (%dB) KEYHEX=%s",
                                len(session_key), session_key.hex())
                else:
                    logger.warning("[game-decrypt] HandshakeRsp keylen=%d unexpected", len(session_key))
            except Exception as e:
                logger.warning("[game-decrypt] HandshakeRsp parse failed: %s", e)
            # HandshakeRsp 原样输出（MJProtocol 不需要它，但保持一致性）
            return raw

        # 0x2bc0 游戏事件在当前 noconfig / ECS 链路上是明文 payload。
        # 如果继续按系统帧那样做 AES-CFB 解密，会把本来合法的 game_event
        # 结构打坏，导致 stable/protocol.py 只能看到乱码 sub_cmd / hand_raw=None。
        #
        # 这与 cloud_player.py 的线上行为一致：它直接把 0x2bc0 payload 当明文喂给
        # MJProtocol，而不再额外解密。系统帧（如 0x0006 / 0x0018）仍然保持
        # fresh-from-IV 的 AES-CFB 解密路径。
        if msg_type == 0x2BC0:
            flag, pay_len, mt, sub, extra = struct.unpack("<HHHHI", raw[:HDR_LEN])
            plain_payload = raw[HDR_LEN:]
            if msg_type not in self._dbg_seen_types:
                self._dbg_seen_types.add(msg_type)
                logger.info("[game-decrypt][dbg] new msg=0x%04x flag=0x%04x sub=0x%04x extra=%d plain_head=%s",
                            msg_type, flag, sub, extra, plain_payload[:24].hex())
            logger.info("[game-decrypt][dbg] 0x2bc0 flag=0x%04x sub=0x%04x extra=%d ENC=%s",
                        flag, sub, extra, plain_payload[:96].hex())
            return raw

        # 已学到会话密钥：解密系统 payload 并重新打包成明文帧。
        if self._session_key_learned:
            try:
                self.crypto.reset_cfb()  # 基线：每帧 fresh-from-IV（系统帧对，游戏帧待破解）
                enc = raw[HDR_LEN:]
                plain_payload = self.crypto.decrypt_payload(enc)
                # ── 诊断：帧头字段（flag/sub/extra，extra 疑为每帧 IV/序号）+ 原始密文 ──
                self._dbg_frame_count += 1
                flag, pay_len, mt, sub, extra = struct.unpack("<HHHHI", raw[:HDR_LEN])
                if msg_type not in self._dbg_seen_types:
                    self._dbg_seen_types.add(msg_type)
                    logger.info("[game-decrypt][dbg] new msg=0x%04x flag=0x%04x sub=0x%04x extra=%d plain_head=%s",
                                msg_type, flag, sub, extra, plain_payload[:24].hex())
                # PlayerData(msgid=6)：解出 sessionid+nickname，触发 presence 上报（每连接一次）
                if msg_type == MSG_PLAYER_DATA and self._on_player_data and not self._player_data_fired:
                    try:
                        from remote.srs_spectator.handshake import parse_player_data
                        info = parse_player_data(plain_payload)
                        if info and not info.get("error") and info.get("sessionid"):
                            self._player_data_fired = True
                            self._on_player_data(info)
                    except Exception as e:
                        logger.debug("[game-decrypt] PlayerData parse/presence failed: %s", e)
                # 重新打包：header 不变，payload 换成明文
                return raw[:HDR_LEN] + plain_payload
            except Exception as e:
                logger.warning("[game-decrypt] decrypt failed: %s", e)
                # 解密失败，原样输出（避免阻断）
                return raw

        return raw  # 未学到密钥，原样输出


# ─── 动态游服代理管理器 ──────────────────────────────────────────────────────

class DynamicGameProxyManager:
    """管理游服地址映射 + 按需动态端口代理。

    方案：RespSRSAddr 只改 szIP→ECS，保留原始 sPort。
    当手机连 ECS:orig_port 时，代理在对应端口起 TcpProxy 转发到真服 orig_ip:orig_port。
    安全组需放行 5700-5799 端口范围。
    """

    def __init__(self, listen_host: str = "0.0.0.0",
                 relay_push_url: str | None = None,
                 api_token: str = "",
                 on_player_data=None):
        self.listen_host = listen_host
        self.relay_push_url = relay_push_url
        self.api_token = api_token
        self.on_player_data = on_player_data
        self._user_id = ""
        self._sessionid = ""
        self._taps: list = []
        # port -> (orig_ip, orig_port) 映射
        self._addr_map: dict[int, tuple[str, int]] = {}
        # port -> TcpProxy
        self._proxies: dict[int, TcpProxy] = {}
        self._lock = threading.Lock()

    def set_user_id(self, user_id: str, sessionid: str = "") -> None:
        """设置 user_id 并传播到所有已有的 game tap"""
        self._user_id = user_id or ""
        self._sessionid = sessionid or ""
        for tap in self._taps:
            try:
                tap.set_user_id(self._user_id, self._sessionid)
            except Exception:
                pass
        logger.info("[game-mgr] user_id set to %s, propagated to %d taps",
                    self._user_id[:16] if self._user_id else "default", len(self._taps))

    def register_orig_addr(self, orig_ip: str, orig_port: int) -> None:
        """记录一条 RespSRSAddr 改写的原始地址，并在 ECS:orig_port 起代理。"""
        with self._lock:
            if orig_port in self._proxies:
                # 代理已存在，更新上游地址
                self._addr_map[orig_port] = (orig_ip, orig_port)
                logger.info("[game-mgr] reuse dynamic route :%d -> %s:%d tag=%s active_ports=%s",
                            orig_port, orig_ip, orig_port,
                            _route_diag_tag(orig_port), sorted(self._proxies.keys()))
                return

        # 端口范围检查
        lo, hi = GAME_PORT_RANGE
        active_ports = self.active_ports
        if not (lo <= orig_port <= hi):
            logger.info("[game-mgr] port %d outside game range %d-%d, skip proxy",
                        orig_port, lo, hi)
            return
        logger.info("[game-mgr] register dynamic route :%d -> %s:%d tag=%s active_before=%s",
                    orig_port, orig_ip, orig_port,
                    _route_diag_tag(orig_port), active_ports)

        # 创建并启动代理：每连接新建 tap+decryptor（旧 session key 跨连接污染根因）
        def _make_on_bytes():
            tap = GameTapDecoder(state_store=None, local_player=1,
                                 server_port=orig_port,
                                 relay_push_url=self.relay_push_url,
                                 api_token=self.api_token)
            tap.set_user_id(self._user_id, self._sessionid)
            self._taps.append(tap)
            decryptor = GameS2CDecryptor(on_player_data=self.on_player_data)

            def _on_bytes(direction: str, data: bytes) -> None:
                if direction == "S->C":
                    # 解密 S→C 帧流：HandshakeRsp 学密钥，后续帧解密 payload
                    decrypted = decryptor.feed(data)
                    pkt = {"src": "server", "dst": "client",
                           "src_port": orig_port, "dst_port": 0, "payload": decrypted}
                else:
                    # C→S 原样透传
                    pkt = {"src": "client", "dst": "server",
                           "src_port": 0, "dst_port": orig_port, "payload": data}
                try:
                    tap.feed_packet(pkt)
                except Exception as exc:
                    logger.warning("[game-mgr] tap feed error on :%d: %s", orig_port, exc)
                # 日志：首次收到数据时记录方向和长度
                if not getattr(tap, '_first_data_logged', False):
                    tap._first_data_logged = True
                    logger.info("[game-mgr] first data on :%d tag=%s dir=%s len=%d head=%s",
                                orig_port, _route_diag_tag(orig_port), direction,
                                len(data), data[:12].hex() if len(data) >= 12 else data.hex())

            return _on_bytes

        proxy = TcpProxy(
            self.listen_host, orig_port,
            orig_ip, orig_port,
            on_bytes_factory=_make_on_bytes,
            diag_tag=_route_diag_tag(orig_port),
        )
        try:
            proxy.start()
        except OSError as e:
            logger.error("[game-mgr] failed to listen on :%d -> %s:%d: %s",
                         orig_port, orig_ip, orig_port, e)
            return

        with self._lock:
            # double-check
            if orig_port in self._proxies:
                proxy.stop()
                return
            self._proxies[orig_port] = proxy
            self._addr_map[orig_port] = (orig_ip, orig_port)

        logger.info("[game-mgr] + dynamic game proxy :%d -> %s:%d tag=%s (0x2bc0 tap + relay push)",
                    orig_port, orig_ip, orig_port, _route_diag_tag(orig_port))

    @property
    def addr_map(self) -> dict:
        with self._lock:
            return dict(self._addr_map)

    @property
    def active_ports(self) -> list[int]:
        with self._lock:
            return sorted(self._proxies.keys())


# ─── 被动 7777 旁路解码 → StateStore ─────────────────────────────────────────

class GameTapDecoder:
    """被动喂 7777 双向字节给 MJProtocol/PacketStateTracker，推进 StateStore。

    复用 stable 管线（不改源码）。state_store 可为 None（仅本地解码自测）。
    relay_push_url 不为 None 时，每次 hand_trusted 后 POST /push 到 noconfig relay。
    """

    def __init__(self, state_store=None, local_player: int = 1,
                 server_port: int = REAL_GAME_PORT,
                 relay_push_url: str | None = None,
                 api_token: str = ""):
        # 延迟 import，避免无 stable 依赖时本模块（仅 RespSRSAddr 部分）也能用。
        from stable.mapping import MappingStore
        from stable.protocol import MJProtocol
        from stable.tracker import PacketStateTracker

        self._store = state_store
        self._mapping = MappingStore(path=None)
        self._tracker = PacketStateTracker(self._mapping, local_player=local_player)
        self._proto = MJProtocol(server_port=server_port)
        self._relay_push_url = relay_push_url
        self._api_token = api_token
        self._last_push_hand = None  # 去重：手牌没变就不重复 push
        self._user_id = ""
        self._sessionid = ""

    def set_user_id(self, user_id: str, sessionid: str = "") -> None:
        self._user_id = user_id or ""
        self._sessionid = sessionid or ""

    @staticmethod
    def _extract_local_hand(snapshot: dict) -> list[str]:
        local_player = snapshot.get("local_player")
        players = snapshot.get("players") or {}
        player_state = players.get(local_player)
        if player_state is None and local_player is not None:
            player_state = players.get(str(local_player))
        hand = player_state.get("hand") if isinstance(player_state, dict) else []
        return list(hand or [])

    def feed_packet(self, pkt: dict) -> None:
        """pkt 为 PcapParser/NpcapCapture 风格的包 dict（含 src/dst/seq/payload）。"""
        prev_trusted = self._tracker.hand_trusted
        for msg in self._proto.process_packet(pkt):
            # ── 诊断：MJProtocol 解出的 0x2bc0 game_event 内容 ──
            if getattr(msg, "msg_type", None) == 0x2BC0:
                g = msg.game or {}
                logger.info("[game][dbg] MJ 0x2bc0 decoded: keys=%s hand_raw=%s untrusted=%s count=%s",
                            list(g.keys()), g.get("hand_raw"),
                            g.get("untrusted_hand_raw_candidate"), g.get("count"))
            self._tracker.apply(msg)
            # 0x2bc0 hand_raw 首次 trusted：打一条 INFO 日志
            if not prev_trusted and self._tracker.hand_trusted:
                snap = self._tracker.snapshot()
                hand = self._extract_local_hand(snap)
                logger.info("[game] 0x2bc0 hand_trusted: hand=%s phase=%s",
                            hand, snap.get("phase"))
                prev_trusted = True
        if self._tracker.hand_trusted:
            snap = self._tracker.snapshot()
            # 推 StateStore（如有）
            if self._store is not None:
                try:
                    self._store.on_game_event(snap)
                except Exception as e:
                    logger.warning("[game] state_store push failed: %s", e)
            # 推 noconfig relay HTTP（如有，去重：手牌没变就不重复 push）
            cur_hand = tuple(self._extract_local_hand(snap))
            if self._relay_push_url and cur_hand != self._last_push_hand:
                self._last_push_hand = cur_hand
                self._push_to_relay(snap)

    @property
    def hand_trusted(self) -> bool:
        return self._tracker.hand_trusted

    def snapshot(self) -> dict:
        return self._tracker.snapshot()

    def _push_to_relay(self, snap: dict) -> None:
        """POST /push 到同机 noconfig relay（8002），让网页也能看到手牌。"""
        try:
            import requests as _req
            body = {"snapshot": snap, "api_token": self._api_token}
            if self._user_id:
                body["user_id"] = self._user_id
            if self._sessionid:
                body["srs_sessionid"] = self._sessionid
            _req.post(
                self._relay_push_url,
                json=body,
                timeout=3,
            )
            logger.info("[game] push to relay OK: user=%s phase=%s hand=%s",
                        self._user_id[:12] or "default",
                        snap.get("phase"), self._extract_local_hand(snap))
        except Exception as e:
            logger.warning("[game] push to relay FAILED: %s", e)


# ─── 透传代理（TCP）──────────────────────────────────────────────────────────

class TcpProxy:
    """通用 TCP 透传代理，可选注入 S→C 改写器（大厅）或 7777 被动旁路。

    s2c_rewriter: callable(bytes)->bytes，对 S→C 字节流改写（大厅用 LobbyS2CRewriter.feed）。
                  None = 原样透传。
    on_bytes:     callable(direction, data)，被动观测钩子（全连接共用一个实例）。
    on_bytes_factory: callable()->callable(direction,data)，**每条连接调用一次**返回独立
                  的 on_bytes。游服代理必须用它——否则 GameS2CDecryptor 会跨连接共用旧
                  session key，重连新局时忽略新 HandshakeRsp，导致解不出（实锤根因）。
                  若提供 factory，则忽略 on_bytes。
    """

    def __init__(self, listen_host: str, listen_port: int,
                 upstream_host: str, upstream_port: int,
                 s2c_rewriter=None, on_bytes=None, on_bytes_factory=None,
                 diag_tag: str | None = None,
                 on_connect=None):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.s2c_rewriter = s2c_rewriter
        self.on_bytes = on_bytes
        self.on_bytes_factory = on_bytes_factory
        self.diag_tag = diag_tag or _route_diag_tag(listen_port)
        self.on_connect = on_connect
        self._srv = None
        self._running = False

    def start(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.listen_host, self.listen_port))
        self._srv.listen(64)
        self._running = True
        logger.info("TcpProxy listening %s:%d -> %s:%d tag=%s",
                    self.listen_host, self.listen_port,
                    self.upstream_host, self.upstream_port, self.diag_tag)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client, addr = self._srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client, addr),
                             daemon=True).start()

    def _handle_client(self, client: socket.socket, addr) -> None:
        if callable(self.s2c_rewriter):
            try:
                rewriter = self.s2c_rewriter(addr)
            except TypeError:
                rewriter = self.s2c_rewriter()
        else:
            rewriter = None
        # 每条连接独立的 on_bytes：游服解码器/tap 不可跨连接共用（旧 session key 污染根因）。
        if self.on_bytes_factory is not None:
            on_bytes = self.on_bytes_factory()
        else:
            on_bytes = self.on_bytes
        try:
            up = socket.create_connection((self.upstream_host, self.upstream_port))
        except Exception as e:
            logger.error("[proxy %d][%s] upstream connect failed %s:%d — %s",
                         self.listen_port, self.diag_tag,
                         self.upstream_host, self.upstream_port, e)
            client.close()
            return
        logger.info("[proxy %d][%s] + %s -> %s:%d",
                    self.listen_port, self.diag_tag,
                    addr[0], self.upstream_host, self.upstream_port)
        if self.on_connect:
            try:
                self.on_connect(self.listen_port, addr)
            except Exception as exc:
                logger.debug("[proxy %d][%s] on_connect failed: %s",
                             self.listen_port, self.diag_tag, exc)

        # C→S 与 S→C 共用本连接的 on_bytes（解码器需同时看到两个方向）
        threading.Thread(target=self._pump, args=(client, up, "C->S", None, addr, on_bytes),
                         daemon=True).start()
        # S→C（可改写）
        self._pump(up, client, "S->C", rewriter, addr, on_bytes)
        logger.info("[proxy %d][%s] - %s disconnected",
                    self.listen_port, self.diag_tag, addr[0])

    def _pump(self, src: socket.socket, dst: socket.socket, direction: str,
              rewriter, addr=None, on_bytes=None) -> None:
        total = 0
        try:
            while self._running:
                data = src.recv(65536)
                if not data:
                    break
                total += len(data)
                if total == len(data):
                    peer = addr[0] if addr else "?"
                    logger.debug("[proxy %d][%s] %s %s first chunk %dB",
                                 self.listen_port, self.diag_tag, peer, direction, len(data))
                if on_bytes:
                    try:
                        on_bytes(direction, data)
                    except Exception:
                        pass
                if direction == "S->C" and rewriter is not None:
                    data = rewriter.feed(data)
                dst.sendall(data)
        except Exception:
            pass
        finally:
            # 诊断：无条件记录两个方向的字节总数（含 0），用于判定大厅上游是否响应。
            # C->S total = 手机发出的字节数；S->C total = 上游回发的字节数。
            # 若 C->S>0 且 S->C=0 → 上游接受连接却不回包；若 C->S=0 → 手机未发登录包。
            peer = addr[0] if addr else "?"
            logger.debug("[proxy %d][%s] %s %s session ended, %dB total",
                         self.listen_port, self.diag_tag, peer, direction, total)
            for s in (src, dst):
                try:
                    s.close()
                except Exception:
                    pass


def build_lobby_proxy(listen_host: str, listen_port: int, ecs_ip: str,
                      real_lobby_ip: str = REAL_LOBBY_IP,
                      upstream_port: int | None = None,
                      lobby_ports: tuple[int, ...] = DEFAULT_LOBBY_PORTS,
                      game_proxy_manager=None,
                      rewrite_port: int | None = None,
                      on_player_data=None,
                      relay_push_url: str | None = None,
                      api_token: str = "",
                      on_connect=None) -> TcpProxy:
    """大厅代理工厂：S→C 改写 RespSRSAddr.szIP → ecs_ip, sPort → rewrite_port。"""
    def _make_rewriter(addr=None):
        source_host = addr[0] if addr else ""
        tap = None
        if relay_push_url:
            tap = GameTapDecoder(state_store=None, local_player=1,
                                 server_port=listen_port,
                                 relay_push_url=relay_push_url,
                                 api_token=api_token)
        return LobbyS2CRewriter(
            ecs_ip, lobby_ports=lobby_ports,
            game_proxy_manager=game_proxy_manager,
            rewrite_port=rewrite_port,
            on_player_data=on_player_data,
            lobby_tap=tap,
            tap_port=listen_port,
            source_host=source_host)

    return TcpProxy(
        listen_host, listen_port,
        real_lobby_ip, upstream_port or listen_port,
        s2c_rewriter=_make_rewriter,
        diag_tag=f"lobby_port={listen_port}",
        on_connect=on_connect,
    )


def build_game_proxy(listen_host: str, listen_port: int,
                     real_game_ip: str = REAL_GAME_IP,
                     state_store=None,
                     local_player: int = 1,
                     relay_push_url: str | None = None,
                     api_token: str = "",
                     upstream_port: int | None = None,
                     on_player_data=None,
                     diag_tag: str | None = None,
                     game_proxy_manager=None) -> TcpProxy:
    """游服代理工厂：7777 透传 + 被动 0x2bc0 旁路解码 → StateStore + relay push。

    state_store 为 None 时只解码不推送（自测用）。
    relay_push_url 不为 None 时，解码结果 POST /push 到同机 noconfig relay（8002）。
    on_player_data 不为 None 时，解出 PlayerData(msgid=6) 触发 presence 上报。
    game_proxy_manager 不为 None 时，创建的 tap 会注册进去，以便接收 user_id。

    关键：用 on_bytes_factory **每连接新建** tap+decryptor——否则跨连接共用同一
    GameS2CDecryptor，首局学到 session key 后锁死，手机重连新局时忽略新 HandshakeRsp，
    继续用旧 key 解密导致全乱码（好友房/第二局起无数据的根因）。
    """
    def _make_on_bytes():
        tap = GameTapDecoder(state_store=state_store, local_player=local_player,
                             server_port=listen_port,
                             relay_push_url=relay_push_url, api_token=api_token)
        if game_proxy_manager is not None:
            tap.set_user_id(game_proxy_manager._user_id, game_proxy_manager._sessionid)
            game_proxy_manager._taps.append(tap)
        # SRS 游服流量是加密的：S→C 需先学会话密钥（HandshakeRsp）再解 payload。
        decryptor = GameS2CDecryptor(on_player_data=on_player_data)

        def _on_bytes(direction: str, data: bytes) -> None:
            # 构造合成包 dict：src_port/dst_port 用来区分方向，不需要真实 IP/seq
            if direction == "S->C":
                decrypted = decryptor.feed(data)
                pkt = {"src": "server", "dst": "client",
                       "src_port": listen_port, "dst_port": 0, "payload": decrypted}
            else:
                pkt = {"src": "client", "dst": "server",
                       "src_port": 0, "dst_port": listen_port, "payload": data}
            try:
                tap.feed_packet(pkt)
            except Exception as exc:
                logger.debug("game tap feed error: %s", exc)

        return _on_bytes

    return TcpProxy(
        listen_host, listen_port,
        real_game_ip, upstream_port if upstream_port is not None else listen_port,
        on_bytes_factory=_make_on_bytes,
        diag_tag=diag_tag,
    )


# ─── 自测 ────────────────────────────────────────────────────────────────────

def _selftest_resp_srs_addr() -> None:
    """单元测试：构造 RespSRSAddr 帧（会话密钥加密），跑变长改写，断言往返正确。

    无真机样本，用构造帧覆盖。模拟服务器：用已知会话密钥 fresh-from-IV 加密
    一条 szIP=47.96.0.227 的 RespSRSAddr；改写成 ECS IP（不同长度）；
    再用同密钥解回，断言 IP 变了、其余字段不变、payload_len 头随之变化。
    """
    session_key = bytes.fromhex("00112233445566778899aabbccddeeff")  # 16B 假会话密钥
    real_ip, ecs_ip = "47.96.0.227", "8.136.32.137"  # 11B vs 12B，变长
    n_app_id, s_port = 7, 12345

    # 1) 服务器侧构造加密帧（fresh-from-IV）
    srv = SRSCrypto(key=session_key)
    plain = build_resp_srs_addr(n_app_id, real_ip, s_port)
    srv.reset_cfb()
    enc = srv.encrypt_payload(plain)
    frame = pack_frame(MSG_RESP_SRS_ADDR, enc)
    print(f"[OK] 构造 RespSRSAddr 帧: {len(frame)}B (payload {len(enc)}B, szIP={real_ip})")

    # 2) 代理侧改写（同会话密钥，不改端口 = rewrite_port=None）
    proxy_crypto = SRSCrypto(key=session_key)
    new_frame, orig_info = rewrite_resp_srs_addr_frame(frame, ecs_ip, proxy_crypto,
                                                        rewrite_port=None)
    assert orig_info is not None, "orig_info should be returned"
    assert orig_info["orig_ip"] == real_ip, f"orig_ip mismatch: {orig_info}"
    assert orig_info["orig_port"] == s_port, f"orig_port mismatch: {orig_info}"
    nf = unpack_frame(new_frame)
    assert nf["msg_type"] == MSG_RESP_SRS_ADDR
    # payload_len 头随变长 IP 改变（ECS IP 比真服多 1B）
    assert nf["payload_len"] == len(enc) + (len(ecs_ip) - len(real_ip)), nf["payload_len"]
    print(f"[OK] 改写后帧: {len(new_frame)}B payload_len头={nf['payload_len']} (随 IP 变长 +1)")

    # 3) 客户端侧解回（fresh-from-IV），断言 szIP 已变、其余不变
    cli = SRSCrypto(key=session_key)
    cli.reset_cfb()
    dec = cli.decrypt_payload(nf["payload"])
    info = parse_resp_srs_addr(dec)
    assert info["szIP"] == ecs_ip, info
    assert info["nAppID"] == n_app_id, info
    assert info["sPort"] == s_port, info
    print(f"[OK] 客户端解回: nAppID={info['nAppID']} szIP={info['szIP']} sPort={info['sPort']}")
    print("[PASS] RespSRSAddr 变长改写单元测试通过 (构造帧；需真机校验 CFB 状态对齐)")


def _selftest_handshake_key_learn() -> None:
    """单元测试：S→C 流里 HandshakeRsp 后跟 RespSRSAddr，验证改写器自动学密钥并改写。"""
    session_key = bytes.fromhex("aabbccddeeff00112233445566778899")
    real_ip, ecs_ip = "47.96.0.227", "8.136.32.137"

    # 服务器：HandshakeRsp(默认密钥, fresh-IV) payload=keylen(16)+key
    srv_default = SRSCrypto(key=SRS_DEFAULT_KEY)
    hs_plain = bytes([len(session_key)]) + session_key
    srv_default.reset_cfb()
    hs_enc = srv_default.encrypt_payload(hs_plain)
    hs_frame = pack_frame(MSG_HANDSHAKE_RSP, hs_enc)

    # 服务器：RespSRSAddr(会话密钥, fresh-IV)
    srv_sess = SRSCrypto(key=session_key)
    addr_plain = build_resp_srs_addr(7, real_ip, 7777)
    srv_sess.reset_cfb()
    addr_enc = srv_sess.encrypt_payload(addr_plain)
    addr_frame = pack_frame(MSG_RESP_SRS_ADDR, addr_enc)

    # 代理改写器：分两次喂（验证粘包/拆包缓冲）
    rw = LobbyS2CRewriter(ecs_ip)
    stream = hs_frame + addr_frame
    out = rw.feed(stream[:7]) + rw.feed(stream[7:])
    assert rw._session_key_learned, "未从 HandshakeRsp 学到会话密钥"

    # 解析输出：HandshakeRsp 原样 + RespSRSAddr 改写
    buf = bytearray(out)
    frames = []
    while True:
        fr, buf = read_frame_from_stream(buf)
        if fr is None:
            break
        frames.append(fr)
    assert len(frames) == 2, len(frames)
    assert frames[0]["msg_type"] == MSG_HANDSHAKE_RSP
    assert frames[0]["payload"] == hs_enc, "HandshakeRsp 不应被改"
    # 解改写后的 RespSRSAddr
    cli = SRSCrypto(key=session_key)
    cli.reset_cfb()
    info = parse_resp_srs_addr(cli.decrypt_payload(frames[1]["payload"]))
    assert info["szIP"] == ecs_ip, info
    print(f"[OK] 流式改写器: HandshakeRsp 学密钥 + RespSRSAddr 改写 szIP={info['szIP']}")
    print("[PASS] HandshakeRsp→RespSRSAddr 流式改写单元测试通过")


def _selftest_game_s2c_decrypt() -> None:
    """单元测试：GameS2CDecryptor 解系统帧，但 0x2bc0 保持明文透传。"""
    session_key = bytes.fromhex("aabbccddeeff00112233445566778899")

    # 服务器：HandshakeRsp(默认密钥, fresh-IV) payload=keylen(16)+key
    srv_default = SRSCrypto(key=SRS_DEFAULT_KEY)
    hs_plain = bytes([len(session_key)]) + session_key
    srv_default.reset_cfb()
    hs_enc = srv_default.encrypt_payload(hs_plain)
    hs_frame = pack_frame(MSG_HANDSHAKE_RSP, hs_enc)

    # 服务器：系统帧仍然加密（例如 0x0006），0x2bc0 游戏帧保持明文 payload。
    srv_sess = SRSCrypto(key=session_key)
    sys_plain = b"LOLLAPALOOZA\x00demo"
    srv_sess.reset_cfb()
    sys_enc = srv_sess.encrypt_payload(sys_plain)
    sys_frame = pack_frame(0x0006, sys_enc)

    game_plain = struct.pack("<HH", 0x0216, 5) + bytes([1, 2, 3, 4, 5])
    game_frame = pack_frame(0x2BC0, game_plain)

    # 解密器：分两次喂（验证粘包/拆包缓冲）
    dec = GameS2CDecryptor()
    stream = hs_frame + sys_frame + game_frame
    out = dec.feed(stream[:10]) + dec.feed(stream[10:])
    assert dec._session_key_learned, "未从 HandshakeRsp 学到会话密钥"

    # 解析输出：HandshakeRsp 原样 + 系统帧已解密 + 0x2bc0 原样透传
    buf = bytearray(out)
    frames = []
    while True:
        fr, buf = read_frame_from_stream(buf)
        if fr is None:
            break
        frames.append(fr)
    assert len(frames) == 3, len(frames)
    assert frames[0]["msg_type"] == MSG_HANDSHAKE_RSP
    assert frames[0]["payload"] == hs_enc, "HandshakeRsp 不应被改"
    assert frames[1]["msg_type"] == 0x0006
    assert frames[1]["payload"] == sys_plain, f"0x0006 payload 未正确解密: got {frames[1]['payload'].hex()}, want {sys_plain.hex()}"
    assert frames[2]["msg_type"] == 0x2BC0
    assert frames[2]["payload"] == game_plain, f"0x2bc0 payload 不应再被解密: got {frames[2]['payload'].hex()}, want {game_plain.hex()}"
    print(f"[OK] GameS2CDecryptor: HandshakeRsp 学密钥 + 0x0006 解密 + 0x2bc0 明文透传")
    print("[PASS] GameS2CDecryptor 单元测试通过")


def _selftest_game_tap(pcap_path: str = None) -> None:
    """集成自测：用仓库 pcap 喂 0x2bc0 被动解码，断言 hand_trusted。"""
    import os
    from stable.protocol import PcapParser

    if pcap_path is None:
        for cand in ("data/phone_srs.pcap", "data/phone_full.pcap"):
            if os.path.exists(cand):
                pcap_path = cand
                break
    assert pcap_path and os.path.exists(pcap_path), "找不到测试 pcap"

    tap = GameTapDecoder(state_store=None, local_player=1, server_port=7777)
    parser = PcapParser()
    hand_raw_seen = 0
    with open(pcap_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            for pkt in parser.feed(chunk):
                # 统计 0x2bc0 hand_raw 解码
                for msg in tap._proto.process_packet(pkt):
                    g = msg.game or {}
                    if g.get("hand_raw"):
                        hand_raw_seen += 1
                    tap._tracker.apply(msg)
    assert tap.hand_trusted, "未达到 hand_trusted"
    assert hand_raw_seen > 0, "未解出 0x2bc0 hand_raw"
    snap = tap.snapshot()
    print(f"[OK] pcap={pcap_path}: hand_trusted={tap.hand_trusted} "
          f"hand_raw帧={hand_raw_seen} phase={snap.get('phase')}")
    print("[PASS] 7777 旁路 0x2bc0 被动解码自测通过")


def _selftest() -> None:
    print("=== tcp_proxy 离线自测 ===")
    _selftest_resp_srs_addr()
    print()
    _selftest_handshake_key_learn()
    print()
    _selftest_game_s2c_decrypt()
    print()
    _selftest_game_tap()
    print("\n[ALL PASS] tcp_proxy 离线自测全部通过")


# ─── ECS 部署入口 ────────────────────────────────────────────────────────────

def _make_presence_reporter(presence_url: str, api_token: str):
    """Build a presence callback that posts lobby/game identity events to /presence."""
    import requests

    def _pending_user_id(host: str, listen_port: int) -> str:
        host = (host or "unknown").replace(":", "_")
        return f"__pending__:{host}:{listen_port}"

    def _report(info: dict) -> None:
        user_id = info.get("user_id", "")
        if not user_id:
            if info.get("provisional"):
                user_id = _pending_user_id(
                    info.get("source_host", ""),
                    int(info.get("listen_port", 0) or 0),
                )
            else:
                sid = info.get("sessionid", b"")
                if not sid:
                    return
                user_id = sid.hex() if isinstance(sid, (bytes, bytearray)) else str(sid)
        name = info.get("nickname", "") or info.get("name", "") or ""
        provisional = bool(info.get("provisional"))
        source_host = info.get("source_host", "") or ""
        try:
            requests.post(
                presence_url,
                json={
                    "api_token": api_token,
                    "user_id": user_id,
                    "name": name,
                    "provisional": provisional,
                    "source_host": source_host,
                },
                timeout=3,
            )
            logger.info("[presence] report online: user=%s name=%s provisional=%s", user_id[:12], name, provisional)
        except Exception as e:
            logger.debug("[presence] report failed: %s", e)

    return _report



def _make_lobby_connect_reporter(presence_reporter):
    """Lobby connect callback: create a short-lived provisional online user."""

    def _report(listen_port: int, addr) -> None:
        host = addr[0] if addr else "unknown"
        logger.info(
            "[lobby] new connection: %s:%d (waiting for PlayerData to resolve identity)",
            host,
            listen_port,
        )
        if presence_reporter is not None:
            presence_reporter({
                "provisional": True,
                "source_host": host,
                "listen_port": listen_port,
                "name": f"connecting {host}",
            })

    return _report


def run_proxies(ecs_ip: str = "8.136.32.137",
                listen_host: str = "0.0.0.0",
                real_lobby_ip: str = REAL_LOBBY_IP,
                real_game_ip: str = REAL_GAME_IP,
                lobby_ports: tuple[int, ...] = DEFAULT_LOBBY_PORTS,
                game_port: int = REAL_GAME_PORT,
                relay_push_url: str | None = None,
                api_token: str = "",
                on_player_data=None,
                on_lobby_connect=None):
    """启动大厅代理 + 游服代理（ECS 常驻）。

    核心方案：RespSRSAddr 只改 szIP→ECS，保留原始 sPort。
    当 RespSRSAddr 改写后，DynamicGameProxyManager 在 ECS:orig_port
    按需起 TcpProxy 转发到真服 orig_ip:orig_port。
    手机连 ECS:5700~5723 等端口，代理精确转发到对应真服。

    安全组需放行 5700-5799 端口范围。
    """
    proxies = []

    # 动态游服代理管理器
    game_proxy_manager = DynamicGameProxyManager(
        listen_host=listen_host,
        relay_push_url=relay_push_url,
        api_token=api_token,
        on_player_data=on_player_data,
    )

    # 大厅代理：listen=listen_host(0.0.0.0)，RespSRSAddr 改写 szIP→ECS
    # 不改 sPort——保留原始端口，手机连 ECS:orig_port
    for lp in lobby_ports:
        p = build_lobby_proxy(listen_host, lp, ecs_ip, real_lobby_ip,
                              lobby_ports=lobby_ports,
                              game_proxy_manager=game_proxy_manager,
                              rewrite_port=None,
                              on_player_data=on_player_data,
                              relay_push_url=relay_push_url,
                              api_token=api_token,
                              on_connect=on_lobby_connect)
        p.start()
        proxies.append(p)
        logger.info("[main] lobby proxy %s:%d -> %s:%d (RespSRSAddr -> %s:orig_port)",
                    listen_host, lp, real_lobby_ip, lp, ecs_ip)

    # 固定 7777 游服代理（向后兼容）
    gp = build_game_proxy(listen_host, game_port, real_game_ip,
                          relay_push_url=relay_push_url, api_token=api_token,
                          on_player_data=on_player_data,
                          diag_tag="fixed_7777_compat",
                          game_proxy_manager=game_proxy_manager)
    gp.start()
    proxies.append(gp)
    # 注册到 game_proxy_manager 避免重复创建
    game_proxy_manager._proxies[game_port] = gp
    logger.info("[main] game proxy  %s:%d -> %s:%d (push_url=%s)",
                listen_host, game_port, real_game_ip, game_port, relay_push_url)

    # 金币局游服固定代理：NetConf 把 _50[5067]/[5167] 改写成 ECS:5767/5768，
    # 这里在对应端口起代理转发回原金币真服 7777（带解密+0x2bc0 解码+relay push）。
    # 金币牌局 groupId=5067(正式)/5167(DEBUG)，走 _50 直连，不经 RespSRSAddr，故必须固定代理。
    from remote.noconfig.hijack.netconf_patch import SRS50_REMAP
    for gid, (real_host, real_port, listen_port) in SRS50_REMAP.items():
        try:
            sp = build_game_proxy(listen_host, listen_port, real_host,
                                  relay_push_url=relay_push_url, api_token=api_token,
                                  upstream_port=real_port, on_player_data=on_player_data,
                                  diag_tag=f"srs50_gid={gid}",
                                  game_proxy_manager=game_proxy_manager)
            sp.start()
            proxies.append(sp)
            game_proxy_manager._proxies[listen_port] = sp
            logger.info("[main] SRS50 gold game proxy %s:%d -> %s:%d (groupId=%d, push_url=%s)",
                        listen_host, listen_port, real_host, real_port, gid, relay_push_url)
        except OSError as e:
            logger.error("[main] SRS50 gold proxy listen :%d failed: %s", listen_port, e)

    return proxies, game_proxy_manager


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="ECS 双代理 — 大厅透传+RespSRSAddr改写 + 游服透传+0x2bc0旁路解码",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tcp_proxy.py --selftest
  python tcp_proxy.py --ecs-ip 0.0.0.0 --relay-push http://127.0.0.1:8002/push
  python tcp_proxy.py --ecs-ip 0.0.0.0 --no-push   # 不推 relay，仅解码到日志
        """)
    ap.add_argument("--selftest", action="store_true", help="跑离线自测后退出")
    ap.add_argument("--ecs-ip", default="8.136.32.137",
                    help="RespSRSAddr 改写目标=ECS 公网 IP（手机据此连 ECS 游服 7777）")
    ap.add_argument("--listen-host", default="0.0.0.0",
                    help="代理监听地址（默认 0.0.0.0 绑所有网卡）")
    ap.add_argument("--real-lobby-ip", default=REAL_LOBBY_IP, help="真大厅 IP")
    ap.add_argument("--real-game-ip", default=REAL_GAME_IP, help="真游服 IP")
    ap.add_argument("--lobby-ports", default=",".join(str(p) for p in DEFAULT_LOBBY_PORTS),
                    help="大厅端口列表，逗号分隔")
    ap.add_argument("--game-port", type=int, default=REAL_GAME_PORT, help="游服端口")
    ap.add_argument("--relay-push", default="http://127.0.0.1:8002/push",
                    help="noconfig relay /push 地址（空则不推）")
    ap.add_argument("--no-push", action="store_true", help="不推 relay，仅解码到日志")
    ap.add_argument("--api-token", default="", help="relay push 鉴权 token")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.selftest:
        logging.basicConfig(level=logging.WARNING)
        _selftest()
        return

    lobby_ports = tuple(int(x) for x in args.lobby_ports.split(","))
    push_url = None if args.no_push else (args.relay_push or None)

    # presence 上报器：从 --relay-push 推导 /presence 地址，PlayerData→标记用户在线
    presence_reporter = None
    if push_url:
        presence_url = push_url.rsplit("/push", 1)[0] + "/presence"
        presence_reporter = _make_presence_reporter(presence_url, args.api_token)
    lobby_connect_reporter = _make_lobby_connect_reporter(presence_reporter)

    proxies, game_proxy_manager = run_proxies(
        ecs_ip=args.ecs_ip,
        listen_host=args.listen_host,
        real_lobby_ip=args.real_lobby_ip,
        real_game_ip=args.real_game_ip,
        lobby_ports=lobby_ports,
        game_port=args.game_port,
        relay_push_url=push_url,
        api_token=args.api_token,
        on_player_data=presence_reporter,
        on_lobby_connect=lobby_connect_reporter,
    )

    logger.info("=" * 50)
    logger.info("ECS 代理已启动，手机经改过的 NetConf 连入即可")
    logger.info("大厅代理: %s", ", ".join(f":{p}" for p in lobby_ports))
    logger.info("游服代理(固定): :%d", args.game_port)
    logger.info("动态游服代理: 按需创建 (RespSRSAddr 改写时自动启动)")
    logger.info("Relay push: %s", push_url or "(disabled)")
    logger.info("=" * 50)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        logger.info("正在停止...")
        for p in proxies:
            p.stop()


if __name__ == "__main__":
    main()
