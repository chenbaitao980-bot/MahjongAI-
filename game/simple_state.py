"""
简化版牌局状态结构（原子笔记 01 阶段要求）

与 game/state.py 中 vision-oriented 的复杂结构并存，
用于纯算法场景（不涉及截图识别）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class SimpleMeld:
    """一组副露（碰/吃/杠）"""
    type: str                  # "chi", "peng", "gang"
    tiles: List[int]           # 整数ID列表
    from_player: int | None = None


@dataclass
class SimpleGameState:
    """简化版完整游戏状态"""
    hands: List[List[int]] = field(default_factory=lambda: [[], [], [], []])
    discards: List[List[int]] = field(default_factory=lambda: [[], [], [], []])
    melds: List[List[SimpleMeld]] = field(default_factory=lambda: [[], [], [], []])
    current_player: int = 0
    dealer: int = 0
    turn: int = 0


if __name__ == "__main__":
    # ---- smoke test ----
    state = SimpleGameState()
    state.hands[0] = [0, 0, 1, 27]  # 1m 1m 2m 东
    state.discards[1] = [0, 2]     # 1m 3m
    state.melds[0].append(SimpleMeld(type="chi", tiles=[0, 1, 2]))  # 123m

    assert len(state.hands) == 4
    assert state.hands[0] == [0, 0, 1, 27]
    assert state.discards[1] == [0, 2]
    assert state.melds[0][0].type == "chi"
    assert state.melds[0][0].tiles == [0, 1, 2]

    print("simple_state.py smoke-test OK")
