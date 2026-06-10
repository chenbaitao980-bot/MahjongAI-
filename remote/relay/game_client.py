"""
game_client.py — GameClient

asyncio TCP 客户端，主动连接游戏服务器，完成握手和认证，持续接收数据。
用于 extractor 离线时（场景B）独立获取游戏状态。

握手序列：
  1. 连接 TCP
  2. 发 0x000F x2（固定 payload）
  3. 发 0x0001 handshake_blob
  4. 进入收发循环：
     - 收到 0x0002 → 立即回复 0x0002（keepalive）
     - 启动后立即发一次 0x0003，此后每 60 秒发一次
     - 收到需要认证时发 0x0006（随机3字节前缀 + 0xf9 + auth_token_12b）
     - 所有 S->C 包 → SocketMJDecoder → PacketStateTracker → state_store.on_game_event()
  5. 断线重连：指数退避 5→10→20→...→60 秒（上限）
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stable.tracker import PacketStateTracker
from stable.mapping import MappingStore

from decoder import SocketMJDecoder, build_frame

_LOGGER = logging.getLogger("remote.relay.game_client")

# 固定初始化 payload（从 pcap 样本提取）
_INIT_0F_1 = bytes.fromhex("ceee43931edbc993c0b08b443d2e4014")
_INIT_0F_2 = bytes.fromhex("f1ee43931edbc993c0b08b443d2e4014")

# 0x0003 心跳 payload（固定）
_HEARTBEAT_REQ_PAYLOAD = bytes.fromhex("f1ef6b65532a4c97d075bc4c393680f925")

# keepalive 0x0002 帧（payload 为空）
_KEEPALIVE_FRAME = build_frame(0x0002, b"", sub_type=0x0000, extra=b"\x00\x00\x00\x00")

# 心跳发送间隔（秒）
_HEARTBEAT_INTERVAL = 60.0


class GameClient:
    """
    异步 TCP 客户端，主动连接游戏服务器。

    通过 state_store 将解析出的游戏状态传递给 API 层。
    """

    def __init__(self, server_ip, server_port, handshake_blob, auth_token_12b, state_store):
        """
        server_ip:       str，游戏服务器 IP
        server_port:     int，游戏服务器端口（通常 7777）
        handshake_blob:  bytes，从 extractor 注册获得的登录 blob
        auth_token_12b:  bytes，12字节用户 token
        state_store:     StateStore 实例
        """
        self.server_ip = server_ip
        self.server_port = int(server_port)
        self.handshake_blob = handshake_blob
        self.auth_token_12b = auth_token_12b
        self.state_store = state_store

        self._running = False
        self._task = None

    def start(self, loop=None):
        """在 asyncio 事件循环中启动客户端（后台任务）"""
        self._running = True
        loop = loop or asyncio.get_event_loop()
        self._task = loop.create_task(self._run_with_retry())

    def stop(self):
        """停止客户端"""
        self._running = False
        if self._task is not None:
            self._task.cancel()

    async def _run_with_retry(self):
        """指数退避重连循环"""
        delay = 5.0
        max_delay = 60.0
        consecutive_failures = 0
        while self._running:
            try:
                await self._run_once()
                delay = 5.0  # 正常断开后重置退避
                consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_failures += 1
                if consecutive_failures >= 10:
                    _LOGGER.error(
                        "连续 %d 次连接失败，凭证可能已过期。"
                        "请等待 extractor 推送新凭证或重启 relay 重新注册。",
                        consecutive_failures,
                    )
                _LOGGER.warning("连接断开: %s，%g 秒后重连", exc, delay)
            if not self._running:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _run_once(self):
        """单次连接生命周期"""
        _LOGGER.info("连接游戏服务器 %s:%d", self.server_ip, self.server_port)
        reader, writer = await asyncio.open_connection(self.server_ip, self.server_port)

        # 初始化协议解码器和状态追踪
        decoder = SocketMJDecoder()
        mapping = MappingStore()
        tracker = PacketStateTracker(mapping_store=mapping)

        try:
            # 阶段1：发送初始化包 0x000F x2
            writer.write(build_frame(0x000F, _INIT_0F_1, sub_type=0x0054, extra=b"\x00\x00\x00\x00"))
            writer.write(build_frame(0x000F, _INIT_0F_2, sub_type=0x0054, extra=b"\x38\x56\x4c\x05"))
            await writer.drain()

            # 阶段2：发送 handshake
            writer.write(build_frame(0x0001, self.handshake_blob, sub_type=0x047b, extra=b"\x38\x56\x4c\x05"))
            await writer.drain()

            # 阶段3：立即发一次心跳
            writer.write(build_frame(0x0003, _HEARTBEAT_REQ_PAYLOAD, sub_type=0x047b, extra=b"\x38\x56\x4c\x05"))
            await writer.drain()

            # 认证标志：只发一次 0x0006
            auth_sent = False
            last_heartbeat = time.monotonic()

            # 主收包循环
            while self._running:
                # 定时发心跳
                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    writer.write(build_frame(0x0003, _HEARTBEAT_REQ_PAYLOAD,
                                             sub_type=0x047b, extra=b"\x38\x56\x4c\x05"))
                    await writer.drain()
                    last_heartbeat = now

                # 读数据（超时 1 秒以便检查心跳定时器）
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    _LOGGER.info("服务器关闭连接")
                    break

                msgs = decoder.feed(chunk, direction="S->C")
                for msg in msgs:
                    # 收到 keepalive → 立即回复
                    if msg.msg_type == 0x0002:
                        writer.write(_KEEPALIVE_FRAME)
                        # 不 await drain，批量刷出
                        continue

                    # 收到服务端 0x0006（认证触发信号）→ 发送认证令牌
                    if msg.msg_type == 0x0006 and msg.direction == "S->C" and not auth_sent:
                        await self._send_auth(writer)
                        auth_sent = True
                        continue

                    # 其他 S->C 包喂给 tracker
                    changed = tracker.apply(msg)
                    if changed:
                        snapshot = tracker.snapshot()
                        self.state_store.on_game_event(snapshot)

                # 批量刷出 keepalive 回复
                try:
                    await writer.drain()
                except Exception:
                    break

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            _LOGGER.info("与游戏服务器连接已关闭")

    async def _send_auth(self, writer):
        """发送认证令牌 0x0006（随机前缀 + auth_token_12b）"""
        import os as _os
        prefix = _os.urandom(3) + b"\xf9"
        payload = prefix + self.auth_token_12b
        writer.write(build_frame(0x0006, payload, sub_type=0x0093, extra=b"\x00\x00\x00\x00"))
        await writer.drain()
        _LOGGER.info("已发送认证令牌")
