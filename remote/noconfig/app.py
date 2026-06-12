"""
app.py — MahjongAI Noconfig Relay

无配置模式独立 FastAPI app。
职责：包含 noconfig 模式相关端点 + SRS spectator 子进程管理。

端点：
  GET  /               — 状态页（HTML），显示凭证状态 + 用法
  GET  /state?token=   — 返回最新 snapshot，触发 spectator 按需启动
  POST /register       — 接收 extractor 的 handshake_blob/auth_token_12b/srs_sessionid，持久化到 config.yaml
  POST /push           — 接收 extractor 推送的 snapshot（extractor 上线时停止 spectator）
  GET  /mode           — 模式诊断信息
  POST /register-room  — 接收 roomid/gameid，通知 spectator 开始旁观
  GET  /watch-info     — 返回当前房间信息

设计约束：
  - StateStore 直接从 remote/relay/state_store.py 导入，不复制
  - SRS spectator 子进程由本模块管理（从 relay/core.py 迁移）
  - 不包含 VPN setup 页面（/vpn-setup, /mahjong-vpn.p12, /ca.crt）
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
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

_LOGGER = logging.getLogger("remote.noconfig.app")

# ─── FastAPI app ────────────────────────────────────────────────

app = FastAPI(title="MahjongAI Noconfig Relay")

# ─── 运行时配置（由 main.py 注入） ──────────────────────────────

_cfg: dict = {}
_cfg_path: str = ""
_state_store: StateStore = StateStore()

# ─── SRS spectator 子进程状态 ───────────────────────────────────

_srs_spectator_proc = None
_spectator_restart_count = 0
_SPECTATOR_MAX_RESTARTS = 5

# 标志位：configure() 注入后若已有凭证，第一次 /state 调用时启动 spectator
_should_auto_start = False


def configure(cfg: dict, cfg_path: str = ""):
    """main.py 启动时注入配置。

    参数:
      cfg      — 来自 config.yaml 的字典
      cfg_path — config.yaml 绝对路径（用于持久化凭证）
    """
    global _cfg, _cfg_path, _state_store, _should_auto_start
    _cfg = dict(cfg)
    _cfg_path = cfg_path
    push_timeout = float(cfg.get("push_timeout", 10.0))
    _state_store = StateStore(push_timeout=push_timeout)

    # 若已有 srs_sessionid，标记自动启动
    srs_sid = cfg.get("srs_sessionid", "")
    hs = cfg.get("handshake_blob", "")
    if srs_sid and len(srs_sid) >= 32 and hs:
        _should_auto_start = True
        _LOGGER.info("[NOCONFIG] 已有 SRS 凭证，将在首次 /state 请求时自动启动 spectator")

    _LOGGER.info(
        "[NOCONFIG] app 配置完成: port=%s, push_timeout=%.1fs, cfg=%s",
        cfg.get("port", 8002),
        push_timeout,
        cfg_path,
    )

    # 使用延迟启动线程，让 uvicorn 先完成初始化
    if _should_auto_start:
        def _delayed_start():
            import time
            time.sleep(2)
            _LOGGER.info("[NOCONFIG] 延迟自动启动 spectator...")
            _ensure_spectator_running()

        threading.Thread(target=_delayed_start, daemon=True).start()


# ─── 请求模型 ────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    handshake_blob: str
    auth_token_12b: str
    srs_sessionid: str = ""
    api_token: str


class PushRequest(BaseModel):
    snapshot: Dict[str, Any]
    api_token: str


class RegisterRoomRequest(BaseModel):
    room_id: int
    game_id: int = 0
    api_token: str


# ─── 内部工具 ────────────────────────────────────────────────────


def _check_api_token(token: str):
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _persist_credentials(handshake_hex: str, auth_hex: str, srs_sid: str = ""):
    """持久化凭证到 config.yaml"""
    if not _cfg_path:
        _LOGGER.warning("[NOCONFIG] 未设置配置文件路径，无法持久化凭证")
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

        _LOGGER.info("[NOCONFIG] 凭证已持久化到 %s", _cfg_path)
    except Exception as exc:
        _LOGGER.error("[NOCONFIG] 持久化凭证失败: %s", exc)


def _ensure_spectator_running():
    """检查 SRS spectator 子进程健康状态，按需启动。

    包含健康检查和重启限制：
    - extractor 在线时跳过（不需要 spectator）
    - 进程已退出则清理并重启（上限 _SPECTATOR_MAX_RESTARTS 次）
    """
    global _srs_spectator_proc, _spectator_restart_count

    if not _state_store.should_use_game_client():
        return

    handshake_hex = _cfg.get("handshake_blob", "")
    srs_sid = _cfg.get("srs_sessionid", "")

    if not handshake_hex:
        return

    if not srs_sid or len(srs_sid) < 32:
        _LOGGER.warning("[NOCONFIG] extractor 离线但无 srs_sessionid（需先运行热点/VPN模式提取凭证），无法启动 spectator")
        return

    # 健康检查：如果进程已退出，清理旧进程
    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is not None:
        exit_code = _srs_spectator_proc.poll()
        _LOGGER.warning("[NOCONFIG] SRS spectator 已退出 (code=%d)，准备重启...", exit_code)
        _srs_spectator_proc = None

        if _spectator_restart_count >= _SPECTATOR_MAX_RESTARTS:
            _LOGGER.error(
                "[NOCONFIG] SRS spectator 已重启 %d 次（上限 %d），不再重试",
                _spectator_restart_count,
                _SPECTATOR_MAX_RESTARTS,
            )
            return

    # 进程仍在运行则跳过
    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None:
        return

    _LOGGER.info("[NOCONFIG] extractor 离线，启动 SRS spectator...")
    _start_srs_spectator(handshake_hex, srs_sid)


def _start_srs_spectator(handshake_hex: str, srs_sid: str):
    """启动 SRS spectator 子进程。"""
    global _srs_spectator_proc, _spectator_restart_count

    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None:
        _LOGGER.debug("[NOCONFIG] SRS spectator 已在运行中 (pid=%d)", _srs_spectator_proc.pid)
        return

    _spectator_restart_count += 1
    if _spectator_restart_count > _SPECTATOR_MAX_RESTARTS:
        _LOGGER.error(
            "[NOCONFIG] SRS spectator 重启次数超限 (%d/%d)，不再启动",
            _spectator_restart_count,
            _SPECTATOR_MAX_RESTARTS,
        )
        return

    auth_hex = _cfg.get("auth_token_12b", "")
    api_token = _cfg.get("api_token", "")
    relay_url = f"http://127.0.0.1:{_cfg.get('port', 8002)}"
    bind_port_str = "8003"  # spectator 固定监听 8003，与 srs_spectator/main.py BIND_PORT 一致
    userid = _cfg.get("userid", "newpt1084306678")

    env = os.environ.copy()
    env["AUTH_TOKEN_12B"] = auth_hex
    env["HANDSHAKE_BLOB"] = handshake_hex
    env["SRS_SESSIONID"] = srs_sid
    env["RELAY_URL"] = relay_url
    env["API_TOKEN"] = api_token
    env["USERID"] = userid
    env["BIND_PORT"] = bind_port_str
    env["PYTHONPATH"] = os.pathsep.join([_ROOT, os.path.join(_ROOT, "remote", "srs_spectator")])

    spectator_main = os.path.join(_ROOT, "remote", "srs_spectator", "main.py")
    log_path = os.path.join(_ROOT, "logs", "srs_spectator_noconfig.log")
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
        _LOGGER.info(
            "[NOCONFIG] SRS spectator 子进程已启动 (pid=%d, log=%s)",
            _srs_spectator_proc.pid,
            log_path,
        )
    except Exception as exc:
        _LOGGER.error("[NOCONFIG] 启动 SRS spectator 失败: %s", exc)


def _stop_spectator():
    """停止 SRS spectator 子进程（extractor 上线时调用）"""
    global _srs_spectator_proc
    if _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None:
        _srs_spectator_proc.terminate()
        try:
            _srs_spectator_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _srs_spectator_proc.kill()
        _srs_spectator_proc = None
        _LOGGER.info("[NOCONFIG] SRS spectator 已停止（extractor 上线）")


def _notify_spectator(room_id: int, game_id: int):
    """通知 SRS spectator 服务开始旁观（异步线程，不阻塞请求）"""
    spectator_url = _cfg.get("spectator_url", "") or "http://localhost:8003"
    spectator_url = spectator_url.rstrip("/")

    def _do_notify():
        try:
            import requests as _requests
            api_token = _cfg.get("api_token", "")
            resp = _requests.post(
                f"{spectator_url}/watch",
                json={"roomid": room_id, "gameid": game_id, "api_token": api_token},
                timeout=5,
            )
            if resp.status_code == 200:
                _LOGGER.info(
                    "[NOCONFIG] 已通知 spectator: room_id=%d, game_id=%d", room_id, game_id
                )
            else:
                _LOGGER.warning(
                    "[NOCONFIG] spectator 通知失败: %d %s", resp.status_code, resp.text
                )
        except Exception as e:
            _LOGGER.debug("[NOCONFIG] spectator 通知异常: %s", e)

    threading.Thread(target=_do_notify, daemon=True).start()


def _build_index_page() -> str:
    """构建首页 HTML"""
    api_token_display = (_cfg.get("api_token", "") or "")[:8] + "..."
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    srs_sid = _cfg.get("srs_sessionid", "")
    credential_status = "已就绪" if (hs and at) else "等待注册"
    spectator_status = "已有 sessionid" if srs_sid else "无 sessionid（需先运行热点/VPN 模式提取）"
    port = _cfg.get("port", 8002)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI 无配置模式</title>
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
<h1>MahjongAI 无配置模式</h1>
<div class="info">
<b>说明：</b> 利用 SRS 旁观协议直连游戏服务器，手机无需任何配置<br>
<b>端口：</b> <code>{port}</code><br>
<b>api_token：</b> <code>{api_token_display}</code><br>
<b>凭证状态：</b> {credential_status}<br>
<b>SRS Sessionid：</b> {spectator_status}
</div>
<h2>API 端点</h2>
<div class="endpoint"><span class="method">GET</span> <span class="path">/state?token=...</span><span class="desc">查询最新游戏状态（触发 spectator 按需启动）</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/push</span><span class="desc">推送游戏快照（extractor 使用，会停止 spectator）</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/register</span><span class="desc">注册认证凭证（extractor 使用）</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/register-room</span><span class="desc">注册房间（通知 spectator 旁观）</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/watch-info?token=...</span><span class="desc">查询当前旁观房间信息</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/mode</span><span class="desc">模式诊断信息</span></div>
</body></html>"""


# ─── 路由 ────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_build_index_page())


@app.get("/state")
async def get_state(token: str = Query(..., description="鉴权 token")):
    _check_api_token(token)
    _ensure_spectator_running()
    snapshot = _state_store.get_snapshot()
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    snapshot["credential_ready"] = bool(hs and at)
    snapshot["mode"] = "noconfig"
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
        "[NOCONFIG] 已注册凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
        len(req.handshake_blob) // 2,
        len(req.auth_token_12b) // 2,
        "present" if req.srs_sessionid else "absent",
    )

    _persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)
    return {"status": "ok", "message": "凭证已注册", "mode": "noconfig"}


@app.post("/push")
async def push(req: PushRequest):
    _check_api_token(req.api_token)
    was_offline = _state_store.should_use_game_client()
    _state_store.on_push(req.snapshot)
    # extractor 上线时停止 spectator（切换到被动嗅探模式）
    if was_offline:
        _stop_spectator()
    return {"status": "ok", "mode": "noconfig"}


@app.post("/register-room")
async def register_room(req: RegisterRoomRequest):
    _check_api_token(req.api_token)
    _state_store.set_room_info(req.room_id, req.game_id)
    _LOGGER.info("[NOCONFIG] 注册房间: room_id=%d, game_id=%d", req.room_id, req.game_id)
    _notify_spectator(req.room_id, req.game_id)
    return {
        "status": "ok",
        "message": "房间已注册",
        "mode": "noconfig",
        "room_id": req.room_id,
        "game_id": req.game_id,
    }


@app.get("/watch-info")
async def get_watch_info(token: str = Query(..., description="鉴权 token")):
    _check_api_token(token)
    return _state_store.get_room_info()


@app.get("/mode")
async def get_mode():
    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    spectator_alive = (
        _srs_spectator_proc is not None and _srs_spectator_proc.poll() is None
    )
    return {
        "mode": "noconfig",
        "title": "无配置模式 (No-Config / SRS Spectator)",
        "description": "利用 SRS 旁观协议直连游戏服务器，手机无需任何配置。端口 8002",
        "port": _cfg.get("port", 8002),
        "credential_ready": bool(hs and at),
        "has_srs_sessionid": bool(_cfg.get("srs_sessionid")),
        "spectator_running": spectator_alive,
        "spectator_restart_count": _spectator_restart_count,
    }
