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

import logging
import os
import subprocess
import sys
import threading
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
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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


class RegisterRoomRequest(BaseModel):
    room_id: int
    game_id: int = 0
    api_token: str
    user_id: str = ""  # 多用户场景下，指定用户


class UpdateUserRequest(BaseModel):
    name: str


# ─── 内部工具 ────────────────────────────────────────────────────


def _check_api_token(token: str):
    expected = _cfg.get("api_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="无效 api_token")


def _get_or_create_user(user_id: str, name: str = "") -> "User":
    """获取或创建用户，返回 User 对象"""
    user = user_store.get_user(user_id)
    if user is None:
        user = user_store.add_user(user_id, name or user_id)
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
    user = _get_or_create_user(target_user_id)

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


@app.post("/push")
async def push(req: PushRequest):
    _check_api_token(req.api_token)

    # 多用户：根据 user_id 路由到对应用户
    target_user_id = req.user_id or _default_user_id
    user = user_store.get_user(target_user_id)
    if user is None:
        # 自动创建用户（如果 extractor 推送时用户不存在）
        user = user_store.add_user(target_user_id, name=target_user_id)

    was_offline = user.state_store.should_use_game_client()
    user.on_push(req.snapshot)
    # extractor 上线时停止 spectator（切换到被动嗅探模式）
    if was_offline:
        _stop_spectator(user)
    return {"status": "ok", "mode": "noconfig", "user_id": user.user_id}


@app.post("/register-room")
async def register_room(req: RegisterRoomRequest):
    _check_api_token(req.api_token)

    target_user_id = req.user_id or _default_user_id
    user = _get_or_create_user(target_user_id)

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
    user = _get_or_create_user(target_user_id)
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

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """后台管理页面 — 用户列表 + 搜索 + 手牌展示"""
    return HTMLResponse(content=_build_admin_page())


def _build_admin_page() -> str:
    """构建后台管理页面 HTML"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MahjongAI 多用户管理</title>
<style>
:root { --bg: #0f1115; --panel: #1a1d24; --panel2: #232733; --txt: #e8eaed; --muted: #9aa0ab; --line: #333947; --accent: #f5b301; --man: #c0392b; --pin: #2563c9; --sou: #1e9e5a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--txt); font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
header { display: flex; align-items: center; gap: 12px; padding: 12px 20px; background: var(--panel); border-bottom: 1px solid var(--line); }
header h1 { font-size: 18px; margin: 0; font-weight: 600; }
header .stats { margin-left: auto; font-size: 13px; color: var(--muted); }
.container { display: flex; height: calc(100vh - 60px); }
.sidebar { width: 320px; min-width: 320px; border-right: 1px solid var(--line); display: flex; flex-direction: column; }
.search-box { padding: 12px 16px; border-bottom: 1px solid var(--line); }
.search-box input { width: 100%; background: var(--panel2); border: 1px solid var(--line); color: var(--txt); padding: 8px 12px; border-radius: 6px; font-size: 13px; }
.user-list { flex: 1; overflow-y: auto; padding: 8px; }
.user-item { padding: 10px 12px; margin: 4px 0; border-radius: 6px; cursor: pointer; transition: background 0.2s; }
.user-item:hover { background: var(--panel2); }
.user-item.active { background: var(--panel2); border-left: 3px solid var(--accent); }
.user-item .name { font-weight: 600; font-size: 14px; }
.user-item .id { font-size: 12px; color: var(--muted); }
.user-item .status { font-size: 11px; margin-top: 4px; }
.user-item .status.online { color: var(--sou); }
.user-item .status.offline { color: var(--muted); }
.main { flex: 1; padding: 20px; overflow-y: auto; }
.empty-state { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--muted); font-size: 14px; }
.token-bar { padding: 8px 16px; background: var(--panel2); border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px; }
.token-bar input { flex: 1; background: var(--bg); border: 1px solid var(--line); color: var(--txt); padding: 6px 10px; border-radius: 4px; font-size: 12px; }
.token-bar button { background: var(--accent); color: #000; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; }
iframe { width: 100%; height: calc(100vh - 140px); border: none; }
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
    <div class="token-bar">
      <span style="font-size:12px;color:var(--muted)">Token:</span>
      <input id="token-input" placeholder="输入 api_token" value="">
      <button onclick="refreshUsers()">刷新</button>
    </div>
    <iframe id="hand-frame" src="about:blank"></iframe>
  </div>
</div>

<script>
let currentUserId = null;
let apiToken = localStorage.getItem('mj_admin_token') || '';
document.getElementById('token-input').value = apiToken;
document.getElementById('token-input').addEventListener('change', (e) => {
  apiToken = e.target.value.trim();
  localStorage.setItem('mj_admin_token', apiToken);
  refreshUsers();
});

document.getElementById('search-input').addEventListener('input', (e) => {
  const q = e.target.value.trim();
  if (q) {
    searchUsers(q);
  } else {
    refreshUsers();
  }
});

async function refreshUsers() {
  if (!apiToken) return;
  try {
    const r = await fetch('/api/users?token=' + encodeURIComponent(apiToken));
    if (!r.ok) { console.error('获取用户列表失败:', r.status); return; }
    const data = await r.json();
    renderUserList(data.users || []);
    document.getElementById('total-users').textContent = data.total || 0;
    const online = (data.users || []).filter(u => u.is_online).length;
    document.getElementById('online-users').textContent = online;
  } catch (e) { console.error('刷新用户失败:', e); }
}

async function searchUsers(q) {
  if (!apiToken) return;
  try {
    const r = await fetch('/api/users/search?token=' + encodeURIComponent(apiToken) + '&q=' + encodeURIComponent(q));
    if (!r.ok) return;
    const data = await r.json();
    renderUserList(data.users || []);
  } catch (e) { console.error('搜索用户失败:', e); }
}

function renderUserList(users) {
  const container = document.getElementById('user-list');
  if (!users.length) { container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">暂无用户</div>'; return; }
  container.innerHTML = users.map(u => `
    <div class="user-item ${currentUserId === u.user_id ? 'active' : ''}" data-id="${u.user_id}" onclick="selectUser('${u.user_id}'">
      <div class="name">${escapeHtml(u.name || u.user_id)}</div>
      <div class="id">ID: ${escapeHtml(u.user_id)}</div>
      <div class="status ${u.is_online ? 'online' : 'offline'}">${u.is_online ? '● 在线' : '○ 离线'}</div>
    </div>
  `).join('');
}

function selectUser(userId) {
  currentUserId = userId;
  document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
  document.querySelector('.user-item[data-id="' + userId + '"]')?.classList.add('active');
  // 加载该用户的手牌页面
  const frame = document.getElementById('hand-frame');
  frame.src = '/static/index.html?token=' + encodeURIComponent(apiToken) + '&user_id=' + encodeURIComponent(userId);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 自动刷新
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
