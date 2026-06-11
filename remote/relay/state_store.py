"""
state_store.py — 内存状态存储

管理最新游戏 snapshot，以及 extractor 在线/离线的模式切换逻辑。
"""
from __future__ import annotations

import logging
import time
import threading

_LOGGER = logging.getLogger("remote.relay.state_store")


class StateStore:
    """
    内存状态存储，仅保留当前局最新 snapshot。

    模式逻辑：
    - extractor 推送时：更新 last_push_time，保存 snapshot
    - 超过 PUSH_TIMEOUT 秒无推送 → 认为 extractor 离线，应启动 GameClient
    - GameClient 收到数据时：直接更新 snapshot（不更新 last_push_time）
    """

    PUSH_TIMEOUT = 60.0  # 超过此秒数无推送认为 extractor 离线

    def __init__(self):
        self._lock = threading.Lock()
        self.latest_snapshot = {}            # 最新游戏状态
        self.last_push_time = 0.0           # extractor 最后推送时间（epoch 秒）
        self._on_extractor_online = None    # extractor 恢复时回调
        self._on_extractor_offline = None   # extractor 超时时回调

    def on_push(self, snapshot):
        """extractor 推送时调用，更新状态和时间戳"""
        with self._lock:
            self.latest_snapshot = snapshot
            self.last_push_time = time.time()

    def on_game_event(self, snapshot):
        """GameClient（主动连接）收到新数据时调用"""
        with self._lock:
            self.latest_snapshot = snapshot

    def _is_extractor_offline_unlocked(self):
        """(需已持有 _lock) 判断 extractor 是否离线"""
        if self.last_push_time == 0.0:
            return True
        return (time.time() - self.last_push_time) > self.PUSH_TIMEOUT

    def should_use_game_client(self):
        """
        判断是否应该启动/保持 GameClient 主动连接。
        返回 True 当且仅当超过 PUSH_TIMEOUT 秒未收到 extractor 推送。
        """
        with self._lock:
            result = self._is_extractor_offline_unlocked()
            if self.last_push_time == 0.0:
                _LOGGER.debug("[模式判断] extractor 从未推送 → 离线, use_game_client=%s", result)
            elif result:
                elapsed = time.time() - self.last_push_time
                _LOGGER.debug("[模式判断] 距上次推送 %.1fs (> %.1fs) → 离线, use_game_client=%s",
                             elapsed, self.PUSH_TIMEOUT, result)
            return result

    def get_snapshot(self):
        """获取当前最新 snapshot，无数据时返回 idle 状态"""
        with self._lock:
            is_game_client = self._is_extractor_offline_unlocked()
            data_source = "game_client" if is_game_client else "extractor"
            if not self.latest_snapshot:
                return {"phase": "idle", "data_source": data_source}
            snap = dict(self.latest_snapshot)
            snap["data_source"] = data_source
            return snap
