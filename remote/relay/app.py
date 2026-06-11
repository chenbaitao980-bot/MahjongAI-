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
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml

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
_cfg_path = ""      # 配置文件路径（用于凭证持久化）
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


# ─── VPN 配置页（GET /vpn-setup）─────────────────────────────

def _build_vpn_setup_page():
    """读取 phone-setup.txt 并渲染为配置页"""
    import os as _os
    # phone-setup.txt 可能在 bundle 的 vpn/ 目录下
    for search in ["/opt/mahjong-extractor/vpn/phone-setup.txt",
                   _os.path.join(_os.path.dirname(__file__), "..", "..", "vpn", "phone-setup.txt")]:
        if _os.path.isfile(search):
            with open(search, "r", encoding="utf-8") as f:
                setup = f.read()
            break
    else:
        setup = "phone-setup.txt not found. Run vpn_configure.py first."

    # Parse credentials
    lines = setup.split("\n")
    creds = {}
    for line in lines:
        stripped = line.strip()
        if "Server:" in stripped and "IPSec" not in stripped:
            creds["Server"] = stripped.split(":", 1)[-1].strip()
        elif "pre-shared key:" in stripped:
            creds["PSK"] = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("Username:"):
            creds["Username"] = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("Password:"):
            creds["Password"] = stripped.split(":", 1)[-1].strip()

    server = creds.get("Server", "?")
    psk = creds.get("PSK", "?")
    username = creds.get("Username", "?")
    password = creds.get("Password", "?")

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VPN Setup</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;max-width:500px;margin:10px auto;padding:0 12px;background:#0f0f23;color:#ccc;line-height:1.6}}
h1{{color:#fff;text-align:center;font-size:20px;margin:10px 0}}
.sub{{text-align:center;color:#4f8;font-size:12px;margin-bottom:15px}}
.step{{background:#1a1a2e;padding:10px 14px;margin:8px 0;border-radius:8px;border-left:3px solid #4f8}}
.cred{{background:#0a0a15;padding:8px 12px;border-radius:6px;font-size:13px;margin:6px 0}}
.cred span{{color:#888;font-size:11px}}
.cred .val{{color:#4f8;font-family:monospace;font-size:14px;word-break:break-all}}
.btn{{background:#2a5a3e;color:#fff;border:none;padding:8px 20px;border-radius:6px;font-size:14px;width:100%;margin:8px 0;cursor:pointer}}
.btn:hover{{background:#3a7a5e}}
.copy{{background:#3a3a5e;color:#ccc;border:1px solid #5a5a8e;padding:3px 8px;border-radius:4px;font-size:11px;cursor:pointer;float:right;margin-top:-2px}}
.note{{font-size:11px;color:#666;text-align:center;margin:15px 0}}
</style>
<script>
function copyToClipboard(text) {{
  navigator.clipboard.writeText(text).then(function() {{
    var el = event.target;
    el.textContent = 'Copied!';
    setTimeout(function(){{ el.textContent = 'Copy'; }}, 1500);
  }});
}}
</script>
</head>
<body>
<h1>Mahjong VPN</h1>
<div class="sub">System VPN - no app - 1 minute</div>
<div class="step">
<b>Step 1:</b> Open VPN Settings<br>
<a href="intent://com.android.settings.Settings\$VpnSettingsActivity#Intent;scheme=android-app;end" style="color:#4f8;font-size:14px">Tap here to open VPN Settings</a>
<br><span style="color:#888;font-size:11px">or manually: Settings > Network > VPN > +</span>
</div>
<div class="step">
<b>Step 2:</b> Tap +, fill in (tap Copy for each):
<div class="cred">
<span>Name:</span> <span class="val">Mahjong</span>
<button class="copy" onclick="copyToClipboard('Mahjong')">Copy</button><br>
<span>Type:</span> <span class="val">IPSec IKEv2 RSA</span><br><br>
<b>First: Install CA Certificate</b><br>
<a href="/ca.crt" style="color:#4f8;font-size:14px">Tap to download CA certificate</a><br>
<span style="color:#888;font-size:11px">Open downloaded file > Name: Mahjong CA > OK</span><br><br>
<b>Then: Add VPN</b>
<div class="cred">
<span>Server:</span> <span class="val">""" + server + """</span>
<button class="copy" onclick="copyToClipboard('""" + server + """')">Copy</button><br>
<span>IPSec identifier:</span> <span class="val">8.136.37.136</span><br>
<span>IPSec CA certificate:</span> <span class="val">Mahjong CA</span><br>
<span>Username:</span> <span class="val">""" + username + """</span>
<button class="copy" onclick="copyToClipboard('""" + username + """')">Copy</button><br>
<span>Password:</span> <span class="val">""" + password + """</span>
<button class="copy" onclick="copyToClipboard('""" + password + """')">Copy</button>
</div>
</div>
<div class="step">
<b>Step 3:</b> Save > gear icon > <b>Always-on VPN = ON</b>
</div>
<button class="btn" onclick="location.href='intent://com.android.settings.Settings\$VpnSettingsActivity#Intent;scheme=android-app;end'">Open VPN Settings</button>
<div class="note">Split tunnel: only game traffic goes VPN. WeChat/4G direct.<br>After setup, never touch again.</div>
</body></html>"""
    return html


@app.get("/vpn-setup", response_class=HTMLResponse)
async def vpn_setup():
    """VPN setup page: static HTML with cert-only auth (no username/password)"""
    import os as _os
    for search in [_os.path.join(_STATIC_DIR, "vpn-setup.html"),
                   "/opt/mahjong-extractor/remote/relay/static/vpn-setup.html"]:
        if _os.path.isfile(search):
            with open(search, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    # Fallback: inline page
    return HTMLResponse(content="""<!DOCTYPE html>
<html><body style="background:#111;color:#ccc;font-family:sans-serif;padding:30px">
<h2>Mahjong VPN</h2>
<p><a href="/mahjong-vpn.p12" style="color:#4f8;font-size:18px">Download Certificate</a></p>
<p>Then: Settings > VPN > + > IPSec IKEv2 RSA</p>
<p>Server: 8.136.37.136 | CA: Mahjong CA | User cert: Mahjong VPN</p>
</body></html>""")


@app.get("/mahjong-vpn.p12")
async def p12_download():
    """Serve client PKCS12 certificate for phone import"""
    from fastapi.responses import FileResponse
    import os as _os
    for p in ["/opt/mahjong-extractor/mahjong-vpn.p12", "/tmp/mahjong-vpn.p12"]:
        if _os.path.isfile(p):
            return FileResponse(p, media_type="application/x-pkcs12", filename="mahjong-vpn.p12")
    return HTMLResponse(content="Certificate not found", status_code=404)


@app.get("/ca.crt")
async def ca_cert():
    """Serve CA certificate for phone to install"""
    import os as _os
    ca_paths = ["/etc/ipsec.d/cacerts/ca.crt"]
    for p in ca_paths:
        if _os.path.isfile(p):
            with open(p, "r") as f:
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(content=f.read(), media_type="application/x-x509-ca-cert")
    return HTMLResponse(content="CA cert not found", status_code=404)


# ─── 请求/响应模型 ─────────────────────────────────────────────


class RegisterRequest(BaseModel):
    handshake_blob: str    # hex 字符串
    auth_token_12b: str    # hex 字符串
    api_token: str


class PushRequest(BaseModel):
    snapshot: Dict[str, Any]
    api_token: str


class RegisterRoomRequest(BaseModel):
    room_id: int
    game_id: int = 0
    api_token: str


# ─── 内部辅助 ──────────────────────────────────────────────────


def _check_api_token(token: str):
    """验证 api_token，不匹配时抛出 401"""
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _ensure_game_client_running():
    """
    如果 extractor 离线且 GameClient 未运行，则启动它。
    需要 handshake_blob（必需）+ auth_token_12b（强烈建议，用于 0x0006 认证）。
    缺少 auth_token_12b 时 GameClient 仍会启动但无法完成服务端认证。
    """
    global _game_client

    use_gc = _state_store.should_use_game_client()
    handshake_hex = _cfg.get("handshake_blob", "")
    last_push = _state_store.last_push_time

    if not use_gc:
        _LOGGER.debug("[模式] extractor 在线 (last_push=%.1fs前), 不需要 GameClient",
                      time.time() - last_push if last_push else float('inf'))
        return

    if not handshake_hex:
        _LOGGER.info("[模式] extractor 离线 (last_push=%s), 但无 handshake_blob, 跳过 GameClient",
                     "从未推送" if last_push == 0.0 else f"{time.time() - last_push:.1f}s前")
        return

    auth_hex = _cfg.get("auth_token_12b", "")
    if not auth_hex:
        now = time.time()
        if now - getattr(_ensure_game_client_running, '_last_auth_warn', 0) > 30.0:
            _LOGGER.warning("[模式] extractor 离线, 有 handshake_blob 但缺少 auth_token_12b。"
                            "GameClient 不会启动（缺少 0x0006 认证包 = 服务端立即断开连接）。"
                            "请确保 extractor 部署在手机流量经过的路由器/NAS/旁路由上。")
            _ensure_game_client_running._last_auth_warn = now
        return

    if _game_client is not None and not _game_client._running:
        _LOGGER.info("[模式] 旧 GameClient 已停止，准备重建")
        _game_client = None  # 旧客户端已停止，重建

    if _game_client is not None:
        _LOGGER.debug("[模式] GameClient 已在运行中, running=%s", _game_client._running)
        return

    _LOGGER.info("[模式] extractor 离线 (last_push=%s), 有 handshake_blob (%d bytes), 启动 GameClient",
                 "从未推送" if last_push == 0.0 else f"{time.time() - last_push:.1f}s前",
                 len(handshake_hex) // 2)

    try:
        handshake_blob = bytes.fromhex(handshake_hex)
        auth_token = bytes.fromhex(auth_hex) if auth_hex else None
        if auth_token and len(auth_token) != 12:
            _LOGGER.warning("[模式] auth_token_12b 长度异常 (%d bytes, 期望 12)，忽略", len(auth_token))
            auth_token = None
    except ValueError:
        _LOGGER.error("[模式] handshake_blob hex 格式错误，无法启动 GameClient")
        return

    server_ip = _cfg.get("game_server_ip", "47.96.0.227")
    server_port = int(_cfg.get("game_server_port", 7777))

    _game_client = GameClient(
        server_ip=server_ip,
        server_port=server_port,
        handshake_blob=handshake_blob,
        auth_token_12b=auth_token,
        state_store=_state_store,
    )
    try:
        loop = asyncio.get_event_loop()
        _game_client.start(loop=loop)
        _LOGGER.info("[模式] GameClient 已启动（场景B：extractor 离线）→ 连接 %s:%d", server_ip, server_port)
    except RuntimeError:
        _LOGGER.warning("[模式] 无法获取事件循环，GameClient 未启动")


def _stop_game_client():
    """停止 GameClient（extractor 上线时可选调用）"""
    global _game_client
    if _game_client is not None:
        _game_client.stop()
        _game_client = None
        _LOGGER.info("[模式] GameClient 已停止（extractor 上线，切换到被动模式）")


def _persist_credentials(handshake_hex: str, auth_hex: str):
    """将凭证持久化到 config.yaml，relay 重启后仍可用"""
    global _cfg_path
    if not _cfg_path:
        _LOGGER.warning("[持久化] 未设置配置文件路径，无法持久化凭证")
        return
    try:
        # 读取当前配置文件
        cfg_on_disk = {}
        if os.path.isfile(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as f:
                cfg_on_disk = yaml.safe_load(f) or {}

        # 只更新凭证字段
        cfg_on_disk["handshake_blob"] = handshake_hex
        cfg_on_disk["auth_token_12b"] = auth_hex

        # 写回
        with open(_cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg_on_disk, f, allow_unicode=True, default_flow_style=False)

        _LOGGER.info("[持久化] 凭证已写入 %s", _cfg_path)
    except Exception as exc:
        _LOGGER.error("[持久化] 写入凭证失败: %s", exc)


# ─── 端点 ──────────────────────────────────────────────────────


@app.post("/register")
async def register(req: RegisterRequest):
    """
    接收 extractor 上传的认证凭证，存入内存配置，持久化到 config.yaml，触发 GameClient 启动。
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
    _LOGGER.info("已注册凭证: handshake_blob=%d bytes(%s...), auth_token_12b=%d bytes(%s...)",
                 len(req.handshake_blob) // 2, req.handshake_blob[:8],
                 len(req.auth_token_12b) // 2, req.auth_token_12b[:8])

    # 持久化凭证到 config.yaml
    _persist_credentials(req.handshake_blob, req.auth_token_12b)

    # 注意：不在此处启动 GameClient。GameClient 已确认不可行
    # （缺少 SRS 认证层，服务端立即关闭连接）。
    # /state 端点会在每次请求时调用 _ensure_game_client_running()
    # 进行凭证完备性检查。

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


@app.post("/register-room")
async def register_room(req: RegisterRoomRequest):
    """
    接收热点端 extractor 上传的 roomid/gameid（通道B）。
    存储到内存，供 srs_spectator 服务拉取。
    """
    _check_api_token(req.api_token)

    _state_store.set_room_info(req.room_id, req.game_id)
    _LOGGER.info("[通道B] 注册房间: room_id=%d, game_id=%d", req.room_id, req.game_id)

    # 尝试通知 srs_spectator 服务
    _notify_spectator(req.room_id, req.game_id)

    return {"status": "ok", "message": "房间已注册", "room_id": req.room_id, "game_id": req.game_id}


@app.get("/watch-info")
async def get_watch_info(token: str = Query(..., description="鉴权 token")):
    """
    返回当前需要旁观的房间信息（供 srs_spectator 轮询）。
    """
    _check_api_token(token)
    info = _state_store.get_room_info()
    return info


@app.get("/state")
async def get_state(token: str = Query(..., description="鉴权 token")):
    """
    返回最新游戏状态 snapshot。
    无数据时返回 {"phase": "idle"}，无效 token 返回 401。
    附加 credential_ready 字段表示 relay 是否持有认证凭证（断热点后 GameClient 可用）。
    """
    _check_api_token(token)

    # 检查是否需要启动 GameClient
    _ensure_game_client_running()

    snapshot = _state_store.get_snapshot()
    # 附加凭证状态，方便调用方判断断热点后是否能自动接管
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    snapshot["credential_ready"] = bool(hs and at)
    return snapshot


# ─── 旁观通知（通道B）────────────────────────────────────────

# srs_spectator 服务地址（同机部署默认 localhost:8001）
_SPECTATOR_URL = ""


def _set_spectator_url(url: str):
    """设置 srs_spectator 服务地址"""
    global _SPECTATOR_URL
    _SPECTATOR_URL = url.rstrip("/") if url else ""


def _notify_spectator(room_id: int, game_id: int):
    """通知 srs_spectator 服务开始旁观（异步，不阻塞）"""
    global _SPECTATOR_URL
    if not _SPECTATOR_URL:
        _SPECTATOR_URL = _cfg.get("spectator_url", "http://localhost:8001")
    if not _SPECTATOR_URL:
        return

    def _do_notify():
        try:
            api_token = _cfg.get("api_token", "")
            resp = requests.post(
                f"{_SPECTATOR_URL}/watch",
                # srs_spectator WatchRequest 期望 roomid/gameid（main.py:49-53），
                # 字段名必须与该契约一致，否则 FastAPI 返回 422。
                json={"roomid": room_id, "gameid": game_id, "api_token": api_token},
                timeout=5,
            )
            if resp.status_code == 200:
                _LOGGER.info("[通道B] 已通知 srs_spectator: room_id=%d, game_id=%d", room_id, game_id)
            else:
                _LOGGER.warning("[通道B] srs_spectator 通知失败: %d %s", resp.status_code, resp.text)
        except Exception as e:
            _LOGGER.debug("[通道B] srs_spectator 通知异常: %s", e)

    threading.Thread(target=_do_notify, daemon=True).start()


# ─── 应用配置注入（由 main.py 调用）──────────────────────────


def configure(cfg: dict, cfg_path: str = ""):
    """注入配置，由 main.py 在启动时调用"""
    global _cfg, _cfg_path, _state_store
    _cfg.update(cfg)
    if cfg_path:
        _cfg_path = cfg_path
    # 从配置读取 push_timeout，默认 10 秒（断热点后快速切换 GameClient）
    push_timeout = float(cfg.get("push_timeout", 10.0))
    _state_store.push_timeout = push_timeout
    _LOGGER.info("push_timeout=%.1fs (超过此时间无 /push 即启动 GameClient)", push_timeout)
    # 设置 srs_spectator 地址
    spec_url = cfg.get("spectator_url", "http://localhost:8001")
    if spec_url:
        _set_spectator_url(spec_url)
        _LOGGER.info("srs_spectator URL: %s", spec_url)
