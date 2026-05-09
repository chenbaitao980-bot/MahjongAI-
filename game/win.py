"""
胡牌判断（支持财神替代）

约束：
- 将牌必须由两张相同真实牌组成，财神不能单独作将。
- 字牌只能组刻子，不能组顺子。
- 副露数 meld_count 影响还需凑的面子数（4 - meld_count）。
"""

from __future__ import annotations


def is_win(hand_counts: list[int], meld_count: int, baida_count: int) -> bool:
    """
    判断 hand_counts（34维，**不含财神**）+ 已有 meld_count 副露 + baida_count 张财神
    是否能组成 1对将 + 4副面子。

    hand_counts 中财神已被清零，由 baida_count 单独传入。
    """
    need_melds = 4 - meld_count
    total_tiles = sum(hand_counts) + baida_count
    expected = need_melds * 3 + 2  # 将牌2张 + 每个面子3张
    if total_tiles != expected:
        return False

    # 枚举将牌（必须两张相同真实牌）
    for pair_tile in range(34):
        if hand_counts[pair_tile] >= 2:
            c = list(hand_counts)
            c[pair_tile] -= 2
            if _can_form_melds(c, need_melds, baida_count):
                return True

    return False


def _can_form_melds(counts: list[int], need: int, jokers: int) -> bool:
    """
    递归判断是否能从 counts + jokers 中凑出 need 个面子。
    counts 中不含将牌，jokers 为剩余财神数。
    """
    if need == 0:
        # 所有剩余牌必须能用 jokers 全部消化（joker 可变成任意牌）
        # 实际上如果牌张数对，这里应该自然满足
        return sum(counts) <= jokers

    # 找第一个 count > 0 的牌
    first = -1
    for i in range(34):
        if counts[i] > 0:
            first = i
            break

    if first == -1:
        # 没有实牌了，看 jokers 够不够凑剩余面子
        return need * 3 <= jokers

    i = first

    # 1) 尝试刻子（全用实牌）
    if counts[i] >= 3:
        c = list(counts)
        c[i] -= 3
        if _can_form_melds(c, need - 1, jokers):
            return True

    # 2) 尝试刻子（缺1张用 joker）
    if counts[i] == 2 and jokers >= 1:
        c = list(counts)
        c[i] -= 2
        if _can_form_melds(c, need - 1, jokers - 1):
            return True

    # 3) 尝试刻子（缺2张用 joker）
    if counts[i] == 1 and jokers >= 2:
        c = list(counts)
        c[i] -= 1
        if _can_form_melds(c, need - 1, jokers - 2):
            return True

    # 4) 尝试顺子（仅数牌，i < 27）
    if i < 27 and (i % 9) <= 6:
        # 枚举 joker 使用方式（每个位置用 0 或 1 个 joker 代替实牌）
        for use_j0 in (0, 1):
            for use_j1 in (0, 1):
                for use_j2 in (0, 1):
                    total_j = use_j0 + use_j1 + use_j2
                    if total_j > jokers:
                        continue
                    # 需要 counts[i] >= 1 或用 joker 补；其余两张同理
                    if (counts[i] >= 1 - use_j0) and \
                       (counts[i + 1] >= 1 - use_j1) and \
                       (counts[i + 2] >= 1 - use_j2):
                        c = list(counts)
                        if use_j0 == 0:
                            c[i] -= 1
                        if use_j1 == 0:
                            c[i + 1] -= 1
                        if use_j2 == 0:
                            c[i + 2] -= 1
                        if _can_form_melds(c, need - 1, jokers - total_j):
                            return True

    return False


# ---- 原子笔记 02 阶段简化接口 ----

ENABLE_SEVEN_PAIRS = True


def is_standard_win(hand: list[int]) -> bool:
    """
    判断 14 张整数ID手牌是否标准胡牌（4面子+1将）。
    无副露、无财神的最简情况。
    """
    if len(hand) != 14:
        return False
    from game.tiles import hand_to_counts, int_to_tile
    counts, _ = hand_to_counts([int_to_tile(t) for t in hand])
    return is_win(counts, meld_count=0, baida_count=0)


def is_seven_pairs(hand: list[int]) -> bool:
    """判断 14 张牌是否为七对。"""
    if len(hand) != 14:
        return False
    counts = [0] * 34
    for t in hand:
        counts[t] += 1
    pairs = sum(1 for c in counts if c == 2)
    return pairs == 7


def is_win_simple(hand: list[int]) -> bool:
    """统一胡牌判断（标准胡牌 或 七对）。"""
    if is_standard_win(hand):
        return True
    if ENABLE_SEVEN_PAIRS and is_seven_pairs(hand):
        return True
    return False


# ---- 纯整数版本（MC 热循环专用，避免字符串转换） ----

def is_win_int(
    hand_ints: list[int],
    meld_count: int,
    baida_int: int | None,
) -> bool:
    """
    纯整数版本的胡牌判断。直接从整数ID列表构建counts，
    避免字符串转换开销。MC模拟热循环专用。
    """
    counts = [0] * 34
    baida_count = 0
    for t in hand_ints:
        counts[t] += 1
    if baida_int is not None:
        baida_count = counts[baida_int]
        counts[baida_int] = 0
    return is_win(counts, meld_count, baida_count)


if __name__ == "__main__":
    # ---- smoke tests ----
    from game.tiles import hand_to_counts

    # 1. 简单胡牌：1m1m + 234m + 345m + 456m + 567m
    hand = ["1m", "1m", "2m", "3m", "4m", "3m", "4m", "5m", "4m", "5m", "6m", "5m", "6m", "7m"]
    c, bc = hand_to_counts(hand)
    assert is_win(c, 0, bc) is True

    # 2. 带财神胡牌：1m + 2m + 3m + 4m + 5m + 6m + 7m + 8m + 9m + 1m + 1m + 2m + 2m + 7z(财神)
    # 将=1m1m, 面子: 123m, 456m, 789m, 22m+7z -> 222m（刻子）
    hand2 = ["1m", "1m", "1m", "2m", "2m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "7z"]
    c2, bc2 = hand_to_counts(hand2, baida="7z")
    assert is_win(c2, 0, bc2) is True

    # 3. 不能胡（少一张）
    hand3 = ["1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p"]
    c3, bc3 = hand_to_counts(hand3)
    assert is_win(c3, 0, bc3) is False

    # 4. 副露1组后胡牌：将=1m1m, 面子: 123m, 456m, 789m（副露1组，手牌还需3面子+将）
    hand4 = ["1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p"]
    c4, bc4 = hand_to_counts(hand4)
    assert is_win(c4, 1, bc4) is False  # 11张牌，需要 3*3+2=11 张，但 1p 是孤张

    # 5. 副露1组，手牌正好：1m1m + 234m + 567m + 89m+7z(财神)->789m
    hand5 = ["1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "7z"]
    c5, bc5 = hand_to_counts(hand5, baida="7z")
    assert is_win(c5, 1, bc5) is True

    # 6. 财神不能单独作将
    hand6 = ["1m", "7z", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p"]
    c6, bc6 = hand_to_counts(hand6, baida="7z")
    # 1m 单张作将？不，将牌需要两张相同。7z 只有1张。所以不能胡。
    assert is_win(c6, 0, bc6) is False

    # ---- 原子笔记简化接口测试 ----
    from game.tiles import parse_tiles

    # 标准胡牌：1m2m3m + 2p3p4p + 5s6s7s + 东东东 + 白白
    hand_std = parse_tiles("1m 2m 3m 2p 3p 4p 5s 6s 7s 1z 1z 1z 7z 7z")
    assert is_standard_win(hand_std) is True
    assert is_win_simple(hand_std) is True

    # 非胡牌
    hand_bad = parse_tiles("1m 1m 3m 2p 3p 4p 5s 6s 7s 1z 1z 1z 7z 7z")
    assert is_standard_win(hand_bad) is False
    assert is_win_simple(hand_bad) is False

    # 七对
    hand_7p = parse_tiles("1m 1m 2m 2m 3p 3p 4p 4p 5s 5s 1z 1z 7z 7z")
    assert is_seven_pairs(hand_7p) is True
    assert is_win_simple(hand_7p) is True

    # 非七对
    hand_not_7p = parse_tiles("1m 1m 1m 2m 2m 2m 3p 3p 3p 4p 4p 4p 5s 5s")
    assert is_seven_pairs(hand_not_7p) is False

    print("win.py smoke-test OK")
