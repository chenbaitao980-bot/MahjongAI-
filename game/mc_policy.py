"""
蒙特卡洛模拟 — 快速 Rollout 策略

目标：单次选牌 < 1ms，不调用完整 evaluator。
基于 calc_shanten + 极简危险度估算。
"""

from __future__ import annotations

import random
from functools import lru_cache

from game.shanten import calc_shanten, calc_shanten_int
from game.tiles import hand_to_counts, int_to_tile, tile_to_int


# ---- 向听数缓存（性能关键） ----

@lru_cache(maxsize=8192)
def _cached_shanten(counts_tuple: tuple[int, ...], meld_count: int, baida_count: int) -> int:
    """缓存向听数计算，避免热循环中重复DFS。"""
    return calc_shanten(list(counts_tuple), meld_count, baida_count)


def _shanten_for_hand(hand_13: list[int], meld_count: int, baida_int: int | None) -> int:
    """将13张手牌转为counts后计算向听数（带缓存）。使用纯整数版避免字符串转换。"""
    counts = [0] * 34
    baida_count = 0
    for t in hand_13:
        counts[t] += 1
    if baida_int is not None:
        baida_count = counts[baida_int]
        counts[baida_int] = 0
    return _cached_shanten(tuple(counts), meld_count, baida_count)


# ---- 极简危险度 ----

def _calc_danger_fast(tile_int: int, visible_counts: list[int]) -> int:
    """
    极简危险度估算（0~100）。
    - 已见张数越少越危险
    - 字牌生张额外加权
    - 中张（3~7）额外加权
    """
    danger = 30
    seen = visible_counts[tile_int]

    # 已见张数修正
    if seen == 1:
        danger -= 5
    elif seen == 2:
        danger -= 10
    elif seen >= 3:
        danger -= 20

    # 字牌生张
    if tile_int >= 27 and seen == 0:
        danger += 15

    # 中张
    if tile_int < 27:
        rank = (tile_int % 9) + 1
        if 3 <= rank <= 7:
            danger += 10

    return max(0, min(100, danger))


# ---- 快速选牌策略 ----

def fast_discard_policy(
    hand: list[int],
    melds: list,
    baida_int: int | None,
    visible_counts: list[int],
    rng: random.Random | None = None,
    randomness: float = 0.2,
) -> int:
    """
    快速选牌策略。

    Args:
        hand: 当前手牌（整数ID列表），摸牌后应为14张
        melds: 副露列表（用于计算 meld_count）
        baida_int: 财神整数ID
        visible_counts: 34维已见牌计数（用于危险度）
        rng: 随机数生成器（对手策略用）
        randomness: 随机扰动概率（0~1），对手用20%随机

    Returns:
        选中的打出牌整数ID
    """
    candidates = list(set(hand))
    meld_count = len(melds)

    # 随机扰动（对手用）
    if rng is not None and rng.random() < randomness:
        return rng.choice(candidates)

    best_tile = candidates[0]
    best_score = -1e9

    for tile in candidates:
        hand_13 = list(hand)
        hand_13.remove(tile)

        shanten = _shanten_for_hand(hand_13, meld_count, baida_int)
        danger = _calc_danger_fast(tile, visible_counts)

        # 综合评分：向听越低越好，危险越低越好
        # 听牌时（shanten==0）优先打危险低的
        if shanten <= 0:
            score = -danger * 100
        else:
            score = -shanten * 1000 - danger * 5

        if score > best_score:
            best_score = score
            best_tile = tile

    return best_tile


if __name__ == "__main__":
    import time

    rng = random.Random(42)

    # 测试1：基本选牌
    hand = [0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 33, 33]  # 14张
    visible = [0] * 34
    visible[0] = 2  # 1m已见2张
    visible[27] = 2  # 东已见2张

    tile = fast_discard_policy(hand, [], None, visible)
    print(f"test1: discard={tile} ({int_to_tile(tile)})")
    assert tile in hand

    # 测试2：对手随机扰动
    tiles = []
    for _ in range(20):
        tiles.append(fast_discard_policy(hand, [], None, visible, rng=rng, randomness=0.2))
    # 应该有部分随机选择
    assert len(set(tiles)) > 1, "随机扰动应产生不同选择"
    print(f"test2: 20次随机选择={set(tiles)}")

    # 测试3：性能测试
    hand_perf = list(range(14))  # 0~13
    visible_perf = [0] * 34
    n = 100
    start = time.perf_counter()
    for _ in range(n):
        fast_discard_policy(hand_perf, [], None, visible_perf)
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / n) * 1000
    print(f"test3: {n}次选牌平均 {avg_ms:.2f}ms/次")
    assert avg_ms < 5, f"单次选牌应<5ms，实际{avg_ms:.2f}ms"

    # 测试4：缓存效果
    # 第二次调用相同手牌应更快
    start2 = time.perf_counter()
    for _ in range(n):
        fast_discard_policy(hand_perf, [], None, visible_perf)
    elapsed2 = time.perf_counter() - start2
    avg_ms2 = (elapsed2 / n) * 1000
    print(f"test4: 缓存后平均 {avg_ms2:.2f}ms/次")
    assert avg_ms2 < avg_ms * 0.5, "缓存后应明显更快"

    print("mc_policy.py smoke-test OK")
