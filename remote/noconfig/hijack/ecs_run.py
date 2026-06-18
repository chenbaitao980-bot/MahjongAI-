"""ecs_run.py — ECS 代理独立进程启动器（轻量版，不导入 noconfig/app.py）。

部署到 ECS，与现有 mahjong-relay-noconfig(:8002) 并列运行。
解出的手牌通过 HTTP POST 推送到 localhost:8002/push。

用法：
  python remote/noconfig/hijack/ecs_run.py
  python remote/noconfig/hijack/ecs_run.py --relay-url http://localhost:8002 --ecs-ip 8.136.37.136

环境变量：
  ECS_IP        代理改写用的 ECS IP（默认 8.136.37.136）
  RELAY_URL     手牌快照推送目标（默认 http://localhost:8002）
  API_TOKEN     relay api_token（可选，默认空）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import urllib.request
import json

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from remote.noconfig.hijack.tcp_proxy import (
    DEFAULT_LOBBY_PORTS,
    REAL_GAME_IP,
    REAL_GAME_PORT,
    REAL_LOBBY_IP,
    build_lobby_proxy,
    DynamicGameProxyManager,
    GameS2CDecryptor,
    GameTapDecoder,
    TcpProxy,
)

logger = logging.getLogger("remote.noconfig.hijack.ecs_run")

DEFAULT_ECS_IP = os.environ.get("ECS_IP", "8.136.37.136")
DEFAULT_RELAY_URL = os.environ.get("RELAY_URL", "http://localhost:8002")
DEFAULT_API_TOKEN = os.environ.get("API_TOKEN", "")


class HttpStateStore:
    """用 HTTP POST /push 代替 StateStore.on_game_event，无需 import noconfig app。"""

    def __init__(self, relay_url: str, api_token: str = ""):
        self._push_url = relay_url.rstrip("/") + "/push"
        self._api_token = api_token
        self._last_push = 0.0
        self._min_interval = 0.2  # 最小推送间隔（秒），避免频繁 POST

    def on_game_event(self, snapshot: dict) -> None:
        now = time.monotonic()
        if now - self._last_push < self._min_interval:
            return
        self._last_push = now
        try:
            body = json.dumps({
                "snapshot": snapshot,
                "api_token": self._api_token,
            }).encode("utf-8")
            req = urllib.request.Request(
                self._push_url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                status = resp.status
            if status != 200:
                logger.warning("[relay_push] HTTP %d", status)
            else:
                hand = snapshot.get("hand", [])
                logger.debug("[relay_push] pushed hand=%s phase=%s",
                             hand, snapshot.get("phase"))
        except Exception as e:
            logger.warning("[relay_push] push failed: %s", e)


def build_game_proxy_http(listen_host: str, listen_port: int,
                          relay_url: str, api_token: str = "",
                          real_game_ip: str = REAL_GAME_IP,
                          local_player: int = 1) -> TcpProxy:
    """游服代理工厂（HTTP 推送版）：SRS 解密 + 0x2bc0 旁路 → POST /push。"""
    store = HttpStateStore(relay_url, api_token)
    tap = GameTapDecoder(state_store=store, local_player=local_player,
                         server_port=listen_port)
    decryptor = GameS2CDecryptor()

    def _on_bytes(direction: str, data: bytes) -> None:
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
            logger.debug("game tap error: %s", exc)

    return TcpProxy(listen_host, listen_port, real_game_ip, listen_port,
                    on_bytes=_on_bytes)


def run(ecs_ip: str = DEFAULT_ECS_IP,
        relay_url: str = DEFAULT_RELAY_URL,
        api_token: str = DEFAULT_API_TOKEN,
        listen_host: str = "0.0.0.0") -> None:

    # 动态游服代理管理器（处理 RespSRSAddr 下发的动态端口）
    game_proxy_manager = DynamicGameProxyManager(
        listen_host=listen_host,
        relay_push_url=relay_url,
        api_token=api_token,
    )

    proxies = []
    for port in DEFAULT_LOBBY_PORTS:
        p = build_lobby_proxy(listen_host, port, ecs_ip, real_lobby_ip=REAL_LOBBY_IP,
                              game_proxy_manager=game_proxy_manager)
        p.start()
        proxies.append(p)

    # 固定 7777 游服代理（向后兼容）
    gp = build_game_proxy_http(listen_host, REAL_GAME_PORT, relay_url, api_token,
                                real_game_ip=REAL_GAME_IP)
    gp.start()
    proxies.append(gp)
    # 注册到管理器避免重复创建
    game_proxy_manager._proxies[REAL_GAME_PORT] = gp

    logger.info("=" * 55)
    logger.info("  ECS 代理已就绪 (ecs_run.py):")
    for port in DEFAULT_LOBBY_PORTS:
        logger.info("    大厅 %d → %s:%d  (RespSRSAddr→%s)", port, REAL_LOBBY_IP, port, ecs_ip)
    logger.info("    游服 %d → %s:%d  (0x2bc0→%s/push)",
                REAL_GAME_PORT, REAL_GAME_IP, REAL_GAME_PORT, relay_url)
    logger.info("    动态端口: 5700-5799 (RespSRSAddr 触发)")
    logger.info("=" * 55)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        logger.info("停止中...")
        for p in proxies:
            p.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="ECS 代理独立进程（大厅改写 + 7777 旁路 → relay）")
    ap.add_argument("--ecs-ip", default=DEFAULT_ECS_IP)
    ap.add_argument("--relay-url", default=DEFAULT_RELAY_URL,
                    help="noconfig relay 地址（默认 http://localhost:8002）")
    ap.add_argument("--api-token", default=DEFAULT_API_TOKEN)
    ap.add_argument("--listen-host", default="0.0.0.0")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run(ecs_ip=args.ecs_ip, relay_url=args.relay_url,
        api_token=args.api_token, listen_host=args.listen_host)


if __name__ == "__main__":
    main()
