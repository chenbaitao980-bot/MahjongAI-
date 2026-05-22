from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from game.tiles import suit_of


@dataclass(frozen=True)
class StrategyModelContext:
    current_shanten: int | None
    remaining_tiles: int
    caishen_tile: str | None
    enemy_discards: list[str] = field(default_factory=list)
    self_discards: list[str] = field(default_factory=list)
    enemy_meld_tiles: list[str] = field(default_factory=list)
    self_meld_tiles: list[str] = field(default_factory=list)
    opponent_prediction: Any = None


@dataclass(frozen=True)
class StrategyModelScore:
    discard: str
    score: float
    source: str
    reasons: list[str]
    features: dict[str, float]


def score_discard_candidate(candidate: Any, ctx: StrategyModelContext) -> StrategyModelScore:
    """Feature-based discard ranker used as the local model adapter.

    This is intentionally constrained to already-legal discard candidates from the
    hard calculator. It never invents an action; it only reorders known candidates.
    """
    discard = str(getattr(candidate, "discard", ""))
    shanten_after = int(getattr(candidate, "shanten_after", 99))
    ukeire_count = int(getattr(candidate, "ukeire_count", 0))
    shanten_delta = int(getattr(candidate, "shanten_delta", 0))
    is_caishen = bool(getattr(candidate, "is_caishen", False))
    shape_value = int(getattr(candidate, "shape_value", 0))
    danger = _danger_score(discard, ctx)
    is_raw = _is_raw_tile(discard, ctx)
    suit_focus = _suit_focus_after_discard(candidate)

    # 对手预测相关计算
    opponent_danger_bonus = 0.0
    tenpai_danger_multiplier = 1.0
    opponent_danger_level = ""
    op = ctx.opponent_prediction
    if op and getattr(op, "enabled", False):
        tenpai = float(getattr(op, "tenpai_probability", 0.0))
        tenpai_danger_multiplier = 1.0 + tenpai * 0.8
        # 危险牌直接惩罚
        for dt in getattr(op, "danger_tiles", []):
            if getattr(dt, "tile", "") == discard:
                level = getattr(dt, "level", "")
                if level == "high":
                    opponent_danger_bonus += 80.0
                    opponent_danger_level = "高"
                elif level == "medium":
                    opponent_danger_bonus += 35.0
                    if not opponent_danger_level:
                        opponent_danger_level = "中"
                else:
                    opponent_danger_bonus += 12.0
                    if not opponent_danger_level:
                        opponent_danger_level = "低"
        # 等待牌惩罚
        for wp in getattr(op, "wait_probabilities", []):
            if getattr(wp, "tile", "") == discard:
                prob = float(getattr(wp, "probability", 0.0))
                opponent_danger_bonus += prob * 60.0
                if not opponent_danger_level:
                    opponent_danger_level = "中"

    features = {
        "shanten_after": float(shanten_after),
        "ukeire_count": float(ukeire_count),
        "shanten_delta": float(shanten_delta),
        "is_caishen": 1.0 if is_caishen else 0.0,
        "shape_value": float(shape_value),
        "danger": float(danger),
        "is_raw": 1.0 if is_raw else 0.0,
        "suit_focus": suit_focus,
        "opponent_danger_bonus": opponent_danger_bonus,
        "tenpai_multiplier": tenpai_danger_multiplier,
    }

    score = 0.0
    score -= shanten_after * 1000.0
    score -= max(0, shanten_delta) * 650.0
    score += max(0, -shanten_delta) * 250.0
    score += ukeire_count * 9.0
    score += shape_value * 4.0
    score += suit_focus * 30.0
    score -= danger * _danger_weight(ctx.remaining_tiles) * tenpai_danger_multiplier
    score -= opponent_danger_bonus
    if is_caishen:
        score -= 800.0
    if is_raw and ctx.remaining_tiles <= 30:
        score -= 120.0

    reasons = _reasons(
        shanten_after=shanten_after,
        ukeire_count=ukeire_count,
        shanten_delta=shanten_delta,
        is_caishen=is_caishen,
        shape_value=shape_value,
        danger=danger,
        is_raw=is_raw,
        remaining_tiles=ctx.remaining_tiles,
        opponent_danger_level=opponent_danger_level,
    )
    return StrategyModelScore(
        discard=discard,
        score=round(score, 1),
        source="local_feature_model",
        reasons=reasons,
        features=features,
    )


def rank_discard_candidates(candidates: list[Any], ctx: StrategyModelContext) -> list[Any]:
    scored = []
    for candidate in candidates:
        model = score_discard_candidate(candidate, ctx)
        setattr(candidate, "model_score", model.score)
        setattr(candidate, "model_source", model.source)
        setattr(candidate, "model_reasons", model.reasons)
        setattr(candidate, "model_features", model.features)
        scored.append(candidate)
    return sorted(
        scored,
        key=lambda c: (
            int(getattr(c, "shanten_after", 99)),
            bool(getattr(c, "is_caishen", False)),
            -float(getattr(c, "model_score", -1e9)),
            -int(getattr(c, "ukeire_count", 0)),
            str(getattr(c, "discard", "")),
        ),
    )


def _danger_score(tile: str, ctx: StrategyModelContext) -> int:
    if not tile:
        return 100
    visible_count = (
        ctx.enemy_discards.count(tile)
        + ctx.self_discards.count(tile)
        + ctx.enemy_meld_tiles.count(tile)
        + ctx.self_meld_tiles.count(tile)
    )
    if visible_count >= 4:
        return 0

    danger = 25
    if tile in ctx.enemy_discards:
        danger -= 25
    if visible_count == 1:
        danger -= 5
    elif visible_count == 2:
        danger -= 12
    elif visible_count == 3:
        danger -= 25

    if tile[-1:] in ("m", "p", "s"):
        rank = int(tile[:-1])
        if 3 <= rank <= 7:
            danger += 10
    elif visible_count == 0:
        danger += 8

    enemy_suits = [suit_of(t) for t in ctx.enemy_meld_tiles if t and suit_of(t) != "z"]
    if enemy_suits:
        dominant = max(set(enemy_suits), key=enemy_suits.count)
        if enemy_suits.count(dominant) / len(enemy_suits) >= 0.75:
            if suit_of(tile) == dominant:
                danger += 35
            elif suit_of(tile) != "z":
                danger -= 8

    if ctx.remaining_tiles <= 30:
        danger += 12
    if ctx.remaining_tiles <= 16:
        danger += 15
    return max(0, min(100, danger))


def _danger_weight(remaining_tiles: int) -> float:
    if remaining_tiles <= 16:
        return 5.0
    if remaining_tiles <= 30:
        return 3.0
    return 1.4


def _is_raw_tile(tile: str, ctx: StrategyModelContext) -> bool:
    return bool(tile) and tile not in ctx.enemy_discards and tile not in ctx.self_discards


def _suit_focus_after_discard(candidate: Any) -> float:
    tiles = [
        t
        for t in list(getattr(candidate, "ukeire_tiles", []))
        if isinstance(t, str) and len(t) >= 2 and suit_of(t) != "z"
    ]
    if not tiles:
        return 0.0
    suits = [suit_of(t) for t in tiles]
    return max(suits.count(suit) for suit in set(suits)) / len(suits)


def _reasons(
    *,
    shanten_after: int,
    ukeire_count: int,
    shanten_delta: int,
    is_caishen: bool,
    shape_value: int,
    danger: int,
    is_raw: bool,
    remaining_tiles: int,
    opponent_danger_level: str = "",
) -> list[str]:
    reasons: list[str] = []
    if shanten_delta < 0:
        reasons.append("进听")
    elif shanten_delta == 0:
        reasons.append("同档向听")
    else:
        reasons.append("退听惩罚")
    reasons.append(f"打后向听 {shanten_after}")
    reasons.append(f"有效进张 {ukeire_count}")
    if is_caishen:
        reasons.append("打财神高惩罚")
    else:
        reasons.append("保留财神")
    if shape_value >= 45:
        reasons.append("整理边张/孤张")
    elif shape_value >= 30:
        reasons.append("整理坎张")
    elif shape_value < 0:
        reasons.append("保留成组/对子")
    if danger >= 70:
        reasons.append("高危险度")
    elif danger <= 25:
        reasons.append("相对安全")
    if is_raw and remaining_tiles <= 30:
        reasons.append("生牌阶段谨慎")
    if opponent_danger_level:
        reasons.append(f"[预测]对手预测{opponent_danger_level}危险")
    return reasons
