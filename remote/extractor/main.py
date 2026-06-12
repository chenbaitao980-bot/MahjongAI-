"""
main.py — extractor 入口

用法:
  python main.py [--mode npcap|tcpdump] [--interface IFACE] [--config CONFIG]

功能:
  1. 被动嗅探经过本机/路由器的游戏 TCP 流量（port 7777）
  2. 提取 handshake_blob + auth_token_12b，POST /register 到 relay
  3. 持续监听，每次状态变化 POST /push 到 relay
"""
import argparse
import logging
import os
import sys
import time

# 插入项目根目录到 sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml

from stable.protocol import MJProtocol
from stable.tracker import PacketStateTracker
from stable.mapping import MappingStore

from remote.extractor.capture import create_capture
from remote.extractor.token_extractor import TokenExtractor, SRSSessionExtractor
from remote.extractor.uploader import register, push

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
)

# 额外挂文件日志 handler，便于事后取证（console 是独立黑窗口，存不下）
_LOG_FILE = os.path.join(os.path.dirname(__file__), "extractor.log")


def _attach_file_handler():
    root = logging.getLogger()
    # 避免重复添加（模块可能被多次导入）
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and \
                getattr(h, "baseFilename", None) == os.path.abspath(_LOG_FILE):
            return
    file_handler = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)


_attach_file_handler()

_LOGGER = logging.getLogger("remote.extractor")
# 双向控制帧取证日志（propagate 到 root，自动进 extractor.log）
_FORENSIC = logging.getLogger("remote.extractor.frames")

# 取证日志排除的高频帧：游戏事件主帧 + keepalive 空帧
_FORENSIC_SKIP_MSG_TYPES = frozenset((0x2BC0, 0x0002))


def load_config(path):
    """加载 YAML 配置文件"""
    if not os.path.isfile(path):
        _LOGGER.error("配置文件不存在: %s", path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class ExtractorApp:
    """extractor 主应用"""

    def __init__(self, cfg, mode=None, interface="any"):
        self.relay_url = cfg.get("relay_url", "http://localhost:8000")
        self.api_token = cfg.get("api_token", "")
        self.game_port = int(cfg.get("game_port", 7777))

        # 抓包适配器
        self._capture = create_capture(mode=mode, port=self.game_port, interface=interface)

        # 协议解析
        self._proto = MJProtocol(server_port=self.game_port)

        # 状态追踪
        self._mapping = MappingStore()
        self._tracker = PacketStateTracker(mapping_store=self._mapping)

        # 旁观帧取证开关（默认开启全量帧头取证，用于逆 sub_type/extra ↔ processid 映射）
        self._capture_all_heads = bool(cfg.get("spectator_forensic_all_heads", True))

        # token 提取 + 旁观帧取证 + SRS sessionid 提取
        self._extractor = TokenExtractor(
            on_registered=self._on_token_registered,
            on_room_info=self._on_room_info,
            capture_all_heads=self._capture_all_heads,
        )
        self._srs_extractor = SRSSessionExtractor(
            on_sessionid=self._on_srs_sessionid
        )

        # 凭证提取提醒（每 120 秒最多提醒一次）
        self._credential_warn_interval = 120.0
        self._last_credential_warn = 0.0
        self._first_packet_ts = None  # 收到第一个包的时间戳

    def _on_token_registered(self, handshake_blob, auth_token_12b):
        """两个凭证都提取到时的回调"""
        _LOGGER.info("提取到认证凭证，正在注册到 relay...")
        srs_sid = self._srs_extractor.sessionid
        ok = register(self.relay_url, self.api_token, handshake_blob, auth_token_12b, srs_sid)
        if not ok:
            _LOGGER.warning("注册失败，将在下次启动时重试")
        elif srs_sid:
            _LOGGER.info("SRS sessionid 也已一并注册")

    def _on_srs_sessionid(self, sessionid):
        """SRS sessionid 提取到时的回调"""
        _LOGGER.info("SRS sessionid 已提取: %s", sessionid.hex())
        # 如果 MJ 凭证也已就绪，立即注册
        if self._extractor.is_complete:
            ok = register(self.relay_url, self.api_token,
                         self._extractor.handshake_blob,
                         self._extractor.auth_token_12b,
                         sessionid)
            if ok:
                _LOGGER.info("凭证（含 SRS sessionid）已注册到 relay")

    def _on_room_info(self, room_id, game_id):
        """房间信息提取到时的回调"""
        _LOGGER.info("提取到房间信息，正在上报 roomid=%d, gameid=%d...", room_id, game_id)
        try:
            from remote.extractor.uploader import register_room
            ok = register_room(self.relay_url, self.api_token, room_id, game_id)
            if ok:
                _LOGGER.info("房间信息已上报 relay (roomid=%d, gameid=%d)", room_id, game_id)
            else:
                _LOGGER.warning("房间信息上报失败 (roomid=%d, gameid=%d)", room_id, game_id)
        except Exception as exc:
            _LOGGER.error("上报房间信息异常: %s", exc)

    def _on_packet(self, pkt):
        """每收到一个 TCP 包的回调"""
        try:
            messages = self._proto.process_packet(pkt)
        except Exception as exc:
            _LOGGER.debug("协议解析异常: %s", exc)
            return

        for msg in messages:
            # 双向控制帧取证（排除高频游戏数据/keepalive 帧）
            if msg.msg_type not in _FORENSIC_SKIP_MSG_TYPES:
                payload = bytes.fromhex(msg.raw_hex)[12:] if msg.raw_hex else b""
                seen = len(payload)
                trunc = " [TRUNCATED]" if seen < msg.pay_len else ""
                _FORENSIC.info(
                    "dir=%s msg_type=0x%04x sub_type=0x%04x pay_len=%d seen=%d payload=%s%s",
                    msg.direction, msg.msg_type, msg.sub_type, msg.pay_len,
                    seen, payload.hex(), trunc,
                )

            # 记录首包时间
            if self._first_packet_ts is None:
                self._first_packet_ts = time.time()

            # 向 token 提取器喂消息
            self._extractor.feed(msg)
            # 同时向 SRS session 提取器喂消息
            self._srs_extractor.feed(msg)

            # 凭证缺失提醒：首包后超过 60 秒仍无凭证，每 120 秒提醒一次
            if not self._extractor.is_complete and self._first_packet_ts is not None:
                now = time.time()
                if (now - self._first_packet_ts > 60 and
                        now - self._last_credential_warn > self._credential_warn_interval):
                    self._last_credential_warn = now
                    if self._extractor.handshake_blob is not None:
                        _LOGGER.warning(
                            "已提取 handshake_blob (%d bytes)，但未捕获到 auth_token_12b！"
                            "游戏使用了本地缓存的 token 走 reauth，未发送 0x0006 认证包。"
                            "需要清除游戏 App 数据后重新登录（Android: 设置→应用→清除数据）。"
                            "此操作只需一次，之后 relay 永久持有凭证。",
                            len(self._extractor.handshake_blob),
                        )
                    else:
                        _LOGGER.warning(
                            "尚未提取到任何认证凭证（handshake_blob/auth_token）。"
                            "请确认手机已连 PC 热点，且游戏正在运行。"
                            "如果游戏已登录，请清除游戏 App 数据后重新登录。"
                        )

            # 向状态追踪器喂消息，检查是否有状态变化
            changed = self._tracker.apply(msg)
            if changed:
                snapshot = self._tracker.snapshot()
                ok = push(self.relay_url, self.api_token, snapshot)
                if not ok:
                    _LOGGER.debug("推送 snapshot 失败")

    def run(self):
        """阻塞运行主循环"""
        _LOGGER.info("extractor 启动，监听 port %d → relay %s", self.game_port, self.relay_url)
        _LOGGER.info(
            "提示：如需提取认证凭证（断热点后 relay 自动接管），需要在 extractor 运行期间，"
            "清除游戏 App 数据后重新登录（Android: 设置→应用→清除数据；iOS: 删除重装）。"
            "仅杀进程或断线重连不会触发 0x0006 认证包——游戏用本地缓存的 token 走 reauth。"
            "此操作只需一次，凭证持久化到 relay 后即可断热点自动接管。"
        )
        _LOGGER.info("旁观帧取证落盘: %s", self._extractor.forensic_path)
        try:
            self._capture.run(self._on_packet)
        except KeyboardInterrupt:
            _LOGGER.info("用户中断，退出")
        finally:
            self._capture.stop()
            self._extractor.close()


def main():
    parser = argparse.ArgumentParser(description="MahjongAI 游戏流量 extractor")
    parser.add_argument(
        "--mode",
        choices=["npcap", "tcpdump"],
        default=None,
        help="抓包模式（默认自动检测：Windows=npcap，Linux=tcpdump）",
    )
    parser.add_argument(
        "--interface",
        default="any",
        help="tcpdump 监听的网卡接口（Linux 模式，默认 any）",
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.yaml"),
        help="配置文件路径（默认 ./config.yaml）",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    app = ExtractorApp(cfg, mode=args.mode, interface=args.interface)
    app.run()


if __name__ == "__main__":
    main()
