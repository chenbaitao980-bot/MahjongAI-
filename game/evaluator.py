"""
出牌候选综合分析
"""

from __future__ import annotations

from game.danger import calc_tile_danger, danger_level_str
from game.state import MeldGroup
from game.tiles import build_visible_tiles, tiles_to_ids
from game.ukeire import calc_ukeire


def analyze_discard_candidates(
    hand_14: list[str],
    melds: list[MeldGroup],
    baida: str | None,
    visible_tiles: dict[str, int],
    enemy_discards: list[str],
    enemy_melds: list[MeldGroup],
    self_discards: list[str],
    remaining_tiles: int,
) -> list[dict]:
    """
    分析14张手牌中每种不重复的候选出牌。
    返回按 (shanten_after ASC, ukeire_count DESC) 排序的列表。
    """
    candidates: list[dict] = []
    meld_count = len(melds)

    # 对手副露数
    enemy_meld_count = len(enemy_melds)

    # 巡目估算（粗略）
    turn = (136 - remaining_tiles) // 2 if remaining_tiles is not None else 0

    # 枚举手牌中不重复的牌
    unique_tiles = sorted(set(hand_14))

    for tile in unique_tiles:
        hand_13 = list(hand_14)
        hand_13.remove(tile)

        ukeire = calc_ukeire(hand_13, meld_count, baida, visible_tiles)

        danger = calc_tile_danger(
            tile,
            enemy_discards,
            enemy_melds,
            self_discards,
            remaining_tiles,
            turn,
        )

        candidates.append({
            "discard": tile,
            "shanten_after": ukeire["current_shanten"],
            "ukeire_tiles": ukeire["tiles"],
            "ukeire_count": ukeire["count"],
            "danger": danger,
            "danger_level": danger_level_str(danger),
        })

    # 排序：向听数升序 → 进张数降序
    candidates.sort(key=lambda x: (x["shanten_after"], -x["ukeire_count"]))
    return candidates


if __name__ == "__main__":
    from game.tiles import hand_to_counts

    # 14张手牌：1m1m + 234m + 345m + 456m + 56m7m
    # 最优打出 7m（保留 56m 两面搭子）
    hand = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "5m", "6m", "7m"]
    visible = build_visible_tiles(hand, [], [], [], [])
    result = analyze_discard_candidates(
        hand, [], None, visible, [], [], [], 80
    )
    print("evaluator test1 top candidates:")
    for c in result[:3]:
        print(f"  {c}")
    # 验证基本排序逻辑：向听数小的在前
    assert result[0]["shanten_after"] <= result[-1]["shanten_after"]
    assert result[0]["ukeire_count"] >= result[1]["ukeire_count"] or result[0]["shanten_after"] < result[1]["shanten_after"]

    print("evaluator.py smoke-test OK")
