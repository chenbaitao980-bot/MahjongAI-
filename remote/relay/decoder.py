"""
decoder.py — SocketMJDecoder

从 TCP socket 接收的字节流中增量解码 ProtocolMessage。
不依赖 pcap dict 格式，直接解析裸字节流。
复用 MJProtocol._decode_frame() 完成帧解码。
"""
from __future__ import annotations

import os
import struct
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.protocol import MJProtocol, HDR_LEN

# 帧构建：云端主动发包时使用
import struct as _struct


def build_frame(msg_type, payload, sub_type=0x047b, extra=b"\x38\x56\x4c\x05"):
    """
    构造游戏协议帧（C->S 方向）。

    msg_type: int，消息类型
    payload:  bytes，消息体
    sub_type: int，子类型（不同消息类型有固定值）
    extra:    bytes，帧头尾4字节
    返回: bytes，完整帧（12字节头 + payload）
    """
    hdr = bytes([0x01, 0x40])
    hdr += _struct.pack("<H", len(payload))
    hdr += _struct.pack("<H", msg_type)
    hdr += _struct.pack("<H", sub_type)
    extra_bytes = (extra + b"\x00" * 4)[:4]
    hdr += extra_bytes
    return hdr + payload


class SocketMJDecoder:
    """
    从 TCP socket 字节流增量解码，返回 ProtocolMessage 列表。

    使用方法：
        decoder = SocketMJDecoder()
        for data in socket_reader:
            msgs = decoder.feed(data, direction='S->C')
            for msg in msgs:
                tracker.apply(msg)
    """

    def __init__(self):
        self._buf = b""
        self._proto = MJProtocol(server_port=7777)

    def feed(self, data, direction="S->C"):
        """
        喂入新收到的字节，返回解码出的 ProtocolMessage 列表。

        data:      bytes
        direction: 'S->C' 或 'C->S'
        """
        self._buf += data
        messages = []
        while len(self._buf) >= HDR_LEN:
            # 检查帧头有效性
            if self._buf[1] not in (0x40, 0x80):
                # 跳过无效字节
                self._buf = self._buf[1:]
                continue
            pay_len = _struct.unpack("<H", self._buf[2:4])[0]
            total = HDR_LEN + pay_len
            if len(self._buf) < total:
                # 数据不足，等待更多数据
                break
            frame = self._buf[:total]
            self._buf = self._buf[total:]
            msg = self._proto._decode_frame(frame, direction, 0.0)
            if msg is not None:
                messages.append(msg)
        return messages

    def reset(self):
        """重置缓冲区（断线重连时使用）"""
        self._buf = b""
