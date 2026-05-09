"""
蒙特卡洛模拟 — 对手手牌分配 + 牌墙构建

从可见牌推算剩余牌分布，随机分配对手暗手，构建牌墙。
"""

from __future__ import annotations

import random

from game.state import MeldGroup
from game.tiles import tile_to_int, tiles_to_ids


def _visible_counts(
    self_hand: list[int],
    self_melds: list[MeldGroup],
    self_discards: list[int],
    enemy_discards: list[int],
    enemy_melds: list[MeldGroup],
) -> list[int]:
    """返回34维可见牌计数数组。"""
    visible = [0] * 34

    for t in self_hand:
        visible[t] += 1
    for t in self_discards:
        visible[t] += 1
    for t in enemy_discards:
        visible[t] += 1

    for meld in self_melds:
        for t in tiles_to_ids(meld.tiles):
            visible[tile_to_int(t)] += 1
    for meld in enemy_melds:
        for t in tiles_to_ids(meld.tiles):
            visible[tile_to_int(t)] += 1

    return visible


def build_wall_and_enemy_hand(
    self_hand: list[int],
    self_melds: list[MeldGroup],
    self_discards: list[int],
    enemy_discards: list[int],
    enemy_melds: list[MeldGroup],
    baida_int: int | None,
    remaining_tiles_hint: int,
    rng: random.Random,
) -> tuple[list[int], list[int]]:
    """
    从完整136张牌中扣除所有可见牌，随机分配对手暗手，剩余作为牌墙。

    正确逻辑：
    - 可见牌 = self_hand + self_discards + enemy_discards + 双方副露
    - remaining（不可见牌）= 136 - sum(可见牌)
    - remaining 中包含：enemy_hand（对手暗手）+ wall（牌墙）
    - enemy_hand_size ≈ 13（2人模式对手手牌数）
    - wall 长度应与 remaining_tiles_hint 一致（若hint合理）

    Args:
        self_hand: 自家手牌（整数ID列表）
        self_melds: 自家副露列表
        self_discards: 自家弃牌（整数ID列表）
        enemy_discards: 对手弃牌（整数ID列表）
        enemy_melds: 对手副露列表
        baida_int: 财神整数ID（或None）
        remaining_tiles_hint: 当前牌墙剩余张数提示
        rng: 随机数生成器

    Returns:
        (wall_list, enemy_hand_list) 均为整数ID列表
    """
    visible = _visible_counts(
        self_hand, self_melds, self_discards,
        enemy_discards, enemy_melds,
    )

    # 构建剩余牌池（不可见牌）
    remaining: list[int] = []
    for tile_int in range(34):
        count = max(0, 4 - visible[tile_int])
        remaining.extend([tile_int] * count)

    # 对手暗手张数：2人模式开局13张
    # 若自家已摸牌（14张），则对手可能也已摸牌（14张）
    enemy_hand_size = 13
    if len(self_hand) == 14:
        # 自家已摸牌，对手可能也已摸牌（取决于回合顺序）
        # 简化处理：仍按13张算，多1张在wall里也无妨
        pass

    # remaining_tiles_hint 是牌墙当前长度
    # 正确关系：len(remaining) == enemy_hand_size + remaining_tiles_hint
    # 但 remaining 是计算值，hint 是游戏报告值，可能不一致
    # 策略：优先保证 enemy_hand_size 合理，wall 取剩余部分
    # 若 hint 与计算值相差太大，以 hint 为准调整 enemy_hand_size

    if remaining_tiles_hint > 0 and remaining_tiles_hint < len(remaining):
        # hint 合理：用 hint 确定 wall 长度，enemy_hand 取剩余
        wall_len = remaining_tiles_hint
        enemy_hand_size = len(remaining) - wall_len
        # 防御：enemy_hand_size 应在合理范围内
        if enemy_hand_size < 10 or enemy_hand_size > 14:
            # hint 可能不准，改回默认13
            enemy_hand_size = 13
            wall_len = len(remaining) - enemy_hand_size
    else:
        # hint 无效（0或不合理），enemy_hand 固定13张
        enemy_hand_size = 13
        wall_len = len(remaining) - enemy_hand_size

    enemy_hand_size = max(0, enemy_hand_size)
    wall_len = max(0, wall_len)

    # 防御：remaining 可能不够分
    if len(remaining) < enemy_hand_size + wall_len:
        # 剩余牌不够，尽量分配
        enemy_hand_size = min(enemy_hand_size, len(remaining))
        wall_len = len(remaining) - enemy_hand_size

    rng.shuffle(remaining)
    enemy_hand = remaining[:enemy_hand_size]
    wall = remaining[enemy_hand_size:enemy_hand_size + wall_len]

    return wall, enemy_hand


if __name__ == "__main__":
    from game.state import MeldGroup, TileMatch

    rng = random.Random(42)

    # 测试1：基础分配
    self_hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 33, 33]  # 13张
    self_discards = [3, 4]
    enemy_discards = [5, 6]
    self_melds = [MeldGroup(meld_type="chi", tiles=[TileMatch("7m", 1.0), TileMatch("8m", 1.0), TileMatch("9m", 1.0)])]
    enemy_melds = []

    wall, enemy_hand = build_wall_and_enemy_hand(
        self_hand, self_melds, self_discards,
        enemy_discards, enemy_melds,
        baida_int=33, remaining_tiles_hint=0, rng=rng,
    )

    print(f"test1: wall={len(wall)}张, enemy_hand={len(enemy_hand)}张")
    assert len(enemy_hand) == 13, f"对手手牌数异常: {len(enemy_hand)}"
    assert len(wall) > 0

    # 测试2：验证牌数守恒（每张牌最多4张，总分136）
    total_counts = [0] * 34
    for t in self_hand:
        total_counts[t] += 1
    for t in enemy_hand:
        total_counts[t] += 1
    for t in self_discards:
        total_counts[t] += 1
    for t in enemy_discards:
        total_counts[t] += 1
    for m in self_melds:
        for t in m.tiles:
            if t.tile_id:
                total_counts[tile_to_int(t.tile_id)] += 1
    for m in enemy_melds:
        for t in m.tiles:
            if t.tile_id:
                total_counts[tile_to_int(t.tile_id)] += 1
    for t in wall:
        total_counts[t] += 1

    for tile_int in range(34):
        assert total_counts[tile_int] <= 4, \
            f"牌{tile_int}出现了{total_counts[tile_int]}张（最多4张）"

    total = sum(total_counts)
    assert total == 136, f"总牌数应为136，实际{total}"
    print("test2: 牌数守恒验证通过")

    # 测试3：总牌数守恒（交叉验证）
    total2 = (len(self_hand) + len(enemy_hand)
            + len(self_discards) + len(enemy_discards)
            + sum(len(m.tiles) for m in self_melds + enemy_melds)
            + len(wall))
    assert total2 == 136, f"总牌数应为136，实际{total2}"
    print("test3: 总牌数交叉验证通过")

    print("mc_dealer.py smoke-test OK")
