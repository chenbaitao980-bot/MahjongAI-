"""
出牌候选综合分析
"""

from __future__ import annotations

from game.danger import calc_tile_danger, danger_level_str
from game.state import MeldGroup
from game.strategy import decide_strategy_mode, rank_candidates, score_candidate
from game.tiles import build_visible_tiles, suit_of, tiles_to_ids
from game.ukeire import calc_ukeire


# 高番字牌：红中(5z)、发财(6z)、门风
FAN_HONOR_TILES = {"5z", "6z"}  # 红中、发财


def estimate_potential_fan(
    hand_13: list[str],
    melds: list[MeldGroup],
    baida: str | None,
    self_wind: str,
) -> float:
    """
    估算打出一张牌后，剩余手牌的潜在最大番数。
    第一版简化规则，仅基于手牌结构做静态估算。

    Returns:
        float: 预估潜在番数（非精确，用于同向听数下的排序）
    """
    fan = 0.0

    # 合并手牌和副露中的所有牌
    all_tiles = list(hand_13)
    for m in melds:
        all_tiles.extend(tiles_to_ids(m.tiles))

    if not all_tiles:
        return 0.0

    total = len(all_tiles)

    # 1. 字牌番：红中、发财、门风 的对子/刻子/杠
    wind_tiles = {self_wind}
    fan_honors = FAN_HONOR_TILES | wind_tiles

    counts: dict[str, int] = {}
    for t in all_tiles:
        counts[t] = counts.get(t, 0) + 1

    for t, c in counts.items():
        if t in fan_honors and c >= 2:
            fan += 1.0  # 对子/刻子/杠各计1番

    # 2. 清一色潜力：某数牌花色占比 >= 80%
    suits: dict[str, int] = {"m": 0, "p": 0, "s": 0, "z": 0}
    for t in all_tiles:
        s = suit_of(t)
        suits[s] = suits.get(s, 0) + 1

    for s in ("m", "p", "s"):
        if total > 0 and suits[s] / total >= 0.8:
            fan += 2.0
            break  # 清一色只加一次

    # 3. 混一色潜力：某数牌花色 + 字牌 占比 >= 90%
    for s in ("m", "p", "s"):
        if total > 0 and (suits[s] + suits.get("z", 0)) / total >= 0.9:
            # 如果已经加了清一色，不再加混一色
            if not (suits[s] / total >= 0.8):
                fan += 0.5
            break

    # 4. 无财神 / 财神还原（较难静态估算，暂不纳入第一版）

    return round(fan, 1)


def analyze_discard_candidates(
    hand_14: list[str],
    melds: list[MeldGroup],
    baida: str | None,
    visible_tiles: dict[str, int],
    enemy_discards: list[str],
    enemy_melds: list[MeldGroup],
    self_discards: list[str],
    remaining_tiles: int,
    self_wind: str = "1z",
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
                    "potential_fan": float,
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

        potential_fan = estimate_potential_fan(hand_13, melds, baida, self_wind)

        candidates.append({
            "discard": tile,
            "shanten_after": ukeire["current_shanten"],
            "ukeire_tiles": ukeire["tiles"],
            "ukeire_count": ukeire["count"],
            "potential_fan": potential_fan,
            "danger": danger,
            "danger_level": danger_level_str(danger),
        })

    # 先按 (向听数, 潜在番数, 进张数) 排序，提取最优向听数
    candidates.sort(key=lambda x: (x["shanten_after"], -x["potential_fan"], -x["ukeire_count"]))
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
