"""
app.py — MahjongAI Hotspot Relay

热点模式独立 FastAPI app。
职责：仅包含热点模式相关端点，不含 spectator 子进程、/register-room、VPN 页面等。

端点：
  GET  /               — 状态页（HTML），显示凭证状态 + 用法
  GET  /state?token=   — 返回最新 snapshot，包含 credential_ready 字段
  POST /register       — 接收 extractor 的 handshake_blob/auth_token_12b/srs_sessionid，持久化到 config.yaml
  POST /push           — 接收 extractor 推送的 snapshot
  GET  /mode           — 模式诊断信息

设计约束：
  - StateStore 直接从 remote/relay/state_store.py 导入，不复制
  - 凭证持久化（_persist_credentials）写回 config.yaml
  - 不包含 spectator 子进程管理、/register-room、/watch-info、VPN setup 页面
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

# 确保项目根目录在 sys.path，使 remote/relay/state_store.py 可导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from state_store import StateStore

_LOGGER = logging.getLogger("remote.hotspot.app")

# ─── FastAPI app ────────────────────────────────────────────────

app = FastAPI(title="MahjongAI Hotspot Relay")

# ─── 运行时配置（由 main.py 注入） ──────────────────────────────

_cfg: dict = {}
_cfg_path: str = ""
_state_store: StateStore = StateStore()


def configure(cfg: dict, cfg_path: str = ""):
    """main.py 启动时注入配置。

    参数:
      cfg      — 来自 config.yaml 的字典
      cfg_path — config.yaml 绝对路径（用于持久化凭证）
    """
    global _cfg, _cfg_path, _state_store
    _cfg = dict(cfg)
    _cfg_path = cfg_path
    push_timeout = float(cfg.get("push_timeout", 10.0))
    _state_store = StateStore(push_timeout=push_timeout)
    _LOGGER.info(
        "[HOTSPOT] app 配置完成: port=%s, push_timeout=%.1fs, cfg=%s",
        cfg.get("port", 8000),
        push_timeout,
        cfg_path,
    )


# ─── 请求模型 ────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    handshake_blob: str
    auth_token_12b: str
    srs_sessionid: str = ""
    api_token: str


class PushRequest(BaseModel):
    snapshot: Dict[str, Any]
    api_token: str


# ─── 内部工具 ────────────────────────────────────────────────────


def _check_api_token(token: str):
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _persist_credentials(handshake_hex: str, auth_hex: str, srs_sid: str = ""):
    """持久化凭证到 config.yaml"""
    if not _cfg_path:
        _LOGGER.warning("[HOTSPOT] 未设置配置文件路径，无法持久化凭证")
        return
    try:
        cfg_on_disk: dict = {}
        if os.path.isfile(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as f:
                cfg_on_disk = yaml.safe_load(f) or {}

        cfg_on_disk["handshake_blob"] = handshake_hex
        cfg_on_disk["auth_token_12b"] = auth_hex
        if srs_sid:
            cfg_on_disk["srs_sessionid"] = srs_sid

        with open(_cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg_on_disk, f, allow_unicode=True, default_flow_style=False)

        _LOGGER.info("[HOTSPOT] 凭证已持久化到 %s", _cfg_path)
    except Exception as exc:
        _LOGGER.error("[HOTSPOT] 持久化凭证失败: %s", exc)


def _build_index_page() -> str:
    """构建首页 HTML"""
    api_token_display = (_cfg.get("api_token", "") or "")[:8] + "..."
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    credential_status = "已就绪" if (hs and at) else "等待注册"
    port = _cfg.get("port", 8000)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI 热点模式</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;max-width:600px;margin:20px auto;padding:0 16px;background:#0f0f23;color:#ccc;line-height:1.6}}
h1{{color:#4f8;text-align:center;font-size:22px;margin:15px 0}}
h2{{color:#4f8;font-size:16px;margin:14px 0 6px}}
.info{{background:#1a1a2e;padding:15px;border-radius:8px;margin:10px 0}}
.info b{{color:#fff}}
.info code{{color:#4f8;font-family:monospace}}
.endpoint{{background:#0a0a15;padding:10px 14px;margin:8px 0;border-radius:6px;border-left:3px solid #4f8}}
.endpoint .method{{color:#ff6;font-weight:bold}}
.endpoint .path{{color:#4f8;font-family:monospace}}
.endpoint .desc{{color:#888;font-size:13px;margin-left:10px}}
</style>
</head>
<body>
<h1>MahjongAI 热点模式</h1>
<div class="info">
<b>说明：</b> 手机连PC共享热点，PC运行extractor抓包推送到此端口<br>
<b>端口：</b> <code>{port}</code><br>
<b>api_token：</b> <code>{api_token_display}</code><br>
<b>凭证状态：</b> {credential_status}
</div>
<h2>API 端点</h2>
<div class="endpoint"><span class="method">GET</span> <span class="path">/state?token=...</span><span class="desc">查询最新游戏状态</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/push</span><span class="desc">推送游戏快照（extractor 使用）</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/register</span><span class="desc">注册认证凭证（extractor 使用）</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/mode</span><span class="desc">模式诊断信息</span></div>
</body></html>"""


# ─── 路由 ────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_build_index_page())


@app.get("/state")
async def get_state(token: str = Query(..., description="鉴权 token")):
    _check_api_token(token)
    snapshot = _state_store.get_snapshot()
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    snapshot["credential_ready"] = bool(hs and at)
    snapshot["mode"] = "hotspot"
    return snapshot


@app.post("/register")
async def register(req: RegisterRequest):
    _check_api_token(req.api_token)
    try:
        bytes.fromhex(req.handshake_blob)
        bytes.fromhex(req.auth_token_12b)
        if req.srs_sessionid:
            bytes.fromhex(req.srs_sessionid)
    except ValueError:
        raise HTTPException(status_code=400, detail="凭证格式错误（需要十六进制字符串）")

    _cfg["handshake_blob"] = req.handshake_blob
    _cfg["auth_token_12b"] = req.auth_token_12b
    if req.srs_sessionid:
        _cfg["srs_sessionid"] = req.srs_sessionid

    _LOGGER.info(
        "[HOTSPOT] 已注册凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
        len(req.handshake_blob) // 2,
        len(req.auth_token_12b) // 2,
        "present" if req.srs_sessionid else "absent",
    )

    _persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)
    return {"status": "ok", "message": "凭证已注册", "mode": "hotspot"}


@app.post("/push")
async def push(req: PushRequest):
    _check_api_token(req.api_token)
    _state_store.on_push(req.snapshot)
    return {"status": "ok", "mode": "hotspot"}


@app.get("/mode")
async def get_mode():
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    return {
        "mode": "hotspot",
        "title": "热点模式 (Hotspot)",
        "description": "手机连PC共享热点，PC抓包推送到云端。端口 8000",
        "port": _cfg.get("port", 8000),
        "credential_ready": bool(hs and at),
        "has_srs_sessionid": bool(_cfg.get("srs_sessionid")),
    }
