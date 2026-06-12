"""
core.py — RelayApp: 每个模式独立的 relay 实例

每种手牌读取模式（热点/VPN/无配置）各自创建一个 RelayApp 实例，
拥有独立的 StateStore、FastAPI app、端口和配置，三者互不影响。

模式对应的端口：
  8000 — 热点模式 (shared hotspot)
  8001 — VPN模式 (phone VPN)
  8002 — 无配置模式 (no-config / SRS spectator)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

# 确保 relay 目录在 sys.path 中，支持从项目根目录或 relay 目录直接导入
_RELAY_DIR = os.path.dirname(os.path.abspath(__file__))
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)

import requests
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from state_store import StateStore

_LOGGER = logging.getLogger("remote.relay.core")

# ─── 请求/响应模型 ─────────────────────────────────────────────


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


# ─── RelayApp 类 ────────────────────────────────────────────────


class RelayApp:
    """独立的 relay 实例：拥有自己的 FastAPI app 和 StateStore"""

    def __init__(
        self,
        cfg: dict,
        cfg_path: str = "",
        mode: str = "unknown",
        port: int = 8000,
    ):
        self._mode = mode
        self._port = port
        self._cfg = dict(cfg)
        self._cfg_path = cfg_path
        self._state_store = StateStore()
        self._srs_spectator_proc = None
        self._spectator_restart_count = 0
        self._SPECTATOR_MAX_RESTARTS = 5
        self._spectator_url = cfg.get("spectator_url", "")

        # 设置 push_timeout
        push_timeout = float(cfg.get("push_timeout", 10.0))
        self._state_store.push_timeout = push_timeout

        # 创建 FastAPI app
        title = self._mode_title()
        self.app = FastAPI(title=f"MahjongAI Relay - {title}")
        self._register_routes()

        _LOGGER.info("[%s] RelayApp 已创建: port=%d, push_timeout=%.1fs, spectator_url=%s",
                     mode.upper(), port, push_timeout,
                     self._spectator_url or "(not set)")

        # noconfig 模式：如果已有 srs_sessionid，启动后自动启动 spectator
        if mode == "noconfig":
            srs_sid = cfg.get("srs_sessionid", "")
            hs = cfg.get("handshake_blob", "")
            if srs_sid and len(srs_sid) >= 32 and hs:
                _LOGGER.info("[%s] 已有 SRS 凭证，将在服务启动后自动启动 spectator", mode.upper())

                @self.app.on_event("startup")
                async def _auto_start_spectator():
                    _LOGGER.info("[%s] 自动启动 spectator...", mode.upper())
                    self._ensure_spectator_running()

    # ─── 模式元信息 ──────────────────────────────────────────────

    MODE_TITLES = {
        "hotspot": "热点模式 (Hotspot)",
        "vpn": "VPN模式 (Phone VPN)",
        "noconfig": "无配置模式 (No-Config / SRS Spectator)",
    }
    MODE_DESCRIPTIONS = {
        "hotspot": "手机连PC共享热点，PC抓包推送到云端。端口 8000",
        "vpn": "手机配置IPSec VPN连云端，云端抓包。端口 8001",
        "noconfig": "利用SRS旁观协议直连游戏服务器，手机无需任何配置。端口 8002",
    }

    def _mode_title(self):
        return self.MODE_TITLES.get(self._mode, self._mode.upper())

    # ─── 配置注入 ────────────────────────────────────────────────

    def update_config(self, cfg: dict, cfg_path: str = ""):
        """运行时更新配置（如 extractor 注册新凭证后）"""
        self._cfg.update(cfg)
        if cfg_path:
            self._cfg_path = cfg_path

    # ─── 路由注册 ────────────────────────────────────────────────

    def _register_routes(self):
        """注册所有路由"""

        # ── 首页（手牌展示） ──
        @self.app.get("/")
        async def index():
            return HTMLResponse(content=self._build_hand_display_page())

        # ── 状态查询 ──
        @self.app.get("/state")
        async def get_state(token: str = Query(..., description="鉴权 token")):
            self._check_api_token(token)
            self._ensure_spectator_running()
            snapshot = self._state_store.get_snapshot()
            hs = self._cfg.get("handshake_blob", "")
            at = self._cfg.get("auth_token_12b", "")
            snapshot["credential_ready"] = bool(hs and at)
            snapshot["mode"] = self._mode
            return snapshot

        # ── 凭证注册 ──
        @self.app.post("/register")
        async def register(req: RegisterRequest):
            self._check_api_token(req.api_token)
            try:
                bytes.fromhex(req.handshake_blob)
                bytes.fromhex(req.auth_token_12b)
                if req.srs_sessionid:
                    bytes.fromhex(req.srs_sessionid)
            except ValueError:
                raise HTTPException(status_code=400, detail="凭证格式错误（需要十六进制字符串）")

            self._cfg["handshake_blob"] = req.handshake_blob
            self._cfg["auth_token_12b"] = req.auth_token_12b
            if req.srs_sessionid:
                self._cfg["srs_sessionid"] = req.srs_sessionid

            _LOGGER.info("[%s] 已注册凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
                         self._mode.upper(),
                         len(req.handshake_blob) // 2,
                         len(req.auth_token_12b) // 2,
                         "present" if req.srs_sessionid else "absent")

            self._persist_credentials(req.handshake_blob, req.auth_token_12b, req.srs_sessionid)
            return {"status": "ok", "message": "凭证已注册", "mode": self._mode}

        # ── 快照推送 ──
        @self.app.post("/push")
        async def push(req: PushRequest):
            self._check_api_token(req.api_token)
            self._state_store.on_push(req.snapshot)
            return {"status": "ok", "mode": self._mode}

        # ── 房间注册（通道B，无配置模式专用）──
        @self.app.post("/register-room")
        async def register_room(req: RegisterRoomRequest):
            self._check_api_token(req.api_token)
            self._state_store.set_room_info(req.room_id, req.game_id)
            _LOGGER.info("[%s] 注册房间: room_id=%d, game_id=%d",
                         self._mode.upper(), req.room_id, req.game_id)
            self._notify_spectator(req.room_id, req.game_id)
            return {"status": "ok", "message": "房间已注册", "mode": self._mode,
                    "room_id": req.room_id, "game_id": req.game_id}

        # ── 旁观信息查询 ──
        @self.app.get("/watch-info")
        async def get_watch_info(token: str = Query(..., description="鉴权 token")):
            self._check_api_token(token)
            return self._state_store.get_room_info()

        # ── 模式信息（诊断用）──
        @self.app.get("/mode")
        async def get_mode():
            return {
                "mode": self._mode,
                "title": self._mode_title(),
                "description": self.MODE_DESCRIPTIONS.get(self._mode, ""),
                "port": self._port,
                "credential_ready": bool(self._cfg.get("handshake_blob") and self._cfg.get("auth_token_12b")),
                "has_srs_sessionid": bool(self._cfg.get("srs_sessionid")),
            }

    # ─── 内部辅助 ──────────────────────────────────────────────────

    def _check_api_token(self, token: str):
        expected = self._cfg.get("api_token", "")
        if not expected or token != expected:
            raise HTTPException(status_code=401, detail="无效 api_token")

    def _ensure_spectator_running(self):
        """无配置模式：extractor 离线时启动 SRS spectator

        包含子进程健康检查和重启限制：
        - 如果子进程已退出（poll() 返回非 None），清理并重启
        - 超过最大重启次数则不再尝试
        """
        if not self._state_store.should_use_game_client():
            return

        handshake_hex = self._cfg.get("handshake_blob", "")
        srs_sid = self._cfg.get("srs_sessionid", "")

        if not handshake_hex:
            return

        if not srs_sid or len(srs_sid) < 32:
            _LOGGER.debug("[%s] extractor 离线但无 srs_sessionid，无法启动 spectator",
                          self._mode.upper())
            return

        # 健康检查：如果进程已退出，清理旧进程
        if self._srs_spectator_proc is not None and self._srs_spectator_proc.poll() is not None:
            exit_code = self._srs_spectator_proc.poll()
            _LOGGER.warning("[%s] SRS spectator 已退出 (code=%d)，准备重启...",
                           self._mode.upper(), exit_code)
            self._srs_spectator_proc = None

            if self._spectator_restart_count >= self._SPECTATOR_MAX_RESTARTS:
                _LOGGER.error("[%s] SRS spectator 已重启 %d 次（上限 %d），不再重试",
                             self._mode.upper(), self._spectator_restart_count,
                             self._SPECTATOR_MAX_RESTARTS)
                return

        # 进程仍在运行则跳过
        if self._srs_spectator_proc is not None and self._srs_spectator_proc.poll() is None:
            return

        _LOGGER.info("[%s] extractor 离线，启动 SRS spectator...", self._mode.upper())
        self._start_srs_spectator(handshake_hex, srs_sid)

    def _start_srs_spectator(self, handshake_hex: str, srs_sid: str):
        """启动 SRS spectator 子进程（无配置模式专用）

        仅在进程不存在时启动，已有运行进程则跳过。
        启动后递增重启计数器。
        """
        if self._srs_spectator_proc is not None and self._srs_spectator_proc.poll() is None:
            _LOGGER.debug("[%s] SRS spectator 已在运行中 (pid=%d)",
                         self._mode.upper(), self._srs_spectator_proc.pid)
            return

        self._spectator_restart_count += 1
        if self._spectator_restart_count > self._SPECTATOR_MAX_RESTARTS:
            _LOGGER.error("[%s] SRS spectator 重启次数超限 (%d/%d)，不再启动",
                         self._mode.upper(), self._spectator_restart_count,
                         self._SPECTATOR_MAX_RESTARTS)
            return

        _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        auth_hex = self._cfg.get("auth_token_12b", "")
        api_token = self._cfg.get("api_token", "")
        relay_url = f"http://127.0.0.1:{self._port}"
        userid = self._cfg.get("userid", "newpt1084306678")

        env = os.environ.copy()
        env["AUTH_TOKEN_12B"] = auth_hex
        env["HANDSHAKE_BLOB"] = handshake_hex
        env["SRS_SESSIONID"] = srs_sid
        env["RELAY_URL"] = relay_url
        env["API_TOKEN"] = api_token
        env["USERID"] = userid
        env["BIND_PORT"] = "8003"  # must match srs_spectator/main.py BIND_PORT default
        env["PYTHONPATH"] = os.pathsep.join([_ROOT, os.path.join(_ROOT, "remote", "srs_spectator")])

        spectator_main = os.path.join(_ROOT, "remote", "srs_spectator", "main.py")
        log_path = os.path.join(_ROOT, "logs", f"srs_spectator_{self._mode}.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log_file = open(log_path, "a", encoding="utf-8")
            self._srs_spectator_proc = subprocess.Popen(
                [sys.executable, spectator_main],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=_ROOT,
            )
            _LOGGER.info("[%s] SRS spectator 子进程已启动 (pid=%d, log=%s)",
                         self._mode.upper(), self._srs_spectator_proc.pid, log_path)
        except Exception as exc:
            _LOGGER.error("[%s] 启动 SRS spectator 失败: %s", self._mode.upper(), exc)

    def _stop_spectator(self):
        """停止 SRS spectator 子进程"""
        if self._srs_spectator_proc is not None and self._srs_spectator_proc.poll() is None:
            self._srs_spectator_proc.terminate()
            try:
                self._srs_spectator_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._srs_spectator_proc.kill()
            self._srs_spectator_proc = None
            _LOGGER.info("[%s] SRS spectator 已停止", self._mode.upper())

    def _persist_credentials(self, handshake_hex: str, auth_hex: str, srs_sid: str = ""):
        """持久化凭证到配置文件"""
        if not self._cfg_path:
            _LOGGER.warning("[%s] 未设置配置文件路径，无法持久化凭证", self._mode.upper())
            return
        try:
            cfg_on_disk = {}
            if os.path.isfile(self._cfg_path):
                with open(self._cfg_path, "r", encoding="utf-8") as f:
                    cfg_on_disk = yaml.safe_load(f) or {}

            cfg_on_disk["handshake_blob"] = handshake_hex
            cfg_on_disk["auth_token_12b"] = auth_hex
            if srs_sid:
                cfg_on_disk["srs_sessionid"] = srs_sid

            with open(self._cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg_on_disk, f, allow_unicode=True, default_flow_style=False)

            _LOGGER.info("[%s] 凭证已持久化到 %s", self._mode.upper(), self._cfg_path)
        except Exception as exc:
            _LOGGER.error("[%s] 持久化凭证失败: %s", self._mode.upper(), exc)

    def _notify_spectator(self, room_id: int, game_id: int):
        """通知 SRS spectator 服务开始旁观"""
        spec_url = self._spectator_url or self._cfg.get("spectator_url", "")
        if not spec_url:
            return

        def _do_notify():
            try:
                api_token = self._cfg.get("api_token", "")
                resp = requests.post(
                    f"{spec_url}/watch",
                    json={"roomid": room_id, "gameid": game_id, "api_token": api_token},
                    timeout=5,
                )
                if resp.status_code == 200:
                    _LOGGER.info("[%s] 已通知 spectator: room_id=%d, game_id=%d",
                                self._mode.upper(), room_id, game_id)
                else:
                    _LOGGER.warning("[%s] spectator 通知失败: %d %s",
                                   self._mode.upper(), resp.status_code, resp.text)
            except Exception as e:
                _LOGGER.debug("[%s] spectator 通知异常: %s", self._mode.upper(), e)

        threading.Thread(target=_do_notify, daemon=True).start()

    # ─── 初始页 ──────────────────────────────────────────────────

    _STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    _INDEX_HTML_PATH = os.path.join(_STATIC_DIR, "index.html")

    def _build_hand_display_page(self):
        """构建手牌展示页（static/index.html）"""
        try:
            with open(self._INDEX_HTML_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return self._build_mode_page()
        """构建模式信息页"""
        mode_title = self._mode_title()
        desc = self.MODE_DESCRIPTIONS.get(self._mode, "")
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{mode_title}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;max-width:600px;margin:20px auto;padding:0 16px;background:#0f0f23;color:#ccc;line-height:1.6}}
h1{{color:#4f8;text-align:center;font-size:22px;margin:15px 0}}
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
<h1>🀄 {mode_title}</h1>
<div class="info">
<b>描述：</b> {desc}<br>
<b>端口：</b> <code>{self._port}</code><br>
<b>api_token：</b> <code>{self._cfg.get('api_token', '未配置')[:8]}...</code><br>
<b>凭证状态：</b> {'✅ 已就绪' if self._cfg.get('handshake_blob') and self._cfg.get('auth_token_12b') else '⏳ 等待注册'}
</div>
<h2>API 端点</h2>
<div class="endpoint"><span class="method">GET</span> <span class="path">/state?token=...</span><span class="desc">查询最新游戏状态</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/push</span><span class="desc">推送游戏快照</span></div>
<div class="endpoint"><span class="method">POST</span> <span class="path">/register</span><span class="desc">注册认证凭证</span></div>
<div class="endpoint"><span class="method">GET</span> <span class="path">/mode</span><span class="desc">模式诊断信息</span></div>
</body></html>"""


# ─── 工厂函数 ──────────────────────────────────────────────────


def create_mode_app(
    mode: str,
    cfg: dict,
    cfg_path: str = "",
    port: int = 8000,
) -> tuple:
    """
    创建指定模式的 RelayApp 实例。

    返回 (RelayApp, FastAPI app) 元组。
    """
    relay = RelayApp(cfg=cfg, cfg_path=cfg_path, mode=mode, port=port)
    return relay, relay.app
