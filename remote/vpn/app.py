"""
app.py — MahjongAI VPN Relay

VPN 模式独立 FastAPI app。
职责：包含 VPN 模式相关端点 + VPN 配置页（/vpn-setup, /mahjong-vpn.p12, /ca.crt）。

端点：
  GET  /               — 状态页（HTML），显示凭证状态 + 用法
  GET  /state?token=   — 返回最新 snapshot，包含 credential_ready 字段
  POST /register       — 接收 extractor 的 handshake_blob/auth_token_12b/srs_sessionid，持久化到 config.yaml
  POST /push           — 接收 extractor 推送的 snapshot
  GET  /mode           — 模式诊断信息
  GET  /vpn-setup      — VPN 配置引导页（手机扫码用）
  GET  /mahjong-vpn.p12 — 客户端 PKCS12 证书下载
  GET  /ca.crt         — CA 证书下载

设计约束：
  - StateStore 直接从 remote/relay/state_store.py 导入，不复制
  - 凭证持久化（_persist_credentials）写回 config.yaml
  - 不包含 spectator 子进程管理、/register-room、/watch-info
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

# 确保项目根目录和 relay 目录在 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from state_store import StateStore

_LOGGER = logging.getLogger("remote.vpn.app")

# static 目录（和 relay/static 共享）
_STATIC_DIR = os.path.join(_RELAY_DIR, "static")

# ─── FastAPI app ────────────────────────────────────────────────

app = FastAPI(title="MahjongAI VPN Relay")

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
        "[VPN] app 配置完成: port=%s, push_timeout=%.1fs, cfg=%s",
        cfg.get("port", 8001),
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
        _LOGGER.warning("[VPN] 未设置配置文件路径，无法持久化凭证")
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

        _LOGGER.info("[VPN] 凭证已持久化到 %s", _cfg_path)
    except Exception as exc:
        _LOGGER.error("[VPN] 持久化凭证失败: %s", exc)


def _build_index_page() -> str:
    """构建首页 HTML"""
    api_token_display = (_cfg.get("api_token", "") or "")[:8] + "..."
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    credential_status = "已就绪" if (hs and at) else "等待注册"
    port = _cfg.get("port", 8001)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI VPN 模式</title>
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
<h1>MahjongAI VPN 模式</h1>
<div class="info">
<b>说明：</b> 手机配置 IPSec IKEv2 VPN 连云端，云端 tcpdump 嗅探流量推送到此端口<br>
<b>端口：</b> <code>{port}</code><br>
<b>api_token：</b> <code>{api_token_display}</code><br>
<b>凭证状态：</b> {credential_status}
</div>
<h2>API 端点</h2>
<div class="endpoint"><span class="method">GET</span> <span class="path">/state?token=...</span><span class="desc">查询最新游戏状态</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/push</span><span class="desc">推送游戏快照（extractor 使用）</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/register</span><span class="desc">注册认证凭证（extractor 使用）</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/mode</span><span class="desc">模式诊断信息</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/vpn-setup</span><span class="desc">VPN 手机配置引导页</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/ca.crt</span><span class="desc">CA 证书下载</span></div>
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
    snapshot["mode"] = "vpn"
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
        "[VPN] 已注册凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
        len(req.handshake_blob) // 2,
        len(req.auth_token_12b) // 2,
        "present" if req.srs_sessionid else "absent",
    )

    _persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)
    return {"status": "ok", "message": "凭证已注册", "mode": "vpn"}


@app.post("/push")
async def push(req: PushRequest):
    _check_api_token(req.api_token)
    _state_store.on_push(req.snapshot)
    return {"status": "ok", "mode": "vpn"}


@app.get("/mode")
async def get_mode():
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    return {
        "mode": "vpn",
        "title": "VPN 模式 (Phone VPN)",
        "description": "手机配置 IPSec IKEv2 VPN 连云端，云端抓包推送。端口 8001",
        "port": _cfg.get("port", 8001),
        "credential_ready": bool(hs and at),
        "has_srs_sessionid": bool(_cfg.get("srs_sessionid")),
    }


# ─── VPN 专属端点 ────────────────────────────────────────────────


@app.get("/vpn-setup", response_class=HTMLResponse)
async def vpn_setup():
    """VPN 配置引导页：从 static/vpn-setup.html 读取，不存在时返回 inline fallback"""
    for search in [
        os.path.join(_STATIC_DIR, "vpn-setup.html"),
        "/opt/mahjong-extractor/remote/relay/static/vpn-setup.html",
    ]:
        if os.path.isfile(search):
            with open(search, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    # Fallback: inline page
    return HTMLResponse(content="""<!DOCTYPE html>
<html><body style="background:#111;color:#ccc;font-family:sans-serif;padding:30px">
<h2>Mahjong VPN Setup</h2>
<p><a href="/ca.crt" style="color:#4f8;font-size:18px">Download CA Certificate</a></p>
<p>Settings &gt; VPN &gt; + &gt; IKEv2/IPSec PSK</p>
<p>vpn-setup.html not found. Deploy relay with static/ directory.</p>
</body></html>""")


@app.get("/mahjong-vpn.p12")
async def p12_download():
    """服务客户端 PKCS12 证书（手机导入用）"""
    from fastapi.responses import FileResponse
    for p in ["/opt/mahjong-extractor/mahjong-vpn.p12", "/tmp/mahjong-vpn.p12"]:
        if os.path.isfile(p):
            return FileResponse(p, media_type="application/x-pkcs12", filename="mahjong-vpn.p12")
    return HTMLResponse(content="Certificate not found", status_code=404)


@app.get("/ca.crt")
async def ca_cert():
    """服务 CA 证书（手机安装用）"""
    ca_paths = ["/etc/ipsec.d/cacerts/ca.crt"]
    for p in ca_paths:
        if os.path.isfile(p):
            with open(p, "r") as f:
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(content=f.read(), media_type="application/x-x509-ca-cert")
    return HTMLResponse(content="CA cert not found", status_code=404)
