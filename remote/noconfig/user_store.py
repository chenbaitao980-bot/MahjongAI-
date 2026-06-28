"""
user_store.py — 多用户状态管理

为 noconfig 模式提供多用户数据存储，每个用户独立保存：
  - 基本信息（user_id, name, srs_sessionid, handshake_blob, auth_token_12b）
  - 游戏状态（snapshot, room_info, last_push_time）
  - spectator 进程引用
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from state_store import StateStore

_LOGGER = logging.getLogger("remote.noconfig.user_store")

# 在线判定阈值：超过该秒数没有任何新数据则视为离线（需求：10 分钟）
ONLINE_TTL_SECONDS = 600.0
PROVISIONAL_ONLINE_TTL_SECONDS = 30.0
_PERSIST_FILENAME = "users.json"


class User:
    """单个用户的数据模型"""

    def __init__(self, user_id: str, name: str = "", srs_sessionid: str = "",
                 handshake_blob: str = "", auth_token_12b: str = ""):
        self.user_id = user_id
        self.name = name or user_id
        self.srs_sessionid = srs_sessionid
        self.handshake_blob = handshake_blob
        self.auth_token_12b = auth_token_12b
        self.created_at = time.time()
        self.updated_at = time.time()
        # presence 时间戳：最近一次"活跃"信号（进大厅/进游戏），独立于实际手牌推送。
        # 用于"进大厅即在线"——此时可能还没有任何 0x2bc0 手牌数据。
        self.presence_ts = 0.0
        self.presence_ttl_seconds = ONLINE_TTL_SECONDS
        self.is_provisional = False
        self.provisional_source = ""
        # 每个用户独立的状态存储
        self.state_store = StateStore()
        # spectator 进程（每个用户可独立启动）
        self.spectator_proc = None
        self.spectator_restart_count = 0

    def to_dict(self) -> dict:
        """序列化为字典（用于 API 返回）"""
        last_seen = self.last_seen_ts()
        last_seen_ago = (time.time() - last_seen) if last_seen > 0 else None
        return {
            "user_id": self.user_id,
            "name": self.name,
            "srs_sessionid": self.srs_sessionid[:16] + "..." if self.srs_sessionid else "",
            "has_credentials": bool(self.handshake_blob and self.auth_token_12b),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_online": self.is_online(),
            "is_provisional": self.is_provisional,
            # 最近一次收到数据的时间戳与距今秒数（前端展示"X 分钟前在线"）
            "last_seen_ts": last_seen if last_seen > 0 else None,
            "last_seen_ago": last_seen_ago,
        }

    def touch_presence(self):
        """标记用户活跃（进大厅/进游戏的 presence 信号）。"""
        self.presence_ts = time.time()
        self.updated_at = self.presence_ts

    def mark_provisional(self, source: str = ""):
        self.is_provisional = True
        self.provisional_source = source or ""
        self.presence_ttl_seconds = PROVISIONAL_ONLINE_TTL_SECONDS

    def clear_provisional(self):
        self.is_provisional = False
        self.provisional_source = ""
        self.presence_ttl_seconds = ONLINE_TTL_SECONDS

    def last_seen_ts(self) -> float:
        """最近一次活跃时间戳：取实际数据推送与 presence 信号的较大者。
        兜底到 updated_at（持久化字段，能在服务器重启后保留最后在线时间）。"""
        ts = max(self.state_store.last_push_time or 0.0, self.presence_ts or 0.0)
        if ts > 0:
            return ts
        return self.updated_at

    def is_online(self) -> bool:
        """判断用户是否在线。

        规则（需求）：用户进入大厅开始有数据即视为在线；超过 ONLINE_TTL_SECONDS
        （10 分钟）没有任何新数据则视为离线。spectator 进程运行中也算在线。
        注意：这里用 ONLINE_TTL_SECONDS 而非 state_store.push_timeout——后者很短
        （5s），仅用于驱动 spectator 的启动/停止判断，不适合作为在线展示阈值。
        """
        last_seen = self.last_seen_ts()
        if last_seen > 0 and (time.time() - last_seen) < self.presence_ttl_seconds:
            return True
        if self.spectator_proc is not None and self.spectator_proc.poll() is None:
            return True
        return False

    def update_credentials(self, handshake_blob: str = "", auth_token_12b: str = "",
                           srs_sessionid: str = ""):
        """更新用户凭证"""
        if handshake_blob:
            self.handshake_blob = handshake_blob
        if auth_token_12b:
            self.auth_token_12b = auth_token_12b
        if srs_sessionid:
            self.srs_sessionid = srs_sessionid
        self.updated_at = time.time()

    def on_push(self, snapshot: dict):
        """接收 extractor 推送的快照"""
        self.state_store.on_push(snapshot)
        self.updated_at = time.time()

    def get_snapshot(self) -> dict:
        """获取当前用户的游戏快照"""
        snap = self.state_store.get_snapshot()
        snap["user_id"] = self.user_id
        snap["user_name"] = self.name
        snap["credential_ready"] = bool(self.handshake_blob and self.auth_token_12b)
        return snap

    def get_room_info(self) -> dict:
        """获取当前用户的房间信息"""
        return self.state_store.get_room_info()

    def set_room_info(self, room_id: int, game_id: int = 0):
        """设置当前用户的房间信息"""
        self.state_store.set_room_info(room_id, game_id)


class UserStore:
    """多用户状态管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._users: Dict[str, User] = {}
        self._users_lock = threading.RLock()
        self._push_timeout = 10.0
        self._data_dir = ""

    def set_data_dir(self, data_dir: str) -> None:
        """设置数据目录，加载持久化的用户元数据"""
        self._data_dir = data_dir
        self._load_persisted()

    def _persist_path(self) -> str:
        return os.path.join(self._data_dir, _PERSIST_FILENAME) if self._data_dir else ""

    def _load_persisted(self) -> None:
        """从 JSON 加载持久化的用户元数据（不含游戏状态快照）"""
        path = self._persist_path()
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for u in raw.get("users", []):
                uid = u.get("user_id")
                if uid and uid not in self._users:
                    user = User(
                        user_id=uid,
                        name=u.get("name", uid),
                        srs_sessionid=u.get("srs_sessionid", ""),
                        handshake_blob=u.get("handshake_blob", ""),
                        auth_token_12b=u.get("auth_token_12b", ""),
                    )
                    user.created_at = u.get("created_at", time.time())
                    user.updated_at = u.get("updated_at", time.time())
                    user.state_store.push_timeout = self._push_timeout
                    self._users[uid] = user
            _LOGGER.info("[UserStore] 已从 %s 恢复 %d 个持久化用户", path, len(raw.get("users", [])))
        except Exception as exc:
            _LOGGER.error("[UserStore] 加载持久化用户失败: %s", exc)

    def _save_persisted(self) -> None:
        """持久化用户元数据到 JSON（仅保存非 provisional 的用户信息，不保存瞬态游戏状态）"""
        path = self._persist_path()
        if not path:
            return
        try:
            users_data = []
            with self._users_lock:
                for user in self._users.values():
                    if user.is_provisional:
                        continue
                    users_data.append({
                        "user_id": user.user_id,
                        "name": user.name,
                        "srs_sessionid": user.srs_sessionid,
                        "handshake_blob": user.handshake_blob,
                        "auth_token_12b": user.auth_token_12b,
                        "created_at": user.created_at,
                        "updated_at": user.updated_at,
                    })
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"users": users_data}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            _LOGGER.error("[UserStore] 持久化用户失败: %s", exc)

    def set_push_timeout(self, timeout: float):
        self._push_timeout = timeout
        for user in self._users.values():
            user.state_store.push_timeout = timeout

    def add_user(self, user_id: str, name: str = "", srs_sessionid: str = "",
                 handshake_blob: str = "", auth_token_12b: str = "") -> User:
        """添加用户，如果已存在则更新。

        去重策略（按优先级）：
        1. user_id 已存在 → 更新该用户
        2. srs_sessionid 已存在 → 更新该用户（同一设备/会话不应创建多个用户）
        3. name 已存在且为有效名称 → 更新该用户（游戏内昵称唯一，兜底去重）
        4. 否则创建新用户

        修改用户后自动持久化到 JSON。
        """
        with self._users_lock:
            # 1. user_id 精确匹配
            if user_id in self._users:
                user = self._users[user_id]
                user.name = name or user.name
                user.update_credentials(handshake_blob, auth_token_12b, srs_sessionid)
                _LOGGER.info("[UserStore] 更新用户: %s (%s)", user_id, user.name)
                self._save_persisted()
                return user

            # 2. srs_sessionid 匹配（同一 session 不应重复）
            if srs_sessionid:
                for existing in self._users.values():
                    if existing.srs_sessionid and existing.srs_sessionid == srs_sessionid:
                        existing.name = name or existing.name
                        existing.update_credentials(handshake_blob, auth_token_12b, srs_sessionid)
                        _LOGGER.info("[UserStore] 按 srs_sessionid 合并用户: %s -> %s (%s)",
                                     user_id, existing.user_id, existing.name)
                        self._save_persisted()
                        return existing

            # 3. name 匹配兜底（游戏内昵称唯一）
            effective_name = name or user_id
            if effective_name and effective_name != user_id and effective_name != "default":
                for existing in self._users.values():
                    if existing.name and existing.name == effective_name:
                        existing.update_credentials(handshake_blob, auth_token_12b, srs_sessionid)
                        _LOGGER.info("[UserStore] 按名称合并用户: %s -> %s (%s)",
                                     user_id, existing.user_id, existing.name)
                        self._save_persisted()
                        return existing

            # 4. 创建新用户
            user = User(user_id, name, srs_sessionid, handshake_blob, auth_token_12b)
            user.state_store.push_timeout = self._push_timeout
            self._users[user_id] = user
            _LOGGER.info("[UserStore] 新增用户: %s (%s)", user_id, user.name)
            self._save_persisted()
            return user

    def remove_user(self, user_id: str) -> bool:
        """删除用户（同时更新持久化）"""
        with self._users_lock:
            if user_id in self._users:
                user = self._users[user_id]
                if user.spectator_proc is not None:
                    try:
                        user.spectator_proc.terminate()
                        user.spectator_proc.wait(timeout=3)
                    except Exception:
                        pass
                del self._users[user_id]
                _LOGGER.info("[UserStore] 删除用户: %s", user_id)
                self._save_persisted()
                return True
            return False

    def get_user(self, user_id: str) -> Optional[User]:
        """获取指定用户"""
        with self._users_lock:
            return self._users.get(user_id)

    def _prune_expired_provisionals_locked(self) -> int:
        now = time.time()
        removed_ids = []
        for user_id, user in list(self._users.items()):
            if not user.is_provisional:
                continue
            last_seen = user.last_seen_ts()
            if last_seen <= 0 or (now - last_seen) >= user.presence_ttl_seconds:
                removed_ids.append(user_id)
                del self._users[user_id]
        for user_id in removed_ids:
            _LOGGER.info("[UserStore] pruned expired provisional user: %s", user_id)
        return len(removed_ids)

    def get_all_users(self) -> list:
        """获取所有用户列表"""
        with self._users_lock:
            self._prune_expired_provisionals_locked()
            return [user.to_dict() for user in self._users.values()]

    def remove_provisional_by_source(self, source: str) -> int:
        if not source:
            return 0
        removed_ids = []
        with self._users_lock:
            for user_id, user in list(self._users.items()):
                if user.is_provisional and user.provisional_source == source:
                    removed_ids.append(user_id)
            for user_id in removed_ids:
                del self._users[user_id]
        for user_id in removed_ids:
            _LOGGER.info("[UserStore] removed provisional user: %s source=%s", user_id, source)
        return len(removed_ids)

    def search_users(self, keyword: str) -> list:
        """按名称搜索用户（不区分大小写）"""
        keyword = keyword.lower()
        with self._users_lock:
            self._prune_expired_provisionals_locked()
            return [
                user.to_dict()
                for user in self._users.values()
                if keyword in user.name.lower() or keyword in user.user_id.lower()
            ]

    def on_push(self, user_id: str, snapshot: dict):
        """指定用户接收推送"""
        user = self.get_user(user_id)
        if user:
            user.on_push(snapshot)
        else:
            _LOGGER.warning("[UserStore] 推送失败: 用户 %s 不存在", user_id)

    def get_user_snapshot(self, user_id: str) -> Optional[dict]:
        """获取指定用户的快照"""
        user = self.get_user(user_id)
        if user:
            return user.get_snapshot()
        return None

    def get_online_users(self) -> list:
        """获取在线用户列表"""
        with self._users_lock:
            self._prune_expired_provisionals_locked()
            return [
                user.to_dict()
                for user in self._users.values()
                if user.is_online()
            ]

    def get_user_count(self) -> int:
        """获取用户总数"""
        with self._users_lock:
            self._prune_expired_provisionals_locked()
            return len(self._users)

    def get_default_user(self) -> Optional[User]:
        """获取默认用户（兼容单用户模式）"""
        with self._users_lock:
            if len(self._users) == 1:
                return next(iter(self._users.values()))
            return None

    def clear(self):
        """清空所有用户"""
        with self._users_lock:
            for user in self._users.values():
                if user.spectator_proc is not None:
                    try:
                        user.spectator_proc.terminate()
                    except Exception:
                        pass
            self._users.clear()
            _LOGGER.info("[UserStore] 已清空所有用户")


# 全局单例
user_store = UserStore()
