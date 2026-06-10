"""
app.py — FastAPI 应用

三个端点：
  POST /register  — 接收 extractor 上传的认证凭证
  POST /push      — 接收 extractor 推送的实时 snapshot
  GET  /state     — 返回最新游戏状态
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional

from state_store import StateStore
from game_client import GameClient

_LOGGER = logging.getLogger("remote.relay.app")

# 实时手牌展示页（GET /）；放在 static/index.html，启动时读入内存
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_INDEX_HTML_PATH = os.path.join(_STATIC_DIR, "index.html")

# 由 main.py 在启动时注入
_cfg = {}           # relay 配置字典
_state_store = StateStore()
_game_client = None  # GameClient 实例（懒启动）

app = FastAPI(title="MahjongAI Remote Relay")


@app.get("/", response_class=HTMLResponse)
async def index():
    """实时手牌展示页。页面内 JS 轮询 /state 渲染手牌。"""
    try:
        with open(_INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>index.html 缺失</h1><p>请确认 remote/relay/static/index.html 已部署。</p>",
            status_code=500,
        )


# ─── 请求/响应模型 ─────────────────────────────────────────────


class RegisterRequest(BaseModel):
    handshake_blob: str    # hex 字符串
    auth_token_12b: str    # hex 字符串
    api_token: str


class PushRequest(BaseModel):
    snapshot: Dict[str, Any]
    api_token: str


# ─── 内部辅助 ──────────────────────────────────────────────────


def _check_api_token(token: str):
    """验证 api_token，不匹配时抛出 401"""
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _ensure_game_client_running():
    """
    如果 extractor 离线（状态存储判断）且 GameClient 未运行，则启动它。
    只有在已配置 handshake_blob 和 auth_token_12b 时才启动。
    """
    global _game_client

    if not _state_store.should_use_game_client():
        return  # extractor 在线，不需要 GameClient

    handshake_hex = _cfg.get("handshake_blob", "")
    auth_hex = _cfg.get("auth_token_12b", "")
    if not handshake_hex or not auth_hex:
        _LOGGER.debug("extractor 离线但无凭证（handshake_blob/auth_token_12b 为空），跳过 GameClient 启动")
        return  # 没有凭证，无法连接

    if _game_client is not None and not _game_client._running:
        _game_client = None  # 旧客户端已停止，重建

    if _game_client is None:
        try:
            handshake_blob = bytes.fromhex(handshake_hex)
            auth_token_12b = bytes.fromhex(auth_hex)
        except ValueError:
            _LOGGER.error("凭证 hex 格式错误，无法启动 GameClient")
            return

        server_ip = _cfg.get("game_server_ip", "47.96.0.227")
        server_port = int(_cfg.get("game_server_port", 7777))

        _game_client = GameClient(
            server_ip=server_ip,
            server_port=server_port,
            handshake_blob=handshake_blob,
            auth_token_12b=auth_token_12b,
            state_store=_state_store,
        )
        try:
            loop = asyncio.get_event_loop()
            _game_client.start(loop=loop)
            _LOGGER.info("GameClient 已启动（场景B：extractor 离线）")
        except RuntimeError:
            _LOGGER.warning("无法获取事件循环，GameClient 未启动")


def _stop_game_client():
    """停止 GameClient（extractor 上线时可选调用）"""
    global _game_client
    if _game_client is not None:
        _game_client.stop()
        _game_client = None
        _LOGGER.info("GameClient 已停止（extractor 上线，切换到被动模式）")


# ─── 端点 ──────────────────────────────────────────────────────


@app.post("/register")
async def register(req: RegisterRequest):
    """
    接收 extractor 上传的认证凭证，存入内存配置，触发 GameClient 启动。
    """
    _check_api_token(req.api_token)

    # 验证 hex 格式
    try:
        bytes.fromhex(req.handshake_blob)
        bytes.fromhex(req.auth_token_12b)
    except ValueError:
        raise HTTPException(status_code=400, detail="凭证格式错误（需要十六进制字符串）")

    _cfg["handshake_blob"] = req.handshake_blob
    _cfg["auth_token_12b"] = req.auth_token_12b
    _LOGGER.info("已注册凭证: handshake_blob=%d bytes, auth_token_12b=%d bytes",
                 len(req.handshake_blob) // 2, len(req.auth_token_12b) // 2)

    # 凭证更新后重启 GameClient
    _stop_game_client()
    _ensure_game_client_running()

    return {"status": "ok", "message": "凭证已注册"}


@app.post("/push")
async def push(req: PushRequest):
    """
    接收 extractor 推送的实时 snapshot（场景A）。
    """
    _check_api_token(req.api_token)

    was_offline = _state_store.should_use_game_client()
    _state_store.on_push(req.snapshot)

    # extractor 上线时停止 GameClient（降级为被动接收）
    if was_offline:
        _stop_game_client()

    return {"status": "ok"}


@app.get("/state")
async def get_state(token: str = Query(..., description="鉴权 token")):
    """
    返回最新游戏状态 snapshot。
    无数据时返回 {"phase": "idle"}，无效 token 返回 401。
    """
    _check_api_token(token)

    # 检查是否需要启动 GameClient
    _ensure_game_client_running()

    snapshot = _state_store.get_snapshot()
    return snapshot


# ─── 应用配置注入（由 main.py 调用）──────────────────────────


def configure(cfg: dict):
    """注入配置，由 main.py 在启动时调用"""
    global _cfg
    _cfg.update(cfg)
