"""
token_extractor.py — 从协议流中提取认证凭证

监听 C->S 方向的包：
- msg_type == 0x0001 → 提取 handshake_blob（payload 全部，只取第一个）
- msg_type == 0x0006 且 len(payload)==16 → 提取 auth_token_12b（payload[4:16]，只取第一个）
两个都提取到后，通过 on_registered 回调通知调用方
"""
import logging
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.protocol import MJProtocol, GAME_SERVER_PORT

_LOGGER = logging.getLogger("remote.extractor.token")


class TokenExtractor:
    """
    从 ProtocolMessage 流中提取 handshake_blob 和 auth_token_12b。

    用法：
        extractor = TokenExtractor(on_registered=my_callback)
        # 每收到一个协议消息：
        extractor.feed(message)
    """

    def __init__(self, on_registered=None):
        """
        on_registered: callable，签名 (handshake_blob: bytes, auth_token_12b: bytes) -> None
                       两个凭证都提取到后调用一次
        """
        self._handshake_blob = None   # bytes
        self._auth_token_12b = None   # bytes
        self._registered = False
        self._seen_init = False       # 是否已见过 C->S 0x000F（init 包）
        self._on_registered = on_registered

    @property
    def handshake_blob(self):
        return self._handshake_blob

    @property
    def auth_token_12b(self):
        return self._auth_token_12b

    @property
    def is_complete(self):
        """是否两个凭证都已提取"""
        return self._handshake_blob is not None and self._auth_token_12b is not None

    def feed(self, message):
        """
        处理一个 ProtocolMessage，尝试提取认证凭证。
        仅处理 C->S 方向的消息。
        """
        # 只处理 C->S
        if message.direction != "C->S":
            return

        # 取证日志：无条件记录 C->S 的 0x0001/0x0006/0x000F，
        # 即使已注册也继续打印（方便看后续还有没有更大的 0x0001 出现）
        if message.msg_type in (0x0001, 0x0006, 0x000F):
            _forensic_payload = bytes.fromhex(message.raw_hex)[12:] if message.raw_hex else b""
            _LOGGER.info(
                "msg_type=0x%04x sub_type=0x%04x pay_len=%d raw_payload_len=%d head16=%s",
                message.msg_type,
                message.sub_type,
                message.pay_len,
                len(_forensic_payload),
                _forensic_payload[:16].hex(),
            )

        # 标记：已见过 C->S 0x000F（init 包）
        if message.msg_type == 0x000F:
            self._seen_init = True

        # 已注册则不再重复提取
        if self._registered:
            return

        payload = bytes.fromhex(message.raw_hex)[12:] if message.raw_hex else b""
        # raw_hex 最多96字节，需要完整 payload
        # 从 pay_len 知道真实长度，这里只能用 raw_hex 截取的部分
        # 对于短帧（<=84字节 payload）raw_hex 足够
        pay_len = message.pay_len

        if (message.msg_type == 0x0001 and self._handshake_blob is None
                and (self._seen_init or message.sub_type == 0x047b)):
            # 提取 handshake_blob：必须是"已见过 C->S 0x000F 之后"出现的 0x0001
            # （或 sub_type==0x047b 无条件优先采纳），跳过 0x000F 之前的杂包
            if len(payload) >= pay_len:
                self._handshake_blob = payload[:pay_len]
            elif len(payload) > 0:
                # raw_hex 截断时取已有部分（最多84字节）
                self._handshake_blob = payload
            if self._handshake_blob:
                print("[TokenExtractor] 已提取 handshake_blob: {} bytes (sub_type=0x{:04x})".format(
                    len(self._handshake_blob), message.sub_type))

        elif message.msg_type == 0x0006 and self._auth_token_12b is None:
            # 提取 auth_token_12b：C->S 0x0006 payload 的 bytes 4-15（需要 payload 完整16字节）
            if pay_len == 16 and len(payload) >= 16:
                self._auth_token_12b = payload[4:16]
                print("[TokenExtractor] 已提取 auth_token_12b: {}".format(
                    self._auth_token_12b.hex()))

        # 检查是否两个都提取到了
        if self.is_complete and not self._registered:
            self._registered = True
            if self._on_registered is not None:
                self._on_registered(self._handshake_blob, self._auth_token_12b)
