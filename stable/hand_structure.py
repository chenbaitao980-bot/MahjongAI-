from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from game.tiles import rank_of, suit_of, tile_display_name, tile_sort_key


@dataclass(frozen=True)
class HandStructureGroup:
    kind: str
    tiles: tuple[str, ...]
    label: str


def build_hand_structure_arrangements(
    hand: list[str],
    melds: list[dict[str, Any]] | None = None,
    recommended_discard: str = "",
    limit: int = 3,
) -> list[list[HandStructureGroup]]:
    """Build several display-only hand arrangements; never used for win logic."""
    prefix = _meld_groups(melds)
    counts = _tile_counts(hand)
    arrangements = _enumerate_arrangements(counts, max_results=1200)
    if not arrangements:
        arrangements = [[]]

    keyed: dict[tuple[tuple[str, tuple[str, ...]], ...], list[HandStructureGroup]] = {}
    for groups in arrangements:
        ordered = _sort_groups(prefix + groups)
        key = tuple((group.kind, group.tiles) for group in ordered)
        keyed.setdefault(key, ordered)

    unique = list(keyed.values())
    unique.sort(key=lambda groups: _arrangement_score(groups, recommended_discard))
    return _select_arrangements(unique, recommended_discard, max(1, limit))


def build_hand_structure_groups(
    hand: list[str],
    melds: list[dict[str, Any]] | None = None,
    recommended_discard: str = "",
) -> list[HandStructureGroup]:
    """Build display-only hand groups; this does not participate in win logic."""
    arrangements = build_hand_structure_arrangements(hand, melds, recommended_discard, limit=1)
    return arrangements[0] if arrangements else []


def _tile_counts(hand: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tile in sorted(hand, key=tile_sort_key):
        counts[tile] = counts.get(tile, 0) + 1
    return counts


def _meld_groups(melds: list[dict[str, Any]] | None = None) -> list[HandStructureGroup]:
    groups: list[HandStructureGroup] = []
    for meld in melds or []:
        tiles = tuple(sorted([str(t) for t in meld.get("tiles", []) if t], key=tile_sort_key))
        if not tiles:
            continue
        meld_type = str(meld.get("type") or "")
        label = {
            "chi": "副露顺子",
            "pon": "副露刻子",
            "kan_open": "明杠",
            "kan_closed": "暗杠",
            "kan_added": "补杠",
        }.get(meld_type, "副露")
        groups.append(HandStructureGroup("meld", tiles, label))
    return groups


def _enumerate_arrangements(
    counts: dict[str, int],
    groups: list[HandStructureGroup] | None = None,
    max_results: int = 80,
) -> list[list[HandStructureGroup]]:
    groups = groups or []
    tile = _first_remaining_tile(counts)
    if not tile:
        return [groups]

    results: list[list[HandStructureGroup]] = []
    for next_counts, group in _next_group_options(counts, tile):
        for result in _enumerate_arrangements(next_counts, groups + [group], max_results):
            results.append(result)
            if len(results) >= max_results:
                return results
    return results


def _first_remaining_tile(counts: dict[str, int]) -> str:
    remaining = [tile for tile, count in counts.items() if count > 0]
    return sorted(remaining, key=tile_sort_key)[0] if remaining else ""


def _next_group_options(
    counts: dict[str, int],
    tile: str,
) -> list[tuple[dict[str, int], HandStructureGroup]]:
    options: list[tuple[dict[str, int], HandStructureGroup]] = []

    if counts.get(tile, 0) >= 3:
        options.append((_remove_tiles(counts, [tile, tile, tile]), HandStructureGroup("triplet", (tile, tile, tile), "刻子")))

    tile_suit = suit_of(tile)
    tile_rank = rank_of(tile)
    if tile_suit in ("m", "s", "p") and isinstance(tile_rank, int):
        sequence_options = (
            (tile_rank, tile_rank + 1, tile_rank + 2),
            (tile_rank - 1, tile_rank, tile_rank + 1),
            (tile_rank - 2, tile_rank - 1, tile_rank),
        )
        for ranks in sequence_options:
            if ranks[0] < 1 or ranks[-1] > 9:
                continue
            seq = [f"{rank}{tile_suit}" for rank in ranks]
            if all(counts.get(seq_tile, 0) > 0 for seq_tile in seq):
                options.append((_remove_tiles(counts, seq), HandStructureGroup("sequence", tuple(seq), "顺子")))

    if counts.get(tile, 0) >= 2:
        options.append((_remove_tiles(counts, [tile, tile]), HandStructureGroup("pair", (tile, tile), "将牌候选")))

    if tile_suit in ("m", "s", "p") and isinstance(tile_rank, int):
        for other_rank in (tile_rank + 1, tile_rank - 1, tile_rank + 2, tile_rank - 2):
            if other_rank < 1 or other_rank > 9:
                continue
            other = f"{other_rank}{tile_suit}"
            if counts.get(other, 0) <= 0:
                continue
            pair = tuple(sorted((tile, other), key=tile_sort_key))
            gap = abs(tile_rank - other_rank)
            edge = gap == 1 and {tile_rank, other_rank} in ({1, 2}, {8, 9})
            kind = "edge_wait" if edge else "taatsu"
            label = "边张搭子" if edge else ("坎张搭子" if gap == 2 else "两面搭子")
            options.append((_remove_tiles(counts, [tile, other]), HandStructureGroup(kind, pair, label)))

    options.append((_remove_tiles(counts, [tile]), HandStructureGroup("single", (tile,), "孤张")))
    return _dedupe_options(options)


def _remove_tiles(counts: dict[str, int], tiles: list[str]) -> dict[str, int]:
    next_counts = dict(counts)
    for tile in tiles:
        next_counts[tile] = next_counts.get(tile, 0) - 1
    return next_counts


def _dedupe_options(
    options: list[tuple[dict[str, int], HandStructureGroup]],
) -> list[tuple[dict[str, int], HandStructureGroup]]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[tuple[dict[str, int], HandStructureGroup]] = []
    for counts, group in options:
        key = (group.kind, group.tiles)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((counts, group))
    return deduped


def _sort_groups(groups: list[HandStructureGroup]) -> list[HandStructureGroup]:
    order = {
        "meld": 0,
        "triplet": 1,
        "sequence": 2,
        "pair": 3,
        "taatsu": 4,
        "edge_wait": 4,
        "single": 5,
    }
    return sorted(groups, key=lambda group: (order.get(group.kind, 9), tile_sort_key(group.tiles[0] if group.tiles else "")))


def _arrangement_score(groups: list[HandStructureGroup], recommended_discard: str = "") -> tuple[int, int, int, str]:
    recommended_rank = _recommended_group_rank(groups, recommended_discard)
    singles = sum(1 for group in groups if group.kind == "single")
    completed = sum(1 for group in groups if group.kind in ("meld", "triplet", "sequence"))
    key = "|".join(f"{group.kind}:{','.join(group.tiles)}" for group in groups)
    return (recommended_rank, singles, -completed, key)


def _select_arrangements(
    arrangements: list[list[HandStructureGroup]],
    recommended_discard: str,
    limit: int,
) -> list[list[HandStructureGroup]]:
    if not arrangements:
        return []
    selected = [arrangements[0]]
    if len(selected) >= limit:
        return selected

    seen_single_sets = {_single_tiles(arrangements[0])}
    remaining = arrangements[1:]
    if recommended_discard:
        same_suit_alt = _first_same_suit_single_alternative(remaining, recommended_discard, seen_single_sets)
        if same_suit_alt:
            selected.append(same_suit_alt)
            seen_single_sets.add(_single_tiles(same_suit_alt))
            remaining = [groups for groups in remaining if groups is not same_suit_alt]
            if len(selected) >= limit:
                return selected
        remaining = sorted(
            remaining,
            key=lambda groups: (
                1 if recommended_discard in _single_tiles(groups) else 0,
                _arrangement_score(groups, recommended_discard),
            ),
        )

    for groups in remaining:
        single_set = _single_tiles(groups)
        if single_set in seen_single_sets:
            continue
        selected.append(groups)
        seen_single_sets.add(single_set)
        if len(selected) >= limit:
            return selected

    for groups in arrangements[1:]:
        if groups in selected:
            continue
        selected.append(groups)
        if len(selected) >= limit:
            break
    return selected


def _first_same_suit_single_alternative(
    arrangements: list[list[HandStructureGroup]],
    recommended_discard: str,
    seen_single_sets: set[tuple[str, ...]],
) -> list[HandStructureGroup] | None:
    recommended_suit = suit_of(recommended_discard)
    for groups in arrangements:
        single_set = _single_tiles(groups)
        if single_set in seen_single_sets or recommended_discard in single_set:
            continue
        if any(suit_of(tile) == recommended_suit for tile in single_set):
            return groups
    return None


def _single_tiles(groups: list[HandStructureGroup]) -> tuple[str, ...]:
    return tuple(sorted((group.tiles[0] for group in groups if group.kind == "single" and group.tiles), key=tile_sort_key))


def _recommended_group_rank(groups: list[HandStructureGroup], recommended_discard: str = "") -> int:
    if not recommended_discard:
        return 9
    ranks = []
    for group in groups:
        if recommended_discard not in group.tiles:
            continue
        if group.kind == "single":
            ranks.append(0)
        elif group.kind == "edge_wait":
            ranks.append(1)
        elif group.label == "坎张搭子":
            ranks.append(2)
        elif group.kind == "taatsu":
            ranks.append(3)
        elif group.kind == "pair":
            ranks.append(4)
        elif group.kind == "sequence":
            ranks.append(5)
        else:
            ranks.append(6)
    return min(ranks, default=9)


def describe_hand_structure(groups: list[HandStructureGroup]) -> str:
    if not groups:
        return "（空）"
    return "；".join(
        f"{group.label}[{' '.join(tile_display_name(tile) for tile in group.tiles)}]"
        for group in groups
    )
