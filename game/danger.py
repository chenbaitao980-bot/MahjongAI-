"""
危险牌评分 — 二人模式版本

二人模式与四人模式的核心差异：
- 无包牌规则，生张字牌不额外危险
- 只有一家对手，副露可聚焦推断清一色
- 基线危险度降低（原四人模式30→20）
"""

from __future__ import annotations

from game.state import MeldGroup
from game.tiles import suit_of, tiles_to_ids


def calc_tile_danger(
    tile: str,
    enemy_discards: list[str],
    enemy_melds: list[MeldGroup],
    self_visible: list[str],
    remaining_tiles: int,
    turn: int,
) -> int:
    """
    计算打出某张牌的危险度（0-100）。

    Args:
        tile: 候选打出的牌ID，如 "5m"
        enemy_discards: 对手已打出的牌列表
        enemy_melds: 对手副露列表
        self_visible: 自家已出现的牌（弃牌+副露），用于生牌判断
        remaining_tiles: 当前剩余牌墙张数
        turn: 当前巡目（粗略估算）

    Returns:
        int: 0（绝对安全）~ 100（极度危险）
    """
    # 统计该牌已见张数（对手弃牌 + 自家已见）
    visible_count = enemy_discards.count(tile) + self_visible.count(tile)

    # 全现物：已见4张 → 绝对安全
    if visible_count >= 4:
        return 0

    danger = 20  # 二人模式基线（无包牌，比四人模式30低）

    # 1. 现物安全：对手打过这张牌 → 大幅降低
    if tile in enemy_discards:
        danger -= 25

    # 2. 已见张数降低危险度
    if visible_count == 1:
        danger -= 5
    elif visible_count == 2:
        danger -= 10
    elif visible_count == 3:
        danger -= 25

    # 3. 对手副露推断（清一色 / 混一色）
    if enemy_melds:
        meld_suit_counts: dict[str, int] = {}
        for m in enemy_melds:
            for t in tiles_to_ids(m.tiles):
                s = suit_of(t)
                if s != "z":
                    meld_suit_counts[s] = meld_suit_counts.get(s, 0) + 1

        if meld_suit_counts:
            dominant_suit = max(meld_suit_counts, key=lambda s: meld_suit_counts[s])
            total_meld_tiles = sum(meld_suit_counts.values())
            dominant_ratio = meld_suit_counts[dominant_suit] / total_meld_tiles

            tile_suit = suit_of(tile)
            if dominant_ratio >= 0.8 and len(enemy_melds) >= 2:
                # 对手疑似清一色
                if tile_suit == dominant_suit:
                    danger += 40  # 同花色极度危险
                elif tile_suit != "z":
                    danger -= 10  # 异色相对安全

    # 4. 中张提高危险度（3-7万/筒/条）
    tile_suit = suit_of(tile)
    if tile_suit in ("m", "p", "s"):
        rank = int(tile[:-1])
        if 3 <= rank <= 7:
            danger += 10

    # 5. 巡目提高危险度
    if turn >= 18:
        danger += 25
    elif turn >= 14:
        danger += 15
    elif turn >= 10:
        danger += 8

    return max(0, min(100, danger))


def danger_level_str(score: int) -> str:
    """将危险度数值转为可读等级标签。"""
    if score <= 20:
        return "安全"
    if score <= 40:
        return "较安全"
    if score <= 60:
        return "中等"
    if score <= 80:
        return "危险"
    return "极危险"


if __name__ == "__main__":
    from game.state import MeldGroup

    # 1. 现物牌 → 安全
    d = calc_tile_danger("5m", ["5m", "3p"], [], [], 80, 5)
    assert d <= 20, f"现物应安全，got {d}"
    print(f"test1 现物: danger={d} ({danger_level_str(d)})")

    # 2. 全现物 → 0
    d = calc_tile_danger("1z", ["1z", "1z", "1z"], [], ["1z"], 80, 5)
    assert d == 0, f"全现物应为0，got {d}"
    print(f"test2 全现物: danger={d}")

    # 3. 中张生牌 + 后巡 → 高危险
    d = calc_tile_danger("5m", [], [], [], 25, 16)
    assert d >= 40, f"中张后巡应高危险，got {d}"
    print(f"test3 中张后巡: danger={d} ({danger_level_str(d)})")

    # 4. 对手疑似清一色 同花色 → 极高危险
    melds = [
        MeldGroup(meld_type="peng", tiles=["3m", "3m", "3m"]),
        MeldGroup(meld_type="peng", tiles=["7m", "7m", "7m"]),
    ]
    d = calc_tile_danger("5m", [], melds, [], 60, 8)
    assert d >= 50, f"清一色同花色应高危险，got {d}"
    print(f"test4 清一色同花色: danger={d} ({danger_level_str(d)})")

    # 5. 对手疑似清一色 异花色 → 降低
    d2 = calc_tile_danger("5p", [], melds, [], 60, 8)
    assert d2 < d, f"异花色应比同花色更安全，got {d2} vs {d}"
    print(f"test5 清一色异花色: danger={d2} ({danger_level_str(d2)})")

    print("danger.py smoke-test OK")
