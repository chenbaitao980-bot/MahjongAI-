"""
危险牌评分
"""

from __future__ import annotations

from game.tiles import rank_of, suit_of, tiles_to_ids
from game.state import MeldGroup

DANGER_LEVELS = [
    (20, "安全"),
    (40, "较安全"),
    (60, "中等"),
    (80, "危险"),
    (101, "极危险"),
]


def calc_tile_danger(
    tile: str,
    enemy_discards: list[str],
    enemy_melds: list[MeldGroup],
    self_discards: list[str],
    remaining_tiles: int,
    turn: int,
) -> int:
    """
    计算单张出牌的危险度分数（0~100）。
    """
    danger = 30

    # 已见张数统计（自家弃牌 + 对手弃牌 + 对手副露）
    seen = 0
    seen += self_discards.count(tile)
    seen += enemy_discards.count(tile)
    for m in enemy_melds:
        seen += tiles_to_ids(m.tiles).count(tile)

    # 已见张数修正
    if seen == 1:
        danger -= 5
    elif seen == 2:
        danger -= 10
    elif seen == 3:
        danger -= 20
    elif seen >= 4:
        danger -= 30

    # 现物（对手弃牌中出现过）
    if tile in enemy_discards:
        danger -= 20

    # 字牌且已见0张
    if suit_of(tile) == "z" and seen == 0:
        danger += 15

    # 中张（万/筒/条 的 3~7）
    if suit_of(tile) in ("m", "p", "s") and 3 <= rank_of(tile) <= 7:
        danger += 15

    # 巡目加成
    if turn >= 8:
        danger += 10
    if turn >= 12:
        danger += 10

    # 对手副露数
    enemy_meld_count = len(enemy_melds)
    if enemy_meld_count >= 2:
        danger += 10

    # 生牌阶段且是生张
    if remaining_tiles <= 30:
        # 生张 = 对手弃牌+对手副露中从未出现
        enemy_seen = enemy_discards.count(tile)
        for m in enemy_melds:
            enemy_seen += tiles_to_ids(m.tiles).count(tile)
        if enemy_seen == 0:
            danger += 25

    return max(0, min(100, danger))


def danger_level_str(score: int) -> str:
    for threshold, label in DANGER_LEVELS:
        if score < threshold:
            return label
    return DANGER_LEVELS[-1][1]


if __name__ == "__main__":
    from game.state import TileMatch

    # 测试1：中张，无已见，生牌阶段
    d1 = calc_tile_danger("5m", [], [], [], 28, 10)
    print("danger test1:", d1, danger_level_str(d1))
    assert d1 > 60  # 中张+15，生牌+25，巡目+10 = 80

    # 测试2：现物，已见2张
    d2 = calc_tile_danger("3m", ["3m", "3m"], [], ["3m"], 50, 5)
    print("danger test2:", d2, danger_level_str(d2))
    assert d2 < 30  # 现物-20，已见3张-20

    # 测试3：字牌生张，生牌阶段
    d3 = calc_tile_danger("1z", [], [], [], 25, 15)
    print("danger test3:", d3, danger_level_str(d3))
    assert d3 > 60

    print("danger.py smoke-test OK")
