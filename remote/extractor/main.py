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

from capture import create_capture
from token_extractor import TokenExtractor
from uploader import register, push

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

        # token 提取
        self._extractor = TokenExtractor(on_registered=self._on_token_registered)

    def _on_token_registered(self, handshake_blob, auth_token_12b):
        """两个凭证都提取到时的回调"""
        _LOGGER.info("提取到认证凭证，正在注册到 relay...")
        ok = register(self.relay_url, self.api_token, handshake_blob, auth_token_12b)
        if not ok:
            _LOGGER.warning("注册失败，将在下次启动时重试")

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

            # 向 token 提取器喂消息
            self._extractor.feed(msg)

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
        try:
            self._capture.run(self._on_packet)
        except KeyboardInterrupt:
            _LOGGER.info("用户中断，退出")
        finally:
            self._capture.stop()


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
