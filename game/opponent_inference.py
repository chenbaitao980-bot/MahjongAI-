from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import random
from typing import Any

from game.shanten import calc_shanten
from game.tiles import ALL_TILES, build_visible_tiles, hand_to_counts, tile_display_name, tile_sort_key


@dataclass(frozen=True)
class TileProbability:
    tile: str
    probability: float
    count: float = 0.0


@dataclass(frozen=True)
class DangerTile:
    tile: str
    probability: float
    level: str
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PredictedHand:
    tiles: list[str]
    probability: float
    shanten: int | None = None


@dataclass(frozen=True)
class OpponentPrediction:
    enabled: bool
    confidence: str
    particle_count: int
    monte_carlo_runs: int
    bayes_enabled: bool
    sampled_count: int
    tenpai_probability: float
    shanten_distribution: dict[str, float]
    tile_probabilities: list[TileProbability] = field(default_factory=list)
    wait_probabilities: list[TileProbability] = field(default_factory=list)
    danger_tiles: list[DangerTile] = field(default_factory=list)
    representative_hands: list[PredictedHand] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    summary: str = ""
    progress_summary: str = ""


def infer_opponent_hand(snapshot: dict[str, Any], config: dict[str, Any] | None = None) -> OpponentPrediction:
    cfg = _normalize_config(config)
    if not cfg["enabled"]:
        return OpponentPrediction(
            enabled=False,
            confidence="disabled",
            particle_count=cfg["particle_count"],
            monte_carlo_runs=cfg["monte_carlo_runs"],
            bayes_enabled=cfg["bayes_enabled"],
            sampled_count=0,
            tenpai_probability=0.0,
            shanten_distribution={},
            summary="opponent prediction disabled",
            progress_summary="disabled",
        )

    players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
    local = snapshot.get("local_player")
    opponent = snapshot.get("opponent_player")
    self_player = players.get(local) or players.get(str(local)) or {}
    enemy_player = players.get(opponent) or players.get(str(opponent)) or {}

    self_hand = _valid_tiles(self_player.get("hand", []))
    self_discards = _valid_tiles(self_player.get("discards", []))
    enemy_discards = _valid_tiles(enemy_player.get("discards", []))
    self_meld_tiles = _meld_tiles(self_player.get("melds", []))
    enemy_melds = list(enemy_player.get("melds", []) or [])
    enemy_meld_tiles = _meld_tiles(enemy_melds)
    enemy_hand_count = int(enemy_player.get("hand_count") or 0)
    enemy_meld_count = len(enemy_melds)
    remaining_tiles = int(snapshot.get("remaining_tiles") or 0)
    baida = str(snapshot.get("baida_tile") or "") if snapshot.get("baida_trusted") else ""

    visible = build_visible_tiles(self_hand, self_discards, self_meld_tiles, enemy_discards, enemy_meld_tiles)
    pool_counts = {tile: max(0, 4 - int(visible.get(tile, 0))) for tile in ALL_TILES}
    pool = [tile for tile, count in pool_counts.items() for _ in range(count)]
    hand_size = min(max(enemy_hand_count, 0), len(pool))

    evidence = _evidence(enemy_discards, enemy_meld_tiles, enemy_meld_count, enemy_hand_count, remaining_tiles, cfg)
    if hand_size <= 0 or not pool:
        return OpponentPrediction(
            enabled=True,
            confidence="low",
            particle_count=cfg["particle_count"],
            monte_carlo_runs=cfg["monte_carlo_runs"],
            bayes_enabled=cfg["bayes_enabled"],
            sampled_count=0,
            tenpai_probability=0.0,
            shanten_distribution={},
            evidence=evidence + ["no hidden hand count"],
            summary="visible information is not enough for hidden-hand sampling",
            progress_summary="waiting for opponent hand count",
        )

    rng = random.Random(_snapshot_seed(snapshot, cfg))
    sample_budget = max(1, cfg["particle_count"])
    samples: list[tuple[list[str], float, int | None, list[str]]] = []
    shanten_weight: dict[str, float] = {}
    tile_weight = {tile: 0.0 for tile in ALL_TILES}
    wait_weight = {tile: 0.0 for tile in ALL_TILES}
    total_weight = 0.0

    for _ in range(sample_budget):
        hand = sorted(rng.sample(pool, hand_size), key=tile_sort_key)
        shanten = _safe_shanten(hand, enemy_meld_count, baida)
        waits = _wait_tiles(hand, enemy_meld_count, baida, pool_counts) if shanten == 0 else []
        weight = _sample_weight(
            hand=hand,
            shanten=shanten,
            waits=waits,
            enemy_discards=enemy_discards,
            enemy_meld_tiles=enemy_meld_tiles,
            enemy_meld_count=enemy_meld_count,
            remaining_tiles=remaining_tiles,
            bayes_enabled=cfg["bayes_enabled"],
        )
        total_weight += weight
        key = "unknown" if shanten is None else str(shanten)
        shanten_weight[key] = shanten_weight.get(key, 0.0) + weight
        for tile in set(hand):
            tile_weight[tile] += weight * hand.count(tile)
        for tile in waits:
            wait_weight[tile] += weight
        samples.append((hand, weight, shanten, waits))

    if total_weight <= 0:
        total_weight = float(len(samples) or 1)

    shanten_distribution = {
        key: round(value / total_weight, 4)
        for key, value in sorted(shanten_weight.items(), key=lambda item: _shanten_sort_key(item[0]))
    }
    tenpai_probability = round(shanten_weight.get("0", 0.0) / total_weight, 4)
    if cfg["bayes_enabled"]:
        tenpai_probability = _bayes_adjust_tenpai(
            tenpai_probability,
            enemy_meld_count=enemy_meld_count,
            discard_count=len(enemy_discards),
            remaining_tiles=remaining_tiles,
        )

    tile_probs = _top_tile_probabilities(tile_weight, total_weight, hand_size, cfg["top_tile_count"])
    wait_probs = _top_wait_probabilities(wait_weight, total_weight, cfg["top_tile_count"])
    danger_tiles = _danger_tiles(wait_probs, tile_probs, enemy_discards, remaining_tiles)
    confidence = _confidence(sampled_count=len(samples), hand_size=hand_size, enemy_discards=enemy_discards, enemy_meld_count=enemy_meld_count)

    summary = _summary(tile_probs, wait_probs, tenpai_probability, confidence)
    progress_summary = _progress_summary(tenpai_probability, shanten_distribution, enemy_hand_count, len(enemy_discards), enemy_meld_count)
    return OpponentPrediction(
        enabled=True,
        confidence=confidence,
        particle_count=cfg["particle_count"],
        monte_carlo_runs=cfg["monte_carlo_runs"],
        bayes_enabled=cfg["bayes_enabled"],
        sampled_count=len(samples),
        tenpai_probability=tenpai_probability,
        shanten_distribution=shanten_distribution,
        tile_probabilities=tile_probs,
        wait_probabilities=wait_probs,
        danger_tiles=danger_tiles,
        representative_hands=[],
        evidence=evidence,
        summary=summary,
        progress_summary=progress_summary,
    )


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    return {
        "enabled": bool(config.get("enabled", True)),
        "particle_count": _bounded_int(config.get("particle_count", 5000), 100, 20000),
        "monte_carlo_runs": _bounded_int(config.get("monte_carlo_runs", 2000), 100, 10000),
        "bayes_enabled": bool(config.get("bayes_enabled", True)),
        "top_tile_count": _bounded_int(config.get("top_tile_count", 8), 3, 16),
        "representative_hand_count": _bounded_int(config.get("representative_hand_count", 3), 1, 5),
    }


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def _valid_tiles(values: Any) -> list[str]:
    return [str(tile) for tile in values or [] if str(tile) in ALL_TILES]


def _meld_tiles(melds: Any) -> list[str]:
    tiles: list[str] = []
    for meld in melds or []:
        if isinstance(meld, dict):
            tiles.extend(_valid_tiles(meld.get("tiles", [])))
    return tiles


def _safe_shanten(hand: list[str], meld_count: int, baida: str) -> int | None:
    try:
        counts, baida_count = hand_to_counts(hand, baida or None)
        return calc_shanten(counts, meld_count, baida_count)
    except Exception:
        return None


def _wait_tiles(hand: list[str], meld_count: int, baida: str, pool_counts: dict[str, int]) -> list[str]:
    waits: list[str] = []
    for tile in ALL_TILES:
        if int(pool_counts.get(tile, 0)) <= 0:
            continue
        shanten = _safe_shanten(hand + [tile], meld_count, baida)
        if shanten == -1:
            waits.append(tile)
    return waits


def _sample_weight(
    *,
    hand: list[str],
    shanten: int | None,
    waits: list[str],
    enemy_discards: list[str],
    enemy_meld_tiles: list[str],
    enemy_meld_count: int,
    remaining_tiles: int,
    bayes_enabled: bool,
) -> float:
    weight = 1.0
    if shanten is None:
        return 0.1
    if shanten <= 0:
        weight *= 2.2
    elif shanten == 1:
        weight *= 1.35
    elif shanten >= 3:
        weight *= 0.55

    if enemy_meld_count >= 2 and shanten <= 1:
        weight *= 1.35
    if remaining_tiles <= 30 and shanten <= 1:
        weight *= 1.45
    if remaining_tiles <= 16 and shanten == 0:
        weight *= 1.4
    if waits:
        weight *= 1.0 + min(0.6, len(waits) * 0.04)

    focus_suits = [tile[-1:] for tile in enemy_meld_tiles if tile and tile[-1:] != "z"]
    if focus_suits:
        dominant = max(set(focus_suits), key=focus_suits.count)
        same_suit_count = sum(1 for tile in hand if tile.endswith(dominant))
        weight *= 1.0 + min(0.7, same_suit_count / max(1, len(hand)))

    if bayes_enabled:
        recent_discards = set(enemy_discards[-4:])
        overlap = len(recent_discards.intersection(hand))
        if overlap:
            weight *= max(0.45, 1.0 - overlap * 0.12)
    return max(0.01, weight)


def _bayes_adjust_tenpai(base: float, *, enemy_meld_count: int, discard_count: int, remaining_tiles: int) -> float:
    odds = base / max(0.0001, 1.0 - base)
    if enemy_meld_count >= 3:
        odds *= 1.9
    elif enemy_meld_count == 2:
        odds *= 1.45
    if discard_count >= 8:
        odds *= 1.25
    if remaining_tiles <= 30:
        odds *= 1.35
    if remaining_tiles <= 16:
        odds *= 1.45
    return round(odds / (1.0 + odds), 4)


def _top_tile_probabilities(weights: dict[str, float], total_weight: float, hand_size: int, limit: int) -> list[TileProbability]:
    denom = total_weight * max(1, hand_size)
    items = [
        TileProbability(tile=tile, probability=round(weight / denom, 4), count=round(weight / total_weight, 3))
        for tile, weight in weights.items()
        if weight > 0
    ]
    return sorted(items, key=lambda item: (-item.probability, tile_sort_key(item.tile)))[:limit]


def _top_wait_probabilities(weights: dict[str, float], total_weight: float, limit: int) -> list[TileProbability]:
    items = [
        TileProbability(tile=tile, probability=round(weight / total_weight, 4), count=0.0)
        for tile, weight in weights.items()
        if weight > 0
    ]
    return sorted(items, key=lambda item: (-item.probability, tile_sort_key(item.tile)))[:limit]


def _danger_tiles(waits: list[TileProbability], tile_probs: list[TileProbability], enemy_discards: list[str], remaining_tiles: int) -> list[DangerTile]:
    tile_map = {item.tile: item.probability * 0.45 for item in tile_probs}
    for item in waits:
        tile_map[item.tile] = tile_map.get(item.tile, 0.0) + item.probability * 0.8
    dangers: list[DangerTile] = []
    for tile, score in tile_map.items():
        if tile in enemy_discards:
            score *= 0.35
        if remaining_tiles <= 30:
            score *= 1.2
        if remaining_tiles <= 16:
            score *= 1.25
        probability = round(min(0.99, score), 4)
        level = "high" if probability >= 0.35 else ("medium" if probability >= 0.16 else "low")
        reasons = []
        if any(item.tile == tile for item in waits):
            reasons.append("possible wait")
        if any(item.tile == tile for item in tile_probs):
            reasons.append("likely held")
        if tile in enemy_discards:
            reasons.append("same tile already discarded")
        dangers.append(DangerTile(tile=tile, probability=probability, level=level, reasons=reasons))
    return sorted(dangers, key=lambda item: (-item.probability, tile_sort_key(item.tile)))[:8]


def _representative_hands(samples: list[tuple[list[str], float, int | None, list[str]]], total_weight: float, limit: int) -> list[PredictedHand]:
    best = sorted(samples, key=lambda item: (-item[1], item[2] if item[2] is not None else 99, item[0]))[: max(limit * 3, limit)]
    seen: set[tuple[str, ...]] = set()
    result: list[PredictedHand] = []
    for hand, weight, shanten, _waits in best:
        key = tuple(hand)
        if key in seen:
            continue
        seen.add(key)
        result.append(PredictedHand(tiles=list(hand), probability=round(weight / total_weight, 4), shanten=shanten))
        if len(result) >= limit:
            break
    return result


def _confidence(sampled_count: int, hand_size: int, enemy_discards: list[str], enemy_meld_count: int) -> str:
    score = 0
    if sampled_count >= 5000:
        score += 2
    elif sampled_count >= 1000:
        score += 1
    if hand_size >= 8:
        score += 1
    if len(enemy_discards) >= 5:
        score += 1
    if enemy_meld_count:
        score += 1
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _evidence(
    enemy_discards: list[str],
    enemy_meld_tiles: list[str],
    enemy_meld_count: int,
    enemy_hand_count: int,
    remaining_tiles: int,
    cfg: dict[str, Any],
) -> list[str]:
    return [
        f"discards={len(enemy_discards)}",
        f"melds={enemy_meld_count}",
        f"hand_count={enemy_hand_count}",
        f"remaining={remaining_tiles}",
        f"particle={cfg['particle_count']}",
        f"mc={cfg['monte_carlo_runs']}",
        f"bayes={'on' if cfg['bayes_enabled'] else 'off'}",
        f"meld_tiles={len(enemy_meld_tiles)}",
    ]


def _summary(
    tile_probs: list[TileProbability],
    wait_probs: list[TileProbability],
    tenpai_probability: float,
    confidence: str,
) -> str:
    held = " / ".join(f"{tile_display_name(item.tile)} {item.probability:.0%}" for item in tile_probs[:4]) or "none"
    waits = " / ".join(f"{tile_display_name(item.tile)} {item.probability:.0%}" for item in wait_probs[:4]) or "none"
    return f"confidence={confidence}; tenpai={tenpai_probability:.0%}; likely held: {held}; waits: {waits}"


def _progress_summary(
    tenpai_probability: float,
    shanten_distribution: dict[str, float],
    enemy_hand_count: int,
    discard_count: int,
    enemy_meld_count: int,
) -> str:
    parts = [f"tenpai={tenpai_probability:.0%}"]
    if shanten_distribution:
        dist = " / ".join(f"{key}:{value:.0%}" for key, value in shanten_distribution.items())
        parts.append(f"shanten {dist}")
    parts.append(f"discards={discard_count}")
    parts.append(f"melds={enemy_meld_count}")
    parts.append(f"hand_count={enemy_hand_count}")
    return "; ".join(parts)


def _snapshot_seed(snapshot: dict[str, Any], cfg: dict[str, Any]) -> int:
    players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
    public_players = {}
    opponent = snapshot.get("opponent_player")
    for pid, player in players.items():
        if not isinstance(player, dict):
            continue
        public_player = dict(player)
        if str(pid) == str(opponent):
            public_player["hand"] = []
        public_players[str(pid)] = public_player
    text = repr(
        (
            snapshot.get("phase"),
            snapshot.get("current_turn"),
            snapshot.get("remaining_tiles"),
            snapshot.get("baida_tile"),
            public_players,
            cfg["particle_count"],
            cfg["monte_carlo_runs"],
            cfg["bayes_enabled"],
        )
    )
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:16], 16)


def _shanten_sort_key(value: str) -> tuple[int, str]:
    try:
        return (int(value), value)
    except ValueError:
        return (99, value)
