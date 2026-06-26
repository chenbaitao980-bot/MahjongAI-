"""
app.py — MahjongAI Noconfig Relay (多用户版)

无配置模式独立 FastAPI app。
职责：包含 noconfig 模式相关端点 + SRS spectator 子进程管理。

端点：
  GET  /               — 状态页（HTML），显示凭证状态 + 用法
  GET  /state?token=&user_id=  — 返回指定用户 snapshot，触发 spectator 按需启动
  POST /register       — 接收 extractor 的 handshake_blob/auth_token_12b/srs_sessionid，创建/更新用户
  POST /push           — 接收 extractor 推送的 snapshot（extractor 上线时停止 spectator）
  GET  /mode           — 模式诊断信息
  POST /register-room  — 接收 roomid/gameid，通知 spectator 开始旁观
  GET  /watch-info     — 返回当前房间信息
  GET  /admin          — 后台管理页面（用户列表 + 搜索 + 手牌展示）
  GET  /api/users      — 获取所有用户列表
  GET  /api/users/search?q= — 按名称搜索用户
  PUT  /api/users/{user_id} — 更新用户名称

设计约束：
  - 使用 UserStore (user_store.py) 管理多用户状态
  - 每个用户独立的 StateStore 和 spectator 进程
  - 向后兼容：不带 user_id 的请求路由到默认用户
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

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
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from state_store import StateStore
from user_store import user_store, User

_LOGGER = logging.getLogger("remote.noconfig.app")

# ─── FastAPI app ────────────────────────────────────────────────

app = FastAPI(title="MahjongAI Noconfig Relay (Multi-User)")

# ─── 运行时配置（由 main.py 注入） ──────────────────────────────

_cfg: dict = {}
_cfg_path: str = ""

# 默认用户（向后兼容单用户模式）
_default_user_id = "default"
_ADMIN_AUTH_COOKIE = "mj_admin_auth"
_ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60
_ADMIN_REMEMBER_TTL_SECONDS = 30 * 24 * 60 * 60


def configure(cfg: dict, cfg_path: str = "") -> None:
    """由 main.py 注入运行时配置。

    将 YAML 配置写入模块级 _cfg / _cfg_path，并把已有的持久化凭证
    预填到默认用户，保证单用户场景开箱即用。
    """
    global _cfg, _cfg_path
    _cfg = cfg or {}
    _cfg_path = cfg_path or ""

    hs = _cfg.get("handshake_blob", "")
    at = _cfg.get("auth_token_12b", "")
    srs_sid = _cfg.get("srs_sessionid", "")
    if hs and at:
        user = _get_or_create_user(_default_user_id, name=_default_user_id)
        user.handshake_blob = hs
        user.auth_token_12b = at
        user.srs_sessionid = srs_sid
        user.userid = _cfg.get("userid", "")
        _LOGGER.info(
            "[NOCONFIG] 默认用户已预填持久化凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
            len(hs) // 2, len(at) // 2, "有" if srs_sid else "无",
        )


# ─── 请求模型 ────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    handshake_blob: str
    auth_token_12b: str
    srs_sessionid: str = ""
    api_token: str
    user_id: str = ""  # 多用户场景下，extractor 推送时带 user_id
    name: str = ""     # 用户显示名称


class PushRequest(BaseModel):
    snapshot: Dict[str, Any]
    api_token: str
    user_id: str = ""  # 多用户场景下，extractor 推送时带 user_id
    srs_sessionid: str = ""  # 游戏服务器下发的 sessionid（hex）


class PresenceRequest(BaseModel):
    """presence 信号：手机进大厅/进游戏时由 ecs_proxy 上报，按 user_id(=numid) 分用户。"""
    api_token: str
    user_id: str  # 用户唯一标识（稳定的 numid）
    name: str = ""  # 玩家昵称（从 PlayerData 解出，可选）
    srs_sessionid: str = ""  # 游戏服务器下发的 sessionid（hex，每次登录变）
    provisional: bool = False
    source_host: str = ""


class RegisterRoomRequest(BaseModel):
    room_id: int
    game_id: int = 0
    api_token: str
    user_id: str = ""  # 多用户场景下，指定用户


class UpdateUserRequest(BaseModel):
    name: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


# ─── 内部工具 ────────────────────────────────────────────────────


def _check_api_token(token: str):
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _admin_username() -> str:
    return str(_cfg.get("admin_username", "") or "").strip()


def _admin_password() -> str:
    return str(_cfg.get("admin_password", "") or "")


def _admin_cookie_secret() -> str:
    return str(_cfg.get("admin_cookie_secret") or _cfg.get("api_token") or "mahjongai-admin-secret")


def _is_admin_configured() -> bool:
    return bool(_admin_username() and _admin_password())


def _make_admin_cookie_value(username: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{username}|{expires_at}"
    signature = hmac.new(
        _admin_cookie_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{signature}".encode("utf-8")).decode("ascii")


def _read_admin_cookie(request: Request) -> Optional[str]:
    raw = request.cookies.get(_ADMIN_AUTH_COOKIE)
    if not raw:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        username, expires_at_text, signature = decoded.split("|", 2)
        payload = f"{username}|{expires_at_text}"
        expected_signature = hmac.new(
            _admin_cookie_secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not secrets.compare_digest(signature, expected_signature):
            return None
        if int(expires_at_text) < int(time.time()):
            return None
        if not secrets.compare_digest(username, _admin_username()):
            return None
        return username
    except Exception:
        return None


def _set_admin_cookie(response: JSONResponse | RedirectResponse, username: str, remember: bool) -> None:
    ttl_seconds = _ADMIN_REMEMBER_TTL_SECONDS if remember else _ADMIN_SESSION_TTL_SECONDS
    response.set_cookie(
        key=_ADMIN_AUTH_COOKIE,
        value=_make_admin_cookie_value(username, ttl_seconds),
        max_age=ttl_seconds if remember else None,
        httponly=True,
        samesite="lax",
    )


def _clear_admin_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(_ADMIN_AUTH_COOKIE, httponly=True, samesite="lax")


def _get_or_create_user(user_id: str, name: str = "") -> "User":
    """获取或创建用户，返回 User 对象"""
    user = user_store.get_user(user_id)
    if user is None:
        user = user_store.add_user(user_id, name or user_id)
    return user


def _get_existing_user_or_404(user_id: str) -> "User":
    """只读接口不要因为查询而重建空壳用户。"""
    user = user_store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


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


def _ensure_spectator_running(user: "User"):
    """检查指定用户的 SRS spectator 子进程健康状态，按需启动。"""
    if not user.state_store.should_use_game_client():
        return

    handshake_hex = user.handshake_blob
    srs_sid = user.srs_sessionid

    if not handshake_hex:
        return

    if not srs_sid or len(srs_sid) < 32:
        _LOGGER.warning("[NOCONFIG] 用户 %s 无 srs_sessionid，无法启动 spectator", user.user_id)
        return

    # 健康检查：如果进程已退出，清理旧进程
    if user.spectator_proc is not None and user.spectator_proc.poll() is not None:
        exit_code = user.spectator_proc.poll()
        _LOGGER.warning("[NOCONFIG] 用户 %s 的 SRS spectator 已退出 (code=%d)，准备重启...", user.user_id, exit_code)
        user.spectator_proc = None
        user.spectator_restart_count += 1

        if user.spectator_restart_count >= 5:  # _SPECTATOR_MAX_RESTARTS
            _LOGGER.error(
                "[NOCONFIG] 用户 %s 的 SRS spectator 已重启 %d 次（上限 5），不再重试",
                user.user_id,
                user.spectator_restart_count,
            )
            return

    # 进程仍在运行则跳过
    if user.spectator_proc is not None and user.spectator_proc.poll() is None:
        return

    _LOGGER.info("[NOCONFIG] 用户 %s extractor 离线，启动 SRS spectator...", user.user_id)
    _start_srs_spectator(user)


def _start_srs_spectator(user: "User"):
    """启动指定用户的 SRS spectator 子进程。"""
    if user.spectator_proc is not None and user.spectator_proc.poll() is None:
        _LOGGER.debug("[NOCONFIG] 用户 %s 的 SRS spectator 已在运行中 (pid=%d)", user.user_id, user.spectator_proc.pid)
        return

    user.spectator_restart_count += 1
    if user.spectator_restart_count > 5:  # _SPECTATOR_MAX_RESTARTS
        _LOGGER.error(
            "[NOCONFIG] 用户 %s 的 SRS spectator 重启次数超限 (%d/5)，不再启动",
            user.user_id,
            user.spectator_restart_count,
        )
        return

    auth_hex = user.auth_token_12b
    api_token = _cfg.get("api_token", "")
    relay_url = f"http://127.0.0.1:{_cfg.get('port', 8002)}"
    bind_port_str = "8003"  # spectator 固定监听 8003，与 srs_spectator/main.py BIND_PORT 一致
    userid = _cfg.get("userid", "newpt1084306678")

    env = os.environ.copy()
    env["AUTH_TOKEN_12B"] = auth_hex
    env["HANDSHAKE_BLOB"] = user.handshake_blob
    env["SRS_SESSIONID"] = user.srs_sessionid
    env["RELAY_URL"] = relay_url
    env["API_TOKEN"] = api_token
    env["USERID"] = userid
    env["BIND_PORT"] = bind_port_str
    env["PYTHONPATH"] = os.pathsep.join([_ROOT, os.path.join(_ROOT, "remote", "srs_spectator")])

    spectator_main = os.path.join(_ROOT, "remote", "srs_spectator", "main.py")
    log_path = os.path.join(_ROOT, "logs", f"srs_spectator_{user.user_id}.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        user.spectator_proc = subprocess.Popen(
            [sys.executable, spectator_main],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=_ROOT,
        )
        _LOGGER.info(
            "[NOCONFIG] 用户 %s 的 SRS spectator 子进程已启动 (pid=%d, log=%s)",
            user.user_id,
            user.spectator_proc.pid,
            log_path,
        )
    except Exception as exc:
        _LOGGER.error("[NOCONFIG] 启动用户 %s 的 SRS spectator 失败: %s", user.user_id, exc)


def _stop_spectator(user: "User"):
    """停止指定用户的 SRS spectator 子进程（extractor 上线时调用）"""
    if user.spectator_proc is not None and user.spectator_proc.poll() is None:
        user.spectator_proc.terminate()
        try:
            user.spectator_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            user.spectator_proc.kill()
        user.spectator_proc = None
        _LOGGER.info("[NOCONFIG] 用户 %s 的 SRS spectator 已停止（extractor 上线）", user.user_id)


def _notify_spectator(user: "User", room_id: int, game_id: int):
    """通知指定用户的 SRS spectator 服务开始旁观（异步线程，不阻塞请求）"""
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
                    "[NOCONFIG] 已通知用户 %s 的 spectator: room_id=%d, game_id=%d", user.user_id, room_id, game_id
                )
            else:
                _LOGGER.warning(
                    "[NOCONFIG] 用户 %s 的 spectator 通知失败: %d %s", user.user_id, resp.status_code, resp.text
                )
        except Exception as e:
            _LOGGER.debug("[NOCONFIG] 用户 %s 的 spectator 通知异常: %s", user.user_id, e)

    threading.Thread(target=_do_notify, daemon=True).start()


# ─── 路由 ────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    """首页 — 重定向到 /admin"""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>MahjongAI 无配置模式</title>
<meta http-equiv="refresh" content="0;url=/admin">
</head>
<body><p>正在跳转到 <a href="/admin">管理页面</a>...</p></body>
</html>""")


@app.get("/state")
async def get_state(
    token: str = Query(..., description="鉴权 token"),
    user_id: str = Query("", description="用户 ID（可选，默认使用 default 用户）"),
):
    _check_api_token(token)

    # 向后兼容：如果未提供 user_id，使用默认用户
    target_user_id = user_id or _default_user_id
    user = _get_existing_user_or_404(target_user_id)

    _ensure_spectator_running(user)
    snapshot = user.get_snapshot()
    snapshot["mode"] = "noconfig"
    snapshot["user_id"] = user.user_id
    snapshot["user_name"] = user.name
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

    # 多用户：根据 user_id 创建或更新用户
    target_user_id = req.user_id or _default_user_id
    user = user_store.add_user(
        target_user_id,
        name=req.name or target_user_id,
        srs_sessionid=req.srs_sessionid,
        handshake_blob=req.handshake_blob,
        auth_token_12b=req.auth_token_12b,
    )

    _persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)

    _LOGGER.info(
        "[NOCONFIG] 已注册用户 %s: hs=%d bytes, auth=%d bytes, srs_sid=%s",
        user.user_id,
        len(req.handshake_blob) // 2,
        len(req.auth_token_12b) // 2,
        "present" if req.srs_sessionid else "absent",
    )

    return {"status": "ok", "message": "凭证已注册", "mode": "noconfig", "user_id": user.user_id}


def _auto_fill_credentials(user: "User", fallback_srs_sid: str = "") -> None:
    """如果用户缺少凭证，自动从 default 用户复制 handshake/auth，srs_sessionid 用 user_id 或 fallback"""
    if user.handshake_blob and user.auth_token_12b and user.srs_sessionid:
        return  # 凭证齐全，无需操作
    default_user = user_store.get_user(_default_user_id)
    if not default_user or not default_user.handshake_blob or not default_user.auth_token_12b:
        return  # default 也没有凭证
    srs_sid = fallback_srs_sid or user.user_id
    if user.user_id == _default_user_id:
        srs_sid = default_user.srs_sessionid  # default 用户保留自己的 srs_sessionid
    user.update_credentials(
        handshake_blob=default_user.handshake_blob,
        auth_token_12b=default_user.auth_token_12b,
        srs_sessionid=srs_sid,
    )
    _LOGGER.info("[NOCONFIG] 自动补全凭证给用户 %s (srs_sid=%s)", user.user_id, srs_sid[:16] if srs_sid else "none")


@app.post("/push")
async def push(req: PushRequest):
    _check_api_token(req.api_token)

    # 多用户：根据 user_id 路由到对应用户
    target_user_id = req.user_id or _default_user_id
    user = user_store.get_user(target_user_id)
    if user is None:
        # 自动创建用户（如果 extractor 推送时用户不存在）
        user = user_store.add_user(target_user_id, name=target_user_id)
    # 确保用户有凭证（重启后用户可能丢失凭证），用 push 里的 sessionid
    _auto_fill_credentials(user, fallback_srs_sid=req.srs_sessionid or target_user_id)

    was_offline = user.state_store.should_use_game_client()
    user.on_push(req.snapshot)
    # extractor 上线时停止 spectator（切换到被动嗅探模式）
    if was_offline:
        _stop_spectator(user)
    return {"status": "ok", "mode": "noconfig", "user_id": user.user_id}


@app.post("/presence")
async def presence(req: PresenceRequest):
    """presence 上报：手机进大厅/进游戏时由 ecs_proxy 调用，按 user_id(srs_sessionid) 标记在线。

    与 /push 的区别：presence 不带手牌快照，仅标记"该用户当前活跃"，用于
    "进大厅即显示在线"。手牌数据仍走 /push（依赖 0x2bc0 解码）。
    """
    _check_api_token(req.api_token)
    if req.provisional:
        user = _get_or_create_user(req.user_id, name=req.name or req.user_id)
        if req.name:
            user.name = req.name
        user.mark_provisional(req.source_host)
        user.touch_presence()
        _LOGGER.info(
            "[NOCONFIG] provisional presence: user=%s source=%s name=%s",
            user.user_id,
            req.source_host or "-",
            user.name,
        )
        return {"status": "ok", "mode": "noconfig", "user_id": user.user_id, "online": True}

    if req.source_host:
        user_store.remove_provisional_by_source(req.source_host)
    user = _get_or_create_user(req.user_id, name=req.name)
    user.clear_provisional()
    # 若带了更可信的昵称（PlayerData 解出），更新显示名
    if req.name and user.name in ("", user.user_id):
        user.name = req.name
    # 自动补全凭证（从 default 复制 handshake/auth，srs_sessionid 用 presence 里的）
    _auto_fill_credentials(user, fallback_srs_sid=req.srs_sessionid or req.user_id)
    user.touch_presence()
    _LOGGER.info("[NOCONFIG] presence: user=%s name=%s 标记在线", user.user_id, user.name)
    return {"status": "ok", "mode": "noconfig", "user_id": user.user_id, "online": True}


@app.post("/register-room")
async def register_room(req: RegisterRoomRequest):
    _check_api_token(req.api_token)

    target_user_id = req.user_id or _default_user_id
    user = _get_existing_user_or_404(target_user_id)

    user.set_room_info(req.room_id, req.game_id)
    _LOGGER.info("[NOCONFIG] 用户 %s 注册房间: room_id=%d, game_id=%d", user.user_id, req.room_id, req.game_id)
    _notify_spectator(user, req.room_id, req.game_id)
    return {
        "status": "ok",
        "message": "房间已注册",
        "mode": "noconfig",
        "user_id": user.user_id,
        "room_id": req.room_id,
        "game_id": req.game_id,
    }


@app.get("/watch-info")
async def get_watch_info(
    token: str = Query(..., description="鉴权 token"),
    user_id: str = Query("", description="用户 ID（可选）"),
):
    _check_api_token(token)
    target_user_id = user_id or _default_user_id
    user = _get_existing_user_or_404(target_user_id)
    return user.get_room_info()


@app.get("/mode")
async def get_mode():
    total_users = user_store.get_user_count()
    online_users = len(user_store.get_online_users())
    return {
        "mode": "noconfig",
        "title": "无配置模式 (No-Config / SRS Spectator) — 多用户版",
        "description": "利用 SRS 旁观协议直连游戏服务器，手机无需任何配置。端口 8002",
        "port": _cfg.get("port", 8002),
        "total_users": total_users,
        "online_users": online_users,
    }


# ─── Admin API ─────────────────────────────────────────────────

@app.get("/api/users")
async def get_users(token: str = Query(..., description="鉴权 token")):
    """获取所有用户列表"""
    _check_api_token(token)
    return {
        "status": "ok",
        "users": user_store.get_all_users(),
        "total": user_store.get_user_count(),
    }


@app.get("/api/users/search")
async def search_users(
    token: str = Query(..., description="鉴权 token"),
    q: str = Query(..., description="搜索关键词"),
):
    """按名称搜索用户"""
    _check_api_token(token)
    return {
        "status": "ok",
        "users": user_store.search_users(q),
        "query": q,
    }


@app.put("/api/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, token: str = Query(..., description="鉴权 token")):
    """更新用户名称"""
    _check_api_token(token)
    user = user_store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.name = req.name
    user.updated_at = __import__("time").time()
    return {"status": "ok", "user": user.to_dict()}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, token: str = Query(..., description="鉴权 token")):
    """删除用户"""
    _check_api_token(token)
    if user_store.remove_user(user_id):
        return {"status": "ok", "message": f"用户 {user_id} 已删除"}
    raise HTTPException(status_code=404, detail="用户不存在")


# ─── Admin Page ─────────────────────────────────────────────────

@app.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    if not _is_admin_configured():
        raise HTTPException(status_code=503, detail="admin login is not configured")

    if not (
        secrets.compare_digest(req.username, _admin_username())
        and secrets.compare_digest(req.password, _admin_password())
    ):
        _LOGGER.warning("[NOCONFIG] admin login failed for user=%s", req.username)
        raise HTTPException(status_code=401, detail="invalid username or password")

    response = JSONResponse({"status": "ok", "username": req.username})
    _set_admin_cookie(response, req.username, req.remember)
    _LOGGER.info("[NOCONFIG] admin login success for user=%s remember=%s", req.username, req.remember)
    return response


@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    _clear_admin_cookie(response)
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """后台管理页面 — 用户列表 + 搜索 + 手牌展示"""
    if not _is_admin_configured():
        return HTMLResponse(content=_build_admin_login_page(config_error="未配置后台账号密码"), status_code=503)

    username = _read_admin_cookie(request)
    if not username:
        return HTMLResponse(content=_build_admin_login_page())

    return HTMLResponse(content=_build_admin_page(username=username, api_token=_cfg.get("api_token", "")))


def _build_admin_login_page(config_error: str = "") -> str:
    error_json = json.dumps(config_error, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI Admin Login</title>
<style>
:root {{ --bg: #0f1115; --panel: #1a1d24; --panel2: #232733; --txt: #e8eaed; --muted: #9aa0ab; --line: #333947; --accent: #f5b301; --danger: #ef4444; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: radial-gradient(circle at top, #1f2431 0%, #0f1115 55%); color: var(--txt); font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
.card {{ width: min(420px, calc(100vw - 32px)); background: rgba(26, 29, 36, 0.96); border: 1px solid var(--line); border-radius: 16px; padding: 28px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35); }}
h1 {{ margin: 0 0 8px; font-size: 24px; }}
p {{ margin: 0 0 20px; color: var(--muted); font-size: 14px; line-height: 1.6; }}
label {{ display: block; margin: 14px 0 6px; font-size: 13px; color: var(--muted); }}
input[type="text"], input[type="password"] {{ width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--panel2); color: var(--txt); padding: 12px 14px; font-size: 14px; }}
.row {{ display: flex; align-items: center; justify-content: space-between; margin-top: 14px; gap: 12px; }}
.remember {{ display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; }}
button {{ width: 100%; margin-top: 18px; border: none; border-radius: 10px; background: var(--accent); color: #111; padding: 12px 14px; font-size: 14px; font-weight: 700; cursor: pointer; }}
button:disabled {{ opacity: 0.7; cursor: wait; }}
.error {{ min-height: 20px; margin-top: 14px; color: var(--danger); font-size: 13px; }}
</style>
</head>
<body>
  <div class="card">
    <h1>MahjongAI 后台登录</h1>
    <p>登录后进入无配置模式后台。勾选“记住我”后，下次访问无需重新输入账号密码。</p>
    <label for="username">账号</label>
    <input id="username" type="text" autocomplete="username" />
    <label for="password">密码</label>
    <input id="password" type="password" autocomplete="current-password" />
    <div class="row">
      <label class="remember"><input id="remember" type="checkbox" checked />记住我</label>
    </div>
    <button id="login-btn" type="button" onclick="login()">登录</button>
    <div class="error" id="error"></div>
  </div>
<script>
const initialError = {error_json};
if (initialError) {{
  document.getElementById('error').textContent = initialError;
}}
async function login() {{
  const btn = document.getElementById('login-btn');
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const remember = document.getElementById('remember').checked;
  const errorEl = document.getElementById('error');
  errorEl.textContent = '';
  if (!username || !password) {{
    errorEl.textContent = '请输入账号和密码';
    return;
  }}
  btn.disabled = true;
  btn.textContent = '登录中...';
  try {{
    const r = await fetch('/admin/login', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ username, password, remember }}),
    }});
    const data = await r.json().catch(() => ({{}}));
    if (!r.ok) {{
      errorEl.textContent = data.detail || '登录失败';
      return;
    }}
    window.location.href = '/admin';
  }} catch (e) {{
    errorEl.textContent = '网络异常，请稍后重试';
  }} finally {{
    btn.disabled = false;
    btn.textContent = '登录';
  }}
}}
document.getElementById('password').addEventListener('keydown', (e) => {{
  if (e.key === 'Enter') login();
}});
</script>
</body>
</html>"""


def _build_admin_page(username: str, api_token: str) -> str:
    """构建后台管理页面 HTML"""
    username_json = json.dumps(username, ensure_ascii=False)
    api_token_json = json.dumps(api_token)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI 多用户管理</title>
<style>
:root {{ --bg: #0f1115; --panel: #1a1d24; --panel2: #232733; --txt: #e8eaed; --muted: #9aa0ab; --line: #333947; --accent: #f5b301; --man: #c0392b; --pin: #2563c9; --sou: #1e9e5a; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--txt); font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
header {{ display: flex; align-items: center; gap: 12px; padding: 12px 20px; background: var(--panel); border-bottom: 1px solid var(--line); }}
header h1 {{ font-size: 18px; margin: 0; font-weight: 600; }}
header .stats {{ margin-left: auto; font-size: 13px; color: var(--muted); }}
.container {{ display: flex; height: calc(100vh - 60px); }}
.sidebar {{ width: 320px; min-width: 320px; border-right: 1px solid var(--line); display: flex; flex-direction: column; }}
.search-box {{ padding: 12px 16px; border-bottom: 1px solid var(--line); }}
.search-box input {{ width: 100%; background: var(--panel2); border: 1px solid var(--line); color: var(--txt); padding: 8px 12px; border-radius: 6px; font-size: 13px; }}
.user-list {{ flex: 1; overflow-y: auto; padding: 8px; }}
.user-item {{ padding: 10px 12px; margin: 4px 0; border-radius: 6px; cursor: pointer; transition: background 0.2s; }}
.user-item:hover {{ background: var(--panel2); }}
.user-item.active {{ background: var(--panel2); border-left: 3px solid var(--accent); }}
.user-item .name {{ font-weight: 600; font-size: 14px; }}
.user-item .id {{ font-size: 12px; color: var(--muted); }}
.user-item .status {{ font-size: 11px; margin-top: 4px; }}
.user-item .status.online {{ color: var(--sou); }}
.user-item .status.offline {{ color: var(--muted); }}
.main {{ flex: 1; padding: 20px; overflow-y: auto; }}
.toolbar {{ padding: 8px 16px; background: var(--panel2); border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.toolbar .meta {{ font-size: 12px; color: var(--muted); }}
.toolbar .actions {{ display: flex; gap: 8px; }}
.toolbar button, .toolbar a {{ background: var(--accent); color: #000; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; text-decoration: none; }}
iframe {{ width: 100%; height: calc(100vh - 140px); border: none; }}
</style>
</head>
<body>
<header>
  <h1>🀄 MahjongAI 多用户管理</h1>
  <span class="stats">总用户: <b id="total-users">0</b> | 在线: <b id="online-users">0</b></span>
</header>
<div class="container">
  <div class="sidebar">
    <div class="search-box">
      <input id="search-input" placeholder="搜索用户名称..." autocomplete="off">
    </div>
    <div class="user-list" id="user-list">
      <!-- 用户列表由 JS 动态填充 -->
    </div>
  </div>
  <div class="main">
    <div class="toolbar">
      <div class="meta">已登录账号: <span id="current-admin"></span></div>
      <div class="actions">
        <button onclick="refreshUsers()">刷新</button>
        <a href="/admin/logout">退出登录</a>
      </div>
    </div>
    <iframe id="hand-frame" src="about:blank"></iframe>
  </div>
</div>

<script>
let currentUserId = null;
const apiToken = {api_token_json};
document.getElementById('current-admin').textContent = {username_json};

document.getElementById('search-input').addEventListener('input', (e) => {{
  const q = e.target.value.trim();
  if (q) {{
    searchUsers(q);
  }} else {{
    refreshUsers();
  }}
}});

async function refreshUsers() {{
  if (!apiToken) return;
  try {{
    const r = await fetch('/api/users?token=' + encodeURIComponent(apiToken));
    if (!r.ok) {{ console.error('获取用户列表失败:', r.status); return; }}
    const data = await r.json();
    renderUserList(data.users || []);
    if (!currentUserId) {{
      const preferred = (data.users || []).find(u => u.is_online && u.user_id !== 'default')
        || (data.users || []).find(u => u.is_online)
        || (data.users || [])[0];
      if (preferred) selectUser(preferred.user_id);
    }}
    document.getElementById('total-users').textContent = data.total || 0;
    const online = (data.users || []).filter(u => u.is_online).length;
    document.getElementById('online-users').textContent = online;
  }} catch (e) {{ console.error('刷新用户失败:', e); }}
}}

async function searchUsers(q) {{
  if (!apiToken) return;
  try {{
    const r = await fetch('/api/users/search?token=' + encodeURIComponent(apiToken) + '&q=' + encodeURIComponent(q));
    if (!r.ok) return;
    const data = await r.json();
    renderUserList(data.users || []);
  }} catch (e) {{ console.error('搜索用户失败:', e); }}
}}

function renderUserList(users) {{
  const container = document.getElementById('user-list');
  if (!users.length) {{ container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">暂无用户</div>'; return; }}
  container.innerHTML = users.map(u => `
    <div class="user-item ${{currentUserId === u.user_id ? 'active' : ''}}" data-id="${{u.user_id}}" onclick="selectUser('${{u.user_id}}')">
      <div class="name">${{escapeHtml(u.name || u.user_id)}}</div>
      <div class="id">ID: ${{escapeHtml(u.user_id)}}</div>
      <div class="status ${{u.is_online ? 'online' : 'offline'}}">${{u.is_online ? '● 在线' : '○ 离线' + formatLastSeen(u.last_seen_ago)}}</div>
    </div>
  `).join('');
}}

function formatLastSeen(agoSecs) {{
  if (agoSecs == null) return ' · 从未在线';
  const s = Math.floor(agoSecs);
  if (s < 60) return ' · ' + s + ' 秒前在线';
  const m = Math.floor(s / 60);
  if (m < 60) return ' · ' + m + ' 分钟前在线';
  const h = Math.floor(m / 60);
  if (h < 24) return ' · ' + h + ' 小时前在线';
  return ' · ' + Math.floor(h / 24) + ' 天前在线';
}}

function selectUser(userId) {{
  currentUserId = userId;
  document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
  document.querySelector('.user-item[data-id="' + userId + '"]')?.classList.add('active');
  const frame = document.getElementById('hand-frame');
  frame.src = '/static/index.html?token=' + encodeURIComponent(apiToken) + '&user_id=' + encodeURIComponent(userId) + '&v=' + Date.now();
}}

function escapeHtml(text) {{
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}}

setInterval(refreshUsers, 5000);
refreshUsers();
</script>
</body>
</html>"""


# ─── Static Files ──────────────────────────────────────────────

# 挂载静态文件目录（手牌展示页面）
static_dir = os.path.join(_ROOT, "remote", "relay", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
