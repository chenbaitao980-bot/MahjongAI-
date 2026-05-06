"""
已见牌 / 剩余牌统计（原子笔记 01 阶段要求）

基于简化版 SimpleGameState，返回长度为 34 的整数数组。
"""

from __future__ import annotations

from game.simple_state import SimpleGameState


def count_visible_tiles(state: SimpleGameState, my_player: int) -> list[int]:
    """
    返回长度为 34 的数组。
    visible_count[tile_id] = 当前已经可见的该牌数量。
    包括：自己的手牌、所有人弃牌、所有人副露。
    """
    visible = [0] * 34

    # 自己的手牌
    for tile_id in state.hands[my_player]:
        visible[tile_id] += 1

    # 所有人弃牌
    for player_discards in state.discards:
        for tile_id in player_discards:
            visible[tile_id] += 1

    # 所有人副露
    for player_melds in state.melds:
        for meld in player_melds:
            for tile_id in meld.tiles:
                visible[tile_id] += 1

    return visible


def count_remaining_tiles(state: SimpleGameState, my_player: int) -> list[int]:
    """
    返回长度为 34 的数组。
    remaining[tile_id] = max(0, 4 - visible_count[tile_id])
    """
    visible = count_visible_tiles(state, my_player)
    return [max(0, 4 - v) for v in visible]


if __name__ == "__main__":
    from game.simple_state import SimpleMeld

    # ---- smoke test ----
    state = SimpleGameState()
    state.hands[0] = [0, 0, 1, 27]   # 1m 1m 2m 东
    state.discards[1] = [0, 2]       # 1m 3m
    state.melds[0].append(SimpleMeld(type="chi", tiles=[3, 4, 5]))  # 456m

    visible = count_visible_tiles(state, my_player=0)
    # 1m: 手牌2 + 弃牌1 = 3
    assert visible[0] == 3
    # 2m: 手牌1 = 1
    assert visible[1] == 1
    # 3m: 弃牌1 = 1
    assert visible[2] == 1
    # 东(27): 手牌1 = 1
    assert visible[27] == 1
    # 4m(3),5m(4),6m(5): 副露各1
    assert visible[3] == 1
    assert visible[4] == 1
    assert visible[5] == 1

    remaining = count_remaining_tiles(state, my_player=0)
    # 1m 已见3张，剩余1张
    assert remaining[0] == 1
    # 2m 已见1张，剩余3张
    assert remaining[1] == 3
    # 某张从未出现的牌，剩余4张
    assert remaining[10] == 4

    print("visible.py smoke-test OK")
