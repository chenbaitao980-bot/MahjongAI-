"""
合法动作枚举（原子笔记 02 阶段要求）

基于简化版 SimpleGameState，枚举可打牌和基础合法动作。
新增 guard 接入：响应别人打出的牌时，检查能胡不胡/能碰不碰限制。
"""

from __future__ import annotations

from game.guard import ActionGuard
from game.simple_state import SimpleGameState
from game.tiles import tile_to_int
from game.win import is_win_int, is_win_simple


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
    注意：这里的 hu 是自摸/已摸牌后的胡牌判断，不涉及能胡不胡限制。
    """
    hand = state.hands[player]
    actions: list[dict] = []

    # 能胡就胡（自摸场景，不涉及 guard 限制）
    if len(hand) == 14 and is_win_simple(hand):
        actions.append({"type": "hu"})

    # 枚举所有可打牌
    actions.extend(get_discard_actions(hand))

    return actions


def get_response_actions(
    hand: list[int],
    melds: list,
    baida_int: int | None,
    tile_id_str: str,
    guard: ActionGuard | None = None,
    player: int = 0,
) -> list[dict]:
    """
    别人打出 tile_id_str 时，判断自己可以做什么响应动作（胡/碰）。
    若提供了 guard，会检查能胡不胡/能碰不碰限制。

    Args:
        hand: 当前手牌（整数ID列表）
        melds: 当前副露列表
        baida_int: 财神整数ID（或None）
        tile_id_str: 别人打出的牌ID（如 "5m"）
        guard: ActionGuard 实例（可选）
        player: 玩家ID（0=自家, 1=对手）

    Returns:
        可执行的动作列表，如 [{"type": "hu", "tile": "5m"}, {"type": "peng", "tile": "5m"}]
    """
    actions: list[dict] = []
    tile_int = tile_to_int(tile_id_str)

    # 1. 胡牌检查
    if guard is None or guard.can_hu(player, tile_id_str):
        # 模拟手牌加入这张牌后是否胡牌
        test_hand = list(hand) + [tile_int]
        if is_win_int(test_hand, len(melds), baida_int):
            actions.append({"type": "hu", "tile": tile_id_str})

    # 2. 碰牌检查
    if guard is None or guard.can_peng(player, tile_id_str):
        if hand.count(tile_int) >= 2:
            actions.append({"type": "peng", "tile": tile_id_str})

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

    # 4. get_response_actions 无 guard 测试
    hand4 = parse_tiles("1m 1m 2m 3m 4m 5m 6m 7m 8m 9m 1p 2p 3p")
    # 手牌 13 张，加入 1m 后：1m*3 + 234m + 567m + 789m + 123p = 胡牌
    resp = get_response_actions(hand4, [], None, "1m")
    assert any(a["type"] == "hu" for a in resp), "应能胡 1m"

    # 5. get_response_actions 有 guard 测试（能胡不胡限制）
    guard = ActionGuard()
    guard.on_decline_hu(0, "1m")
    resp_guarded = get_response_actions(hand4, [], None, "1m", guard=guard, player=0)
    assert not any(a["type"] == "hu" for a in resp_guarded), "guard 应阻止胡 1m"
    print("test4+5 response_actions:", resp, resp_guarded)

    # 6. get_response_actions 碰牌测试
    hand6 = parse_tiles("5m 5m 3p 4p 6s 7s 1z 2z 3z 7z 7z 7z 1m")
    resp_peng = get_response_actions(hand6, [], None, "5m")
    assert any(a["type"] == "peng" for a in resp_peng), "应能碰 5m"

    # guard 限制碰
    guard2 = ActionGuard()
    guard2.on_decline_peng(0, "5m")
    resp_no_peng = get_response_actions(hand6, [], None, "5m", guard=guard2, player=0)
    assert not any(a["type"] == "peng" for a in resp_no_peng), "guard 应阻止碰 5m"
    print("test6 response_actions peng:", resp_peng, resp_no_peng)

    print("actions.py smoke-test OK")
