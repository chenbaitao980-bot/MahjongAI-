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
import subprocess
import sys
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Ensure relay directory is importable for bare imports like 'from state_store'
_RELAY_DIR = os.path.dirname(os.path.abspath(__file__))
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)

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
_srs_spectator_proc = None  # SRS spectator 子进程（懒启动）

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
    handshake_blob: str    # hex 字符串，MJ 层握手 blob
    auth_token_12b: str    # hex 字符串，MJ 层认证 token (12B)
    srs_sessionid: str = ""  # hex 字符串，SRS 层 sessionid (16B)，用于旁观客户端直连
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
    extractor 离线时的降级策略。

    优先使用 SRS spectator（新方案，需要 srs_sessionid）。
    兜底使用 GameClient（旧方案，已知不可行，仅保留兼容）。
    """
    global _game_client

    use_gc = _state_store.should_use_game_client()
    handshake_hex = _cfg.get("handshake_blob", "")
    srs_sid = _cfg.get("srs_sessionid", "")
    last_push = _state_store.last_push_time

    if not use_gc:
        _LOGGER.debug("[模式] extractor 在线，不需要降级连接")
        return

    if not handshake_hex:
        return

    # ── 新方案：SRS spectator（需要 srs_sessionid）──
    if srs_sid and len(srs_sid) >= 32:  # 16B hex = 32 chars
        _LOGGER.info("[模式] extractor 离线但 srs_sessionid 可用，启用 SRS spectator...")
        _start_srs_spectator(handshake_hex, srs_sid)
        return

    # ── 旧方案：GameClient（已确认不可行，不再自动启动）──
    # SRS 认证层在 native libcocos2dlua.so 中，纯 Python 无法复现。
    # 服务端立即关闭连接（存活 0.0 秒）。详见 spec/backend/remote-access.md。
    _LOGGER.info("[模式] extractor 离线，GameClient 已禁用（SRS 认证不可复制）。"
                 "需要 extractor 在线或使用 SRS spectator（需 srs_sessionid）")
    return


def _start_srs_spectator(handshake_hex, srs_sid):
    """启动 SRS spectator 子进程，通过环境变量传递凭证。"""
    global _srs_spectator_proc
    
    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None:
        _LOGGER.debug("[模式] SRS spectator 已在运行中 (pid=%d)", _srs_spectator_proc.pid)
        return
    
    auth_hex = _cfg.get("auth_token_12b", "")
    api_token = _cfg.get("api_token", "")
    relay_url = f"http://127.0.0.1:{_cfg.get('port', 8000)}"
    userid = _cfg.get("userid", "newpt1084306678")

    env = os.environ.copy()
    env["AUTH_TOKEN_12B"] = auth_hex
    env["HANDSHAKE_BLOB"] = handshake_hex
    env["SRS_SESSIONID"] = srs_sid
    env["RELAY_URL"] = relay_url
    env["API_TOKEN"] = api_token
    env["USERID"] = userid
    env["PYTHONPATH"] = os.pathsep.join([_ROOT, os.path.join(_ROOT, "remote", "srs_spectator")])

    spectator_main = os.path.join(_ROOT, "remote", "srs_spectator", "main.py")
    log_path = os.path.join(_ROOT, "logs", "srs_spectator.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        _srs_spectator_proc = subprocess.Popen(
            [sys.executable, spectator_main],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=_ROOT,
        )
        _LOGGER.info("[模式] SRS spectator 子进程已启动 (pid=%d, log=%s)", _srs_spectator_proc.pid, log_path)
    except Exception as exc:
        _LOGGER.error("[模式] 启动 SRS spectator 失败: %s", exc)


def _stop_game_client():
    """停止 GameClient 和 SRS spectator（extractor 上线时可选调用）"""
    global _game_client, _srs_spectator_proc
    if _game_client is not None:
        _game_client.stop()
        _game_client = None
        _LOGGER.info("[模式] GameClient 已停止（extractor 上线，切换到被动模式）")
    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None:
        _srs_spectator_proc.terminate()
        try:
            _srs_spectator_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _srs_spectator_proc.kill()
        _srs_spectator_proc = None
        _LOGGER.info("[模式] SRS spectator 已停止")


def _persist_credentials(handshake_hex: str, auth_hex: str, srs_sid: str = ""):
    """将凭证持久化到 config.yaml，relay 重启后仍可用"""
    global _cfg_path
    if not _cfg_path:
        _LOGGER.warning("[持久化] 未设置配置文件路径，无法持久化凭证")
        return
    try:
        cfg_on_disk = {}
        if os.path.isfile(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as f:
                cfg_on_disk = yaml.safe_load(f) or {}

        cfg_on_disk["handshake_blob"] = handshake_hex
        cfg_on_disk["auth_token_12b"] = auth_hex
        if srs_sid:
            cfg_on_disk["srs_sessionid"] = srs_sid

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
        if req.srs_sessionid:
            bytes.fromhex(req.srs_sessionid)
    except ValueError:
        raise HTTPException(status_code=400, detail="凭证格式错误（需要十六进制字符串）")

    _cfg["handshake_blob"] = req.handshake_blob
    _cfg["auth_token_12b"] = req.auth_token_12b
    if req.srs_sessionid:
        _cfg["srs_sessionid"] = req.srs_sessionid
    _LOGGER.info("已注册凭证: handshake_blob=%d bytes(%s...), auth_token_12b=%d bytes(%s...), srs_sid=%s",
                 len(req.handshake_blob) // 2, req.handshake_blob[:8],
                 len(req.auth_token_12b) // 2, req.auth_token_12b[:8],
                 "present" if req.srs_sessionid else "absent")

    # 持久化凭证到 config.yaml
    _persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)

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
