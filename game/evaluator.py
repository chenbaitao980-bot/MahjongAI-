"""
出牌候选综合分析
"""

from __future__ import annotations

from game.danger import calc_tile_danger, danger_level_str
from game.state import MeldGroup
from game.strategy import decide_strategy_mode, rank_candidates, score_candidate
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
) -> dict:
    """
    分析14张手牌中每种不重复的候选出牌。

    返回：
        {
            "strategy_mode": "attack" | "balance" | "defense",
            "candidates": [
                {
                    "discard": tile,
                    "shanten_after": int,
                    "ukeire_tiles": [...],
                    "ukeire_count": int,
                    "danger": int,
                    "danger_level": str,
                    "score": float,
                }
            ]
        }
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

        # 生牌判断需要包含自家副露牌（被碰/杠/吃的牌也算已出现）
        self_meld_tiles_flat: list[str] = []
        for m in melds:
            self_meld_tiles_flat.extend(tiles_to_ids(m.tiles))
        # 合并自家弃牌和自家副露牌用于生牌判断
        self_all_visible = list(self_discards) + self_meld_tiles_flat

        danger = calc_tile_danger(
            tile,
            enemy_discards,
            enemy_melds,
            self_all_visible,
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

    # 先按原始规则排序，提取最优向听数和对应进张数
    candidates.sort(key=lambda x: (x["shanten_after"], -x["ukeire_count"]))
    best_shanten = candidates[0]["shanten_after"] if candidates else 99
    best_ukeire = candidates[0]["ukeire_count"] if candidates else 0

    # 决定攻守模式
    mode = decide_strategy_mode(best_shanten, best_ukeire, turn, enemy_meld_count)

    # 为每个候选计算综合评分
    for c in candidates:
        c["score"] = round(score_candidate(c, mode), 1)

    # 按综合评分降序重排
    candidates = rank_candidates(candidates)

    return {
        "strategy_mode": mode,
        "candidates": candidates,
    }


if __name__ == "__main__":
    from game.tiles import hand_to_counts

    # 14张手牌：1m1m + 234m + 345m + 456m + 56m7m
    # 最优打出 7m（保留 56m 两面搭子）
    hand = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "5m", "6m", "7m"]
    visible = build_visible_tiles(hand, [], [], [], [])
    result = analyze_discard_candidates(
        hand, [], None, visible, [], [], [], 80
    )
    print("evaluator test1:")
    print(f"  strategy_mode: {result['strategy_mode']}")
    print("  top candidates:")
    for c in result["candidates"][:3]:
        print(f"    {c}")

    candidates = result["candidates"]
    # 验证返回结构
    assert "strategy_mode" in result
    assert "candidates" in result
    assert "score" in candidates[0]

    # 验证排序：score 降序
    for i in range(len(candidates) - 1):
        assert candidates[i]["score"] >= candidates[i + 1]["score"]

    # test2: 高危险牌在防守模式下应被降权
    # 构造一个后巡高向听场景，触发 defense 模式
    hand2 = ["1m", "2m", "3m", "5p", "6p", "7p", "2s", "3s", "4s", "1z", "1z", "7z", "7z", "9m"]
    visible2 = build_visible_tiles(hand2, [], [], [], [])
    result2 = analyze_discard_candidates(
        hand2, [], None, visible2, [], [], [], 20
    )
    print("evaluator test2 (defense scenario):")
    print(f"  strategy_mode: {result2['strategy_mode']}")
    cands2 = result2["candidates"]
    for c in cands2[:3]:
        print(f"    discard={c['discard']}, shanten={c['shanten_after']}, danger={c['danger']}, score={c['score']}")
    # 后巡 + 剩余20张 → 巡目约58，>=12，若向听>=2 则 defense
    if result2["strategy_mode"] == "defense":
        # 危险牌不应排在最前（即使向听低）
        top = cands2[0]
        assert top["danger"] < 80, f"defense mode should avoid high danger cards, got danger={top['danger']}"

    print("evaluator.py smoke-test OK")
