"""
牌编码辅助模块（字符串牌ID <-> 整数索引，计数数组等）

牌编号（0~33）：
  0~8:  1m~9m  (万)
  9~17: 1p~9p  (筒)
 18~26: 1s~9s  (条)
 27~33: 1z~7z  (字：东、南、西、北、中、发、白)
"""

from __future__ import annotations

ALL_TILES: list[str] = (
    [f"{i}m" for i in range(1, 10)]   # 0~8
    + [f"{i}p" for i in range(1, 10)] # 9~17
    + [f"{i}s" for i in range(1, 10)] # 18~26
    + [f"{i}z" for i in range(1, 8)]  # 27~33
)

_TILE_TO_INT: dict[str, int] = {t: i for i, t in enumerate(ALL_TILES)}


def tile_to_int(tile_id: str) -> int:
    return _TILE_TO_INT[tile_id]


def int_to_tile(idx: int) -> str:
    return ALL_TILES[idx]


def suit_of(tile_id: str) -> str:
    """返回 'm'/'p'/'s'/'z'"""
    return tile_id[-1]


def rank_of(tile_id: str) -> int:
    """返回 1~9"""
    return int(tile_id[:-1])


def is_honor(tile_id: str) -> bool:
    return tile_id.endswith("z")


def tiles_to_ids(tiles: list) -> list[str]:
    """从 TileMatch 列表或字符串列表中提取 tile_id。"""
    result: list[str] = []
    for t in tiles:
        if isinstance(t, str):
            result.append(t)
        elif hasattr(t, "tile_id"):
            tid = getattr(t, "tile_id")
            if tid:
                result.append(tid)
    return result


def hand_to_counts(hand: list[str], baida: str | None = None) -> tuple[list[int], int]:
    """
    把字符串手牌列表转为 counts[34] 计数数组，同时返回财神张数。
    财神在返回的 counts 中被清零，由调用方通过 baida_count 单独获取。
    """
    counts = [0] * 34
    for t in hand:
        counts[tile_to_int(t)] += 1

    baida_count = 0
    if baida:
        bidx = tile_to_int(baida)
        baida_count = counts[bidx]
        counts[bidx] = 0

    return counts, baida_count


def build_visible_tiles(
    self_hand: list[str],
    self_discards: list[str],
    self_melds_tiles: list[str],
    enemy_discards: list[str],
    enemy_melds_tiles: list[str],
) -> dict[str, int]:
    """统计所有可见牌的出现次数（含自家手牌），用于计算剩余张数。"""
    visible: dict[str, int] = {}
    for t in self_hand + self_discards + self_melds_tiles + enemy_discards + enemy_melds_tiles:
        visible[t] = visible.get(t, 0) + 1
    return visible


if __name__ == "__main__":
    # ---- smoke test ----
    assert tile_to_int("1m") == 0
    assert tile_to_int("9m") == 8
    assert tile_to_int("1p") == 9
    assert tile_to_int("9p") == 17
    assert tile_to_int("1s") == 18
    assert tile_to_int("9s") == 26
    assert tile_to_int("1z") == 27
    assert tile_to_int("7z") == 33
    assert int_to_tile(33) == "7z"
    assert suit_of("5m") == "m"
    assert is_honor("7z")
    assert not is_honor("5m")

    counts, bc = hand_to_counts(["1m", "1m", "2m", "7z", "7z"], baida="7z")
    assert counts[tile_to_int("7z")] == 0
    assert bc == 2
    assert counts[tile_to_int("1m")] == 2
    assert counts[tile_to_int("2m")] == 1

    vis = build_visible_tiles(
        ["1m", "2m"],
        ["3m"],
        ["4m"],
        ["5m", "5m"],
        ["6m"],
    )
    assert vis["5m"] == 2
    assert vis["1m"] == 1
    print("tiles.py smoke-test OK")
