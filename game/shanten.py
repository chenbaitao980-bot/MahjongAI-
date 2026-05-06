"""
向听数计算（支持财神替代）

向听数公式（need = 4 - meld_count）：
    shanten = need * 2 - (2 * groups + min(taatsus, need) + has_pair)

其中：
- groups：手牌中完整面子数
- taatsus：搭子数（顺子/刻子缺1张的组合）
- has_pair：0/1，是否有将牌候选
"""

from __future__ import annotations


def calc_shanten(counts: list[int], meld_count: int, baida_count: int) -> int:
    """
    计算向听数。
    counts: 34维数组，**不含财神**（财神已被清零）
    meld_count: 已有副露数
    baida_count: 手牌中财神数

    返回：-1（已胡），0（听牌），1（一向听），...
    """
    need = 4 - meld_count
    best = need * 2 + 1  # 向听数上界

    # 情况1：有将牌候选
    for pair in range(34):
        if counts[pair] >= 2:
            c = list(counts)
            c[pair] -= 2
            for groups, rem_counts, rem_jokers in _remove_all_groups(c, baida_count):
                taatsus = _count_taatsus(rem_counts, rem_jokers)
                shanten = need * 2 - (groups * 2 + min(taatsus, need) + 1)
                if shanten < best:
                    best = shanten

    # 情况2：无将牌候选（用剩余牌中的对子/搭子凑将）
    for groups, rem_counts, rem_jokers in _remove_all_groups(counts, baida_count):
        taatsus, pairs = _count_taatsus_and_pairs(rem_counts, rem_jokers)
        # 如果没有将牌，需要额外1步来凑将牌
        shanten = need * 2 - (groups * 2 + min(taatsus + pairs, need))
        if shanten < best:
            best = shanten

    # 已胡牌的情况
    if best <= -1:
        return -1
    return best


def _remove_all_groups(counts: list[int], jokers: int):
    """
    递归移除所有可能的面子组合，返回生成器：(groups, remaining_counts, remaining_jokers)
    """
    yield from _remove_groups_dfs(counts, jokers, 0, 0)


def _remove_groups_dfs(counts: list[int], jokers: int, idx: int, groups: int):
    """
    从 idx 开始找面子，回溯所有可能。
    """
    # 跳过空位
    while idx < 34 and counts[idx] == 0:
        idx += 1

    if idx >= 34:
        yield groups, counts, jokers
        return

    # 不把这个位置的牌作为面子的起点，直接跳过
    # （但需要保留递归深度，由后续处理其他位置）
    # 先把当前位置的牌跳过，继续往后
    # 注意：这里不能简单设为0然后yield，因为可能有多种面子组合方式

    # 方案A：尝试作为刻子
    if counts[idx] >= 3:
        c = list(counts)
        c[idx] -= 3
        yield from _remove_groups_dfs(c, jokers, idx, groups + 1)

    if counts[idx] == 2 and jokers >= 1:
        c = list(counts)
        c[idx] -= 2
        yield from _remove_groups_dfs(c, jokers - 1, idx, groups + 1)

    if counts[idx] == 1 and jokers >= 2:
        c = list(counts)
        c[idx] -= 1
        yield from _remove_groups_dfs(c, jokers - 2, idx, groups + 1)

    # 方案B：尝试作为顺子（仅数牌）
    if idx < 27 and (idx % 9) <= 6:
        for use_j0 in (0, 1):
            for use_j1 in (0, 1):
                for use_j2 in (0, 1):
                    total_j = use_j0 + use_j1 + use_j2
                    if total_j > jokers:
                        continue
                    if (counts[idx] >= 1 - use_j0) and \
                       (counts[idx + 1] >= 1 - use_j1) and \
                       (counts[idx + 2] >= 1 - use_j2):
                        c = list(counts)
                        if use_j0 == 0:
                            c[idx] -= 1
                        if use_j1 == 0:
                            c[idx + 1] -= 1
                        if use_j2 == 0:
                            c[idx + 2] -= 1
                        yield from _remove_groups_dfs(c, jokers - total_j, idx, groups + 1)

    # 方案C：不组成面子，跳过当前牌（保留counts，idx前进）
    yield from _remove_groups_dfs(counts, jokers, idx + 1, groups)


def _count_taatsus(counts: list[int], jokers: int) -> int:
    """
    统计剩余牌中最多能组成多少个搭子（不考虑对子作为将牌候选）。
    搭子包括：两面、坎张、对子（但这里对子也算搭子，因为对子+1张=刻子）。
    """
    c = list(counts)
    taatsus = 0

    # 1) 两面搭子（如 3-4，等2或5）
    for i in range(27):
        rank = i % 9
        if rank <= 7:  # 3-4, 4-5, ... 8-9
            pairs = min(c[i], c[i + 1])
            taatsus += pairs
            c[i] -= pairs
            c[i + 1] -= pairs

    # 2) 对子搭子（3-3，等1张成刻子）
    for i in range(34):
        pairs = c[i] // 2
        taatsus += pairs
        c[i] -= pairs * 2

    # 3) 坎张搭子（3-5，等4）
    for i in range(27):
        rank = i % 9
        if rank <= 6:  # 3-5, 4-6, ... 7-9
            pairs = min(c[i], c[i + 2])
            taatsus += pairs
            c[i] -= pairs
            c[i + 2] -= pairs

    # 4) 剩余孤张，1个joker可以补成对子搭子
    singles = sum(c)
    taatsus += min(singles, jokers)

    return taatsus


def _count_taatsus_and_pairs(counts: list[int], jokers: int) -> tuple[int, int]:
    """
    统计搭子数和对子数（用于无将牌候选的情况）。
    返回 (taatsus, pairs)，其中 pairs 是可以作对子候选的对子数。
    """
    c = list(counts)
    taatsus = 0
    pairs = 0

    # 1) 两面搭子
    for i in range(27):
        rank = i % 9
        if rank <= 7:
            n = min(c[i], c[i + 1])
            taatsus += n
            c[i] -= n
            c[i + 1] -= n

    # 2) 对子（作对子候选）
    for i in range(34):
        n = c[i] // 2
        pairs += n
        c[i] -= n * 2

    # 3) 坎张搭子
    for i in range(27):
        rank = i % 9
        if rank <= 6:
            n = min(c[i], c[i + 2])
            taatsus += n
            c[i] -= n
            c[i + 2] -= n

    # 4) 孤张+1joker=对子（作对子候选）
    singles = sum(c)
    extra_pairs = min(singles, jokers)
    pairs += extra_pairs

    return taatsus, pairs


if __name__ == "__main__":
    from game.tiles import hand_to_counts

    # 1. 已胡牌 → -1
    hand1 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "5m", "6m", "7m"]
    c1, bc1 = hand_to_counts(hand1)
    assert calc_shanten(c1, 0, bc1) == -1

    # 2. 听牌 → 0（1m1m + 234m + 345m + 456m + 67m 等一张5m或8m... 不，这是12张）
    # 13张听牌：1m1m + 234m + 345m + 456m + 67m
    hand2 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7m"]
    c2, bc2 = hand_to_counts(hand2)
    s2 = calc_shanten(c2, 0, bc2)
    print("test2 shanten:", s2)
    assert s2 == 0  # 听牌（等5m或8m）

    # 3. 一向听 → 1
    # 1m1m + 234m + 345m + 45m + 67m
    hand3 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "7m"]
    c3, bc3 = hand_to_counts(hand3)
    s3 = calc_shanten(c3, 0, bc3)
    print("test3 shanten:", s3)
    assert s3 == 1

    # 4. 带财神听牌：1m1m + 234m + 345m + 456m + 6m + 7z(财神)
    # 6m+7z=67m 搭子，听58m
    hand4 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "6m", "7z"]
    c4, bc4 = hand_to_counts(hand4, baida="7z")
    s4 = calc_shanten(c4, 0, bc4)
    print("test4 shanten (with baida):", s4)
    assert s4 == 0

    # 5. 副露1组后的向听数
    # 副露1组，手牌11张：1m1m + 234m + 345m + 456m（已3面子+将，还需1面子，11张=3*3+2）
    # 这是胡牌
    hand5 = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m"]
    c5, bc5 = hand_to_counts(hand5)
    s5 = calc_shanten(c5, 1, bc5)
    print("test5 shanten (1 meld):", s5)
    assert s5 == -1

    print("shanten.py smoke-test OK")
