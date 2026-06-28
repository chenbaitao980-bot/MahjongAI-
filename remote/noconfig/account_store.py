"""
account_store.py — 登录账户管理（独立模块，零依赖）

为 noconfig 模式提供登录账户的 CRUD + JSON 持久化 + 密码哈希。
不依赖 FastAPI / app.py，可独立测试或嵌入其他服务。

用法:
    from account_store import account_store
    account_store.set_data_dir("/path/to/data")
    account_store.add_account("obs1", "password123", allowed_user_ids=["u1", "u2"])
    acct = account_store.authenticate("obs1", "password123")
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Optional

_LOGGER = logging.getLogger("remote.noconfig.account_store")

_ACCOUNTS_FILENAME = "accounts.json"


# ─── 密码工具 ────────────────────────────────────────────────────


def generate_salt(length: int = 16) -> str:
    """生成加密随机盐，返回十六进制字符串"""
    return secrets.token_hex(length)


def hash_password(password: str, salt: str) -> str:
    """SHA-256(salt + password) → hex"""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    """常量时间比较，防时序攻击"""
    return secrets.compare_digest(hash_password(password, salt), password_hash)


# ─── 数据模型 ────────────────────────────────────────────────────


class Account:
    """单个登录账户数据模型"""

    def __init__(
        self,
        account_id: str,
        username: str,
        salt: str,
        password_hash: str,
        description: str = "",
        allowed_user_ids: Optional[list[str]] = None,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
    ):
        self.id = account_id
        self.username = username
        self.salt = salt
        self.password_hash = password_hash
        self.description = description
        self.allowed_user_ids = list(allowed_user_ids or [])
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()

    def to_dict(self) -> dict:
        """完整序列化（含敏感字段，仅用于持久化）"""
        return {
            "id": self.id,
            "username": self.username,
            "salt": self.salt,
            "password_hash": self.password_hash,
            "description": self.description,
            "allowed_user_ids": list(self.allowed_user_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict) -> Account:
        """从字典反序列化"""
        return Account(
            account_id=d["id"],
            username=d["username"],
            salt=d["salt"],
            password_hash=d["password_hash"],
            description=d.get("description", ""),
            allowed_user_ids=d.get("allowed_user_ids", []),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def to_safe_dict(self) -> dict:
        """安全序列化（不含密码哈希和盐，用于 API 返回）"""
        return {
            "id": self.id,
            "username": self.username,
            "description": self.description,
            "allowed_user_ids": list(self.allowed_user_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ─── 账户存储 ────────────────────────────────────────────────────


class AccountStore:
    """登录账户存储（线程安全单例）

    职责：
        - 账户 CRUD
        - JSON 文件持久化
        - 密码验证

    用法:
        account_store = AccountStore()
        account_store.set_data_dir("/path/to/data")
    """

    _instance: Optional[AccountStore] = None
    _lock = threading.Lock()

    def __new__(cls) -> AccountStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._accounts_lock = threading.RLock()
        self._data_dir = ""
        self._loaded = False

    # ── 初始化 ──────────────────────────────────────────────────

    def set_data_dir(self, data_dir: str) -> None:
        """设置数据目录并加载已有账户"""
        self._data_dir = data_dir
        self._load()

    def _path(self) -> str:
        return os.path.join(self._data_dir, _ACCOUNTS_FILENAME) if self._data_dir else ""

    def _load(self) -> None:
        path = self._path()
        if not path or not os.path.isfile(path):
            _LOGGER.info("[AccountStore] %s 不存在，跳过加载", path or "(空路径)")
            self._loaded = True
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            raw_accounts = raw.get("accounts", {}) if isinstance(raw, dict) else {}
            with self._accounts_lock:
                self._accounts.clear()
                for acc_id, acc_dict in raw_accounts.items():
                    self._accounts[acc_id] = Account.from_dict(acc_dict)
            _LOGGER.info("[AccountStore] 已加载 %d 个登录账户 from %s", len(self._accounts), path)
        except Exception as exc:
            _LOGGER.error("[AccountStore] 加载失败 %s: %s", path, exc)
        finally:
            self._loaded = True

    def _save(self) -> None:
        path = self._path()
        if not path:
            _LOGGER.warning("[AccountStore] 未设置 data_dir，无法保存")
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {
                "accounts": {
                    acc_id: acc.to_dict() for acc_id, acc in self._accounts.items()
                }
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            _LOGGER.error("[AccountStore] 保存失败 %s: %s", path, exc)

    # ── CRUD ───────────────────────────────────────────────────

    def add_account(
        self,
        username: str,
        password: str,
        description: str = "",
        allowed_user_ids: Optional[list[str]] = None,
    ) -> Account:
        """创建新账户，自动生成 ID 和盐"""
        account_id = "acc_" + secrets.token_hex(4)
        salt = generate_salt()
        pw_hash = hash_password(password, salt)
        account = Account(
            account_id=account_id,
            username=username,
            salt=salt,
            password_hash=pw_hash,
            description=description,
            allowed_user_ids=allowed_user_ids,
        )
        with self._accounts_lock:
            self._accounts[account_id] = account
        self._save()
        _LOGGER.info("[AccountStore] 新增账户: %s (%s)", account_id, username)
        return account

    def update_account(
        self,
        account_id: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        description: Optional[str] = None,
        allowed_user_ids: Optional[list[str]] = None,
    ) -> Optional[Account]:
        """更新账户。只更新提供的字段，None 字段不更新。"""
        with self._accounts_lock:
            account = self._accounts.get(account_id)
            if account is None:
                return None
            if username is not None:
                account.username = username
            if password is not None:
                account.salt = generate_salt()
                account.password_hash = hash_password(password, account.salt)
            if description is not None:
                account.description = description
            if allowed_user_ids is not None:
                account.allowed_user_ids = list(allowed_user_ids)
            account.updated_at = time.time()
        self._save()
        _LOGGER.info("[AccountStore] 更新账户: %s", account_id)
        return account

    def delete_account(self, account_id: str) -> bool:
        """删除账户"""
        with self._accounts_lock:
            if account_id not in self._accounts:
                return False
            del self._accounts[account_id]
        self._save()
        _LOGGER.info("[AccountStore] 删除账户: %s", account_id)
        return True

    def get_account(self, account_id: str) -> Optional[Account]:
        """按 ID 获取账户"""
        with self._accounts_lock:
            return self._accounts.get(account_id)

    def get_account_by_username(self, username: str) -> Optional[Account]:
        """按用户名查找账户"""
        with self._accounts_lock:
            for acc in self._accounts.values():
                if acc.username == username:
                    return acc
        return None

    def list_accounts(self) -> list[dict]:
        """获取所有账户（安全序列化，无密码）"""
        with self._accounts_lock:
            return [acc.to_safe_dict() for acc in self._accounts.values()]

    # ── 认证 ───────────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> Optional[Account]:
        """验证用户名密码，成功返回 Account，失败返回 None"""
        account = self.get_account_by_username(username)
        if account is None:
            return None
        if verify_password(password, account.salt, account.password_hash):
            return account
        return None

    # ── 授权辅助 ───────────────────────────────────────────────

    def remove_user_from_all(self, user_id: str) -> None:
        """从所有账户的授权列表中移除指定 user_id

        当手机用户被删除时调用，清理各账户的授权数据。
        """
        changed = False
        with self._accounts_lock:
            for acc in self._accounts.values():
                if user_id in acc.allowed_user_ids:
                    acc.allowed_user_ids = [uid for uid in acc.allowed_user_ids if uid != user_id]
                    acc.updated_at = time.time()
                    changed = True
        if changed:
            self._save()
            _LOGGER.info("[AccountStore] 已从所有账户中移除 user_id=%s", user_id)

    def is_user_allowed(self, account_id: str, user_id: str) -> bool:
        """检查账户是否有权限查看指定用户"""
        account = self.get_account(account_id)
        if account is None:
            return False
        # 空列表 = 没有权限（不允许查看任何用户）
        return user_id in account.allowed_user_ids


# ─── 全局单例 ────────────────────────────────────────────────────

account_store = AccountStore()
