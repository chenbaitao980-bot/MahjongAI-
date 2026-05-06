"""
合法动作枚举（原子笔记 02 阶段要求）

基于简化版 SimpleGameState，枚举可打牌和基础合法动作。
"""

from __future__ import annotations

from game.simple_state import SimpleGameState
from game.win import is_win_simple


def get_discard_actions(hand: list[int]) -> list[dict]:
    """
    返回当前手牌可以打出的牌。同一种牌只返回一次。
    输出格式：[{"type": "discard", "tile": 0}, ...]
    """
    seen = set()
    actions: list[dict] = []
    for tile_id in hand:
        if tile_id not in seen:
            seen.add(tile_id)
            actions.append({"type": "discard", "tile": tile_id})
    return actions


def get_legal_actions(state: SimpleGameState, player: int) -> list[dict]:
    """
    当前阶段只实现 discard 和 hu。
    如果手牌14张且能胡，加入 {"type": "hu"}，然后枚举所有可打牌。
    """
    hand = state.hands[player]
    actions: list[dict] = []

    # 能胡就胡
    if len(hand) == 14 and is_win_simple(hand):
        actions.append({"type": "hu"})

    # 枚举所有可打牌
    actions.extend(get_discard_actions(hand))

    return actions


if __name__ == "__main__":
    from game.tiles import parse_tiles
    from game.simple_state import SimpleMeld

    # ---- smoke test ----

    # 1. get_discard_actions 去重测试
    hand = parse_tiles("1m 1m 2m 3m 1z 1z 7z")
    discards = get_discard_actions(hand)
    tiles = [a["tile"] for a in discards]
    assert len(tiles) == len(set(tiles)), "同种牌不应重复"
    assert 0 in tiles   # 1m
    assert 1 in tiles   # 2m
    assert 2 in tiles   # 3m
    assert 27 in tiles  # 东(1z)
    assert 33 in tiles  # 白(7z)
    print("test1 discard_actions:", discards)

    # 2. get_legal_actions 胡牌场景
    state = SimpleGameState()
    # 标准胡牌手牌：1m2m3m + 2p3p4p + 5s6s7s + 东东东 + 白白
    state.hands[0] = parse_tiles("1m 2m 3m 2p 3p 4p 5s 6s 7s 1z 1z 1z 7z 7z")
    legal = get_legal_actions(state, player=0)
    types = [a["type"] for a in legal]
    assert "hu" in types, "能胡时应包含 hu"
    assert "discard" in types, "应包含 discard"
    print("test2 legal_actions (win):", legal[:3], "...")

    # 3. get_legal_actions 非胡牌场景
    state2 = SimpleGameState()
    state2.hands[0] = parse_tiles("1m 1m 2m 3m 1z 1z 7z")
    legal2 = get_legal_actions(state2, player=0)
    types2 = [a["type"] for a in legal2]
    assert "hu" not in types2, "不能胡时不应包含 hu"
    assert types2.count("discard") == 5, "7张牌有5种不同牌"
    print("test3 legal_actions (no win):", legal2)

    print("actions.py smoke-test OK")
