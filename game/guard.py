"""
能胡不胡 / 能碰不碰 守卫器

台州麻将规则限制：
- 同一回合中，若有人点炮且玩家第一次选择不胡，则该回合内再次有人点炮同一张牌时也不能胡。
- 同一回合中，若有人打出可碰的牌且玩家第一次选择不碰，则该回合内再次有人打出这张牌时也不能碰。
- 限制仅对该回合生效，该玩家有任何动牌（吃、碰、杠、摸牌）后即解除。
"""

from __future__ import annotations


class ActionGuard:
    """
    跟踪每个玩家本回合的 declined_hu / declined_peng 状态。
    提供查询接口和状态更新接口。
    """

    def __init__(self) -> None:
        # player -> 本回合已拒绝过的牌ID (str)
        self._declined_hu: dict[int, str | None] = {0: None, 1: None}
        self._declined_peng: dict[int, str | None] = {0: None, 1: None}

    def can_hu(self, player: int, tile_id: str) -> bool:
        """判断玩家当前是否可以胡这张牌。"""
        return self._declined_hu.get(player) != tile_id

    def can_peng(self, player: int, tile_id: str) -> bool:
        """判断玩家当前是否可以碰这张牌。"""
        return self._declined_peng.get(player) != tile_id

    def on_decline_hu(self, player: int, tile_id: str) -> None:
        """记录玩家本回合拒绝胡某张牌。"""
        self._declined_hu[player] = tile_id

    def on_decline_peng(self, player: int, tile_id: str) -> None:
        """记录玩家本回合拒绝碰某张牌。"""
        self._declined_peng[player] = tile_id

    def on_action(self, player: int) -> None:
        """玩家有动牌（吃、碰、杠、摸牌）行为后，解除该玩家的限制。"""
        self._declined_hu[player] = None
        self._declined_peng[player] = None

    def reset(self, player: int | None = None) -> None:
        """重置限制。player=None 时重置双方。"""
        if player is None:
            self._declined_hu = {0: None, 1: None}
            self._declined_peng = {0: None, 1: None}
        else:
            self._declined_hu[player] = None
            self._declined_peng[player] = None

    def get_state(self) -> dict:
        """返回当前限制状态（用于序列化）。"""
        return {
            "declined_hu": dict(self._declined_hu),
            "declined_peng": dict(self._declined_peng),
        }


if __name__ == "__main__":
    # ---- smoke tests ----
    guard = ActionGuard()

    # 1. 初始状态：可以胡/碰任意牌
    assert guard.can_hu(0, "5m") is True
    assert guard.can_peng(0, "5m") is True
    assert guard.can_hu(1, "3p") is True

    # 2. 拒绝胡 5m 后，不能再胡 5m
    guard.on_decline_hu(0, "5m")
    assert guard.can_hu(0, "5m") is False
    assert guard.can_hu(0, "3p") is True  # 其他牌仍可胡
    assert guard.can_peng(0, "5m") is True  # 碰不受胡限制影响

    # 3. 拒绝碰 3p 后，不能再碰 3p
    guard.on_decline_peng(1, "3p")
    assert guard.can_peng(1, "3p") is False
    assert guard.can_hu(1, "3p") is True  # 胡不受碰限制影响

    # 4. 动牌后限制解除
    guard.on_action(0)
    assert guard.can_hu(0, "5m") is True
    assert guard.can_peng(0, "5m") is True
    # 玩家1的限制仍在
    assert guard.can_peng(1, "3p") is False

    # 5. 重置全部
    guard.reset()
    assert guard.can_peng(1, "3p") is True

    print("guard.py smoke-test OK")
