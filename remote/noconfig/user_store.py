"""
user_store.py — 多用户状态管理

为 noconfig 模式提供多用户数据存储，每个用户独立保存：
  - 基本信息（user_id, name, srs_sessionid, handshake_blob, auth_token_12b）
  - 游戏状态（snapshot, room_info, last_push_time）
  - spectator 进程引用
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from state_store import StateStore

_LOGGER = logging.getLogger("remote.noconfig.user_store")


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
        # 每个用户独立的状态存储
        self.state_store = StateStore()
        # spectator 进程（每个用户可独立启动）
        self.spectator_proc = None
        self.spectator_restart_count = 0

    def to_dict(self) -> dict:
        """序列化为字典（用于 API 返回）"""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "srs_sessionid": self.srs_sessionid[:16] + "..." if self.srs_sessionid else "",
            "has_credentials": bool(self.handshake_blob and self.auth_token_12b),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_online": self.is_online(),
        }

    def is_online(self) -> bool:
        """判断用户是否在线（有最近推送或 spectator 运行中）"""
        if self.state_store.last_push_time > 0:
            elapsed = time.time() - self.state_store.last_push_time
            if elapsed < self.state_store.push_timeout:
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

    def set_push_timeout(self, timeout: float):
        self._push_timeout = timeout
        for user in self._users.values():
            user.state_store.push_timeout = timeout

    def add_user(self, user_id: str, name: str = "", srs_sessionid: str = "",
                 handshake_blob: str = "", auth_token_12b: str = "") -> User:
        """添加用户，如果已存在则更新"""
        with self._users_lock:
            if user_id in self._users:
                user = self._users[user_id]
                user.name = name or user.name
                user.update_credentials(handshake_blob, auth_token_12b, srs_sessionid)
                _LOGGER.info("[UserStore] 更新用户: %s (%s)", user_id, user.name)
            else:
                user = User(user_id, name, srs_sessionid, handshake_blob, auth_token_12b)
                user.state_store.push_timeout = self._push_timeout
                self._users[user_id] = user
                _LOGGER.info("[UserStore] 新增用户: %s (%s)", user_id, user.name)
            return user

    def remove_user(self, user_id: str) -> bool:
        """删除用户"""
        with self._users_lock:
            if user_id in self._users:
                user = self._users[user_id]
                # 停止 spectator 进程
                if user.spectator_proc is not None:
                    try:
                        user.spectator_proc.terminate()
                        user.spectator_proc.wait(timeout=3)
                    except Exception:
                        pass
                del self._users[user_id]
                _LOGGER.info("[UserStore] 删除用户: %s", user_id)
                return True
            return False

    def get_user(self, user_id: str) -> Optional[User]:
        """获取指定用户"""
        with self._users_lock:
            return self._users.get(user_id)

    def get_all_users(self) -> list:
        """获取所有用户列表"""
        with self._users_lock:
            return [user.to_dict() for user in self._users.values()]

    def search_users(self, keyword: str) -> list:
        """按名称搜索用户（不区分大小写）"""
        keyword = keyword.lower()
        with self._users_lock:
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
            return [
                user.to_dict()
                for user in self._users.values()
                if user.is_online()
            ]

    def get_user_count(self) -> int:
        """获取用户总数"""
        with self._users_lock:
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
