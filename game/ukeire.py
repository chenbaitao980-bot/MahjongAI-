"""
有效进张（Ukeire）计算
"""

from __future__ import annotations

from game.tiles import hand_to_counts, int_to_tile, tile_to_int
from game.shanten import calc_shanten


def calc_ukeire(
    hand_13: list[str],
    meld_count: int,
    baida: str | None,
    visible_tiles: dict[str, int],
) -> dict:
    """
    计算打出一张牌后的 13 张手牌的有效进张。

    返回 {"tiles": [...], "count": total, "current_shanten": current_shanten}
    """
    counts, baida_count = hand_to_counts(hand_13, baida)
    current_shanten = calc_shanten(counts, meld_count, baida_count)

    ukeire_tiles: list[str] = []
    total = 0
    baida_int = tile_to_int(baida) if baida else -1

    for t in range(34):
        tile_id = int_to_tile(t)
        remaining = 4 - visible_tiles.get(tile_id, 0)
        if remaining <= 0:
            continue

        new_counts = list(counts)
        new_baida_count = baida_count

        if t == baida_int:
            new_baida_count += 1
        else:
            new_counts[t] += 1

        new_shanten = calc_shanten(new_counts, meld_count, new_baida_count)
        if new_shanten < current_shanten:
            ukeire_tiles.append(tile_id)
            total += remaining

    return {
        "tiles": ukeire_tiles,
        "count": total,
        "current_shanten": current_shanten,
    }


if __name__ == "__main__":
    from game.tiles import build_visible_tiles

    # 听牌测试：1m1m + 234m + 345m + 456m + 67m
    # 进张很多：1m,2m,4m,5m,7m,8m 都能胡
    hand = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m"]
    visible = build_visible_tiles(hand, [], [], [], [])
    result = calc_ukeire(hand, 0, None, visible)
    print("ukeire test1:", result)
    assert result["current_shanten"] == 0
    assert result["count"] > 0
    assert "5m" in result["tiles"]

    # 一向听测试：1m1m + 234m + 345m + 45m + 67m
    hand2 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "7m"]
    visible2 = build_visible_tiles(hand2, [], [], [], [])
    result2 = calc_ukeire(hand2, 0, None, visible2)
    print("ukeire test2:", result2)
    assert result2["current_shanten"] == 1
    assert result2["count"] > 0

    print("ukeire.py smoke-test OK")
