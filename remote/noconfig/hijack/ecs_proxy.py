"""ecs_proxy.py — ECS 运行期一键启动脚本。

部署到 ECS，与 noconfig relay(main.py) 同进程运行，共享 StateStore。

启动顺序：
  1. 初始化 StateStore（同 noconfig/app.py）
  2. 启动大厅代理 × 2（5748, 5749 → 47.96.101.155，S→C 改写 RespSRSAddr）
  3. 启动游服代理（7777 → 47.96.0.227，被动 0x2bc0 旁路 → StateStore）
  4. 启动 noconfig FastAPI relay（:8002，网页读牌）

用法：
  python remote/noconfig/hijack/ecs_proxy.py
  python remote/noconfig/hijack/ecs_proxy.py --ecs-ip 8.136.37.136 --relay-port 8002

环境变量（优先于命令行，便于 Docker/systemd）：
  ECS_IP          覆盖 --ecs-ip
  RELAY_PORT      覆盖 --relay-port
  RELAY_CONFIG    覆盖 --relay-config（noconfig config.yaml 路径）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
# ecs_proxy.py 位置: remote/noconfig/hijack/ecs_proxy.py → repo root 上 3 级
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_RELAY_DIR = os.path.join(_REPO_ROOT, "remote", "relay")
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)
_HERE = os.path.dirname(os.path.abspath(__file__))
_NOCONFIG_DIR = os.path.join(_HERE, "..")
if _NOCONFIG_DIR not in sys.path:
    sys.path.insert(0, _NOCONFIG_DIR)

from remote.noconfig.hijack.tcp_proxy import (
    DEFAULT_LOBBY_PORTS,
    REAL_GAME_IP,
    REAL_GAME_PORT,
    REAL_LOBBY_IP,
    DynamicGameProxyManager,
    build_game_proxy,
    build_lobby_proxy,
)

logger = logging.getLogger("remote.noconfig.hijack.ecs_proxy")

DEFAULT_ECS_IP = os.environ.get("ECS_IP", "8.136.37.136")
DEFAULT_RELAY_PORT = int(os.environ.get("RELAY_PORT", "8002"))
DEFAULT_RELAY_CONFIG = os.environ.get(
    "RELAY_CONFIG",
    os.path.join(_NOCONFIG_DIR, "config.yaml"),
)


def make_presence_reporter(relay_url: str, api_token: str):
    """构造 presence 回调：解出 PlayerData(sessionid+nickname) → POST /presence。

    按 srs_sessionid(hex) 作为 user_id，让"手机进游戏即在多用户页显示在线"。
    在代理的 S→C 线程里调用，requests 带短超时，避免阻塞数据泵。
    """
    import requests

    def _report(info: dict) -> None:
        numid = info.get("numid", 0)
        if not numid:
            return
        user_id = str(numid)
        name = info.get("nickname", "") or ""
        sid = info.get("sessionid", b"")
        srs_sid = sid.hex() if isinstance(sid, (bytes, bytearray)) else str(sid)
        try:
            requests.post(
                f"{relay_url}/presence",
                json={"api_token": api_token, "user_id": user_id, "name": name,
                      "srs_sessionid": srs_sid},
                timeout=3,
            )
            logger.info("[presence] 上报在线: user=%s name=%s", user_id, name)
        except Exception as e:
            logger.debug("[presence] 上报失败: %s", e)

    return _report


def start_proxies(ecs_ip: str, relay_push_url: str | None = None, api_token: str = "",
                  on_player_data=None, listen_host: str = "0.0.0.0") -> list:
    """启动大厅 × N + 动态游服代理管理器 + 静态 7777 兜底，返回已启动的 TcpProxy 列表。

    relay_push_url 不为 None 时，解码手牌 POST /push；on_player_data 不为 None 时，
    PlayerData 触发 /presence 上报（多用户在线）。
    """
    proxies = []
    # 动态游服代理：大厅 RespSRSAddr 改写后，按需在动态端口(5700+)起代理，带 push+presence
    game_mgr = DynamicGameProxyManager(listen_host=listen_host,
                                       relay_push_url=relay_push_url,
                                       api_token=api_token,
                                       on_player_data=on_player_data)
    for port in DEFAULT_LOBBY_PORTS:
        p = build_lobby_proxy(listen_host, port, ecs_ip,
                              real_lobby_ip=REAL_LOBBY_IP,
                              game_proxy_manager=game_mgr,
                              on_player_data=on_player_data)
        p.start()
        proxies.append(p)
        logger.info("大厅代理已启动: %s:%d -> %s:%d (RespSRSAddr改写→%s)",
                    listen_host, port, REAL_LOBBY_IP, port, ecs_ip)

    # 静态 7777 兜底（若牌局直接在 7777）
    gp = build_game_proxy(listen_host, REAL_GAME_PORT,
                          real_game_ip=REAL_GAME_IP,
                          relay_push_url=relay_push_url,
                          api_token=api_token,
                          on_player_data=on_player_data)
    gp.start()
    proxies.append(gp)
    logger.info("游服代理已启动: %s:%d -> %s:%d (0x2bc0旁路→push + PlayerData→presence)",
                listen_host, REAL_GAME_PORT, REAL_GAME_IP, REAL_GAME_PORT)
    return proxies


def run(ecs_ip: str = DEFAULT_ECS_IP,
        relay_port: int = DEFAULT_RELAY_PORT,
        relay_config: str = DEFAULT_RELAY_CONFIG,
        relay_host: str = "0.0.0.0") -> None:
    """完整启动：proxies + relay。"""
    import yaml

    # 1. 读 relay 配置
    cfg: dict = {}
    if os.path.isfile(relay_config):
        with open(relay_config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        logger.info("relay 配置: %s", relay_config)
    else:
        logger.warning("relay 配置文件不存在: %s（用默认配置）", relay_config)

    cfg["port"] = relay_port

    # 2. 初始化多用户 noconfig relay（app.configure 注入配置 + 预填 default 用户）
    from app import app as relay_app
    from app import configure as relay_configure
    relay_configure(cfg=cfg, cfg_path=relay_config)

    api_token = cfg.get("api_token", "")
    relay_push_url = f"http://127.0.0.1:{relay_port}"
    presence_reporter = make_presence_reporter(relay_push_url, api_token)

    # 3. 启动代理（大厅 + 动态游服 + 7777 兜底）：手牌→/push，PlayerData→/presence
    start_proxies(ecs_ip, relay_push_url=relay_push_url, api_token=api_token,
                  on_player_data=presence_reporter)

    # 4. 启动摘要
    logger.info("=" * 55)
    logger.info("  ECS 代理已就绪:")
    for port in DEFAULT_LOBBY_PORTS:
        logger.info("    大厅 %d → %s:%d  (RespSRSAddr→%s)", port, REAL_LOBBY_IP, port, ecs_ip)
    logger.info("    游服 %d → %s:%d  (0x2bc0旁路→relay)", REAL_GAME_PORT, REAL_GAME_IP, REAL_GAME_PORT)
    logger.info("  noconfig relay 启动: http://%s:%d", relay_host, relay_port)
    logger.info("=" * 55)

    # 5. 启动 relay FastAPI（阻塞，在主线程）
    logger.info("noconfig relay 启动: %s:%d", relay_host, relay_port)
    import uvicorn
    uvicorn.run(relay_app, host=relay_host, port=relay_port)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ECS 运行期一键启动：大厅代理 + 游服代理 + noconfig relay"
    )
    ap.add_argument("--ecs-ip", default=DEFAULT_ECS_IP,
                    help="ECS 公网 IP（写进 NetConf 的地址，默认 %(default)s）")
    ap.add_argument("--relay-port", type=int, default=DEFAULT_RELAY_PORT,
                    help="noconfig relay 端口（默认 %(default)s）")
    ap.add_argument("--relay-config", default=DEFAULT_RELAY_CONFIG,
                    help="noconfig config.yaml 路径")
    ap.add_argument("--relay-host", default="0.0.0.0")
    ap.add_argument("--proxy-host", default="0.0.0.0")
    ap.add_argument("--proxies-only", action="store_true",
                    help="只起代理，不起 relay（relay 另起进程时用）")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.proxies_only:
        # 纯代理模式：relay 另起进程。presence/push 仍上报到本机 relay 端口。
        relay_push_url = f"http://127.0.0.1:{args.relay_port}"
        api_token = os.environ.get("API_TOKEN", "")
        presence_reporter = make_presence_reporter(relay_push_url, api_token)
        start_proxies(args.ecs_ip, relay_push_url=relay_push_url, api_token=api_token,
                      on_player_data=presence_reporter, listen_host=args.proxy_host)
        logger.info("纯代理模式（无 relay）已启动，Ctrl-C 退出")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    run(
        ecs_ip=args.ecs_ip,
        relay_port=args.relay_port,
        relay_config=args.relay_config,
        relay_host=args.relay_host,
    )


if __name__ == "__main__":
    main()
