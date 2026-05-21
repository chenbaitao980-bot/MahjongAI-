from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from game.shanten import calc_shanten
from game.stable_strategy_model import StrategyModelContext, rank_discard_candidates
from game.tiles import ALL_TILES, build_visible_tiles, hand_to_counts, tile_display_name
from game.ukeire import calc_ukeire


@dataclass
class HardDiscardCandidate:
    discard: str
    shanten_after: int
    ting_tiles: list[dict[str, Any]] = field(default_factory=list)
    ukeire_tiles: list[str] = field(default_factory=list)
    ukeire_count: int = 0
    is_caishen: bool = False
    shanten_delta: int = 0
    model_score: float = 0.0
    model_source: str = ""
    model_reasons: list[str] = field(default_factory=list)
    model_features: dict[str, float] = field(default_factory=dict)


@dataclass
class StableHardAnalysis:
    current_status: str
    caishen_text: str
    current_shanten: int | None
    is_ting: bool
    ting_tiles: list[dict[str, Any]]
    best_ting_discards: list[HardDiscardCandidate]
    effective_tiles: list[str]
    effective_count: int
    current_advice: str
    advice_reason: str
    strong_reminders: list[str]
    caishen_risk: str
    opponent_hand_prediction: str
    opponent_progress_prediction: str
    data_confidence: str
    recommended_discard: str = ""
    candidates: list[HardDiscardCandidate] = field(default_factory=list)
    model_status: str = "waiting"
    recommendation_source: str = ""


def analyze_snapshot(snapshot: dict[str, Any]) -> StableHardAnalysis:
    local = snapshot.get("local_player")
    opponent = snapshot.get("opponent_player")
    players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
    self_player = players.get(local) or players.get(str(local)) or {}
    enemy_player = players.get(opponent) or players.get(str(opponent)) or {}

    hand = _valid_tiles(self_player.get("hand", []))
    self_discards = _valid_tiles(self_player.get("discards", []))
    enemy_discards = _valid_tiles(enemy_player.get("discards", []))
    self_meld_tiles = _meld_tiles(self_player.get("melds", []))
    enemy_meld_tiles = _meld_tiles(enemy_player.get("melds", []))
    meld_count = len(self_player.get("melds", []) or [])
    baida = str(snapshot.get("baida_tile") or "") or None
    baida_trusted = bool(snapshot.get("baida_trusted"))
    effective_count = len(hand) + len(self_meld_tiles)
    remaining_tiles = int(snapshot.get("remaining_tiles") or 0)

    current_status = infer_current_status(snapshot, effective_count)
    caishen_text = tile_display_name(baida) if baida and baida_trusted else "等待财神"
    visible = build_visible_tiles(hand, self_discards, self_meld_tiles, enemy_discards, enemy_meld_tiles)

    confidence_parts = _data_confidence(snapshot, hand, effective_count)
    can_recommend = _can_recommend(snapshot, hand, baida_trusted, effective_count)

    current_shanten: int | None = None
    if hand and baida and baida_trusted:
        counts, baida_count = hand_to_counts(hand, baida)
        current_shanten = calc_shanten(counts, meld_count, baida_count)

    candidates: list[HardDiscardCandidate] = []
    if can_recommend and baida:
        candidates = _discard_candidates(hand, meld_count, baida, visible, current_shanten)
        candidates = rank_discard_candidates(
            candidates,
            StrategyModelContext(
                current_shanten=current_shanten,
                remaining_tiles=remaining_tiles,
                caishen_tile=baida,
                enemy_discards=enemy_discards,
                self_discards=self_discards,
                enemy_meld_tiles=enemy_meld_tiles,
                self_meld_tiles=self_meld_tiles,
            ),
        )

    ting_tiles = _current_ting_tiles(hand, meld_count, baida, visible, effective_count, candidates)
    is_ting = bool(ting_tiles) or current_shanten == 0
    best_ting_discards = [
        c for c in candidates if c.ting_tiles and c.shanten_after == 0
    ]

    recommended = _choose_recommendation(candidates)
    effective_tiles = list(recommended.ukeire_tiles) if recommended else []
    effective_count_after = int(recommended.ukeire_count) if recommended else 0
    recommended_discard = recommended.discard if recommended else ""

    strong_reminders = _strong_reminders(
        can_recommend=can_recommend,
        hand=hand,
        baida=baida,
        current_shanten=current_shanten,
        recommended=recommended,
        candidates=candidates,
        is_ting=is_ting,
    )
    caishen_risk = _caishen_risk(baida, recommended, candidates)
    opponent_hand_prediction, opponent_progress_prediction = _opponent_predictions(
        enemy_discards=enemy_discards,
        enemy_meld_tiles=enemy_meld_tiles,
        enemy_meld_count=len(enemy_player.get("melds", []) or []),
        enemy_hand_count=int(enemy_player.get("hand_count") or 0),
        remaining_tiles=remaining_tiles,
        current_turn=str(snapshot.get("current_turn") or "none"),
        visible=visible,
    )
    current_advice = (
        f"建议打 {tile_display_name(recommended_discard)}"
        if recommended_discard and can_recommend
        else "等待完整数据"
    )
    advice_reason = _advice_reason(recommended, candidates, current_shanten, is_ting, can_recommend)
    model_status = (
        "local_feature_model"
        if recommended_discard and can_recommend
        else _blocked_reason(snapshot, effective_count)
    )

    return StableHardAnalysis(
        current_status=current_status,
        caishen_text=caishen_text,
        current_shanten=current_shanten,
        is_ting=is_ting,
        ting_tiles=ting_tiles,
        best_ting_discards=best_ting_discards,
        effective_tiles=effective_tiles,
        effective_count=effective_count_after,
        current_advice=current_advice,
        advice_reason=advice_reason,
        strong_reminders=strong_reminders,
        caishen_risk=caishen_risk,
        opponent_hand_prediction=opponent_hand_prediction,
        opponent_progress_prediction=opponent_progress_prediction,
        data_confidence="；".join(confidence_parts),
        recommended_discard=recommended_discard,
        candidates=candidates,
        model_status=model_status,
        recommendation_source=(recommended.model_source if recommended else ""),
    )


def infer_current_status(snapshot: dict[str, Any], effective_count: int | None = None) -> str:
    if not snapshot.get("hand_trusted"):
        return "等待手牌"
    if snapshot.get("optional_actions"):
        return "可操作"
    turn = str(snapshot.get("current_turn") or "none")
    if turn == "self":
        return "等待出牌" if effective_count in (None, 14) else "等待响应"
    if turn == "enemy":
        return "等待对方"
    return "等待响应"


def getTingTiles(
    hand: list[str],
    meld_count: int,
    baida: str | None,
    visible_tiles: dict[str, int],
) -> list[dict[str, Any]]:
    return get_ting_tiles(hand, meld_count, baida, visible_tiles)


def get_ting_tiles(
    hand: list[str],
    meld_count: int,
    baida: str | None,
    visible_tiles: dict[str, int],
) -> list[dict[str, Any]]:
    if not baida:
        return []
    waits: list[dict[str, Any]] = []
    for tile in ALL_TILES:
        remaining = 4 - int(visible_tiles.get(tile, 0))
        if remaining <= 0:
            continue
        test_hand = list(hand) + [tile]
        counts, baida_count = hand_to_counts(test_hand, baida)
        if calc_shanten(counts, meld_count, baida_count) == -1:
            waits.append({"tile": tile, "remaining": remaining})
    return waits


def _discard_candidates(
    hand: list[str],
    meld_count: int,
    baida: str,
    visible: dict[str, int],
    current_shanten: int | None,
) -> list[HardDiscardCandidate]:
    result: list[HardDiscardCandidate] = []
    for discard in sorted(set(hand)):
        after = list(hand)
        after.remove(discard)
        ukeire = calc_ukeire(after, meld_count, baida, visible)
        ting_tiles = get_ting_tiles(after, meld_count, baida, visible)
        shanten_after = int(ukeire.get("current_shanten", 99))
        result.append(
            HardDiscardCandidate(
                discard=discard,
                shanten_after=shanten_after,
                ting_tiles=ting_tiles,
                ukeire_tiles=list(ukeire.get("tiles", [])),
                ukeire_count=int(ukeire.get("count", 0)),
                is_caishen=discard == baida,
                shanten_delta=(
                    shanten_after - current_shanten
                    if current_shanten is not None
                    else 0
                ),
            )
        )
    result.sort(key=lambda c: (c.is_caishen, c.shanten_after, -c.ukeire_count, c.discard))
    return result


def _choose_recommendation(candidates: list[HardDiscardCandidate]) -> HardDiscardCandidate | None:
    if not candidates:
        return None
    return candidates[0]


def _current_ting_tiles(
    hand: list[str],
    meld_count: int,
    baida: str | None,
    visible: dict[str, int],
    effective_count: int,
    candidates: list[HardDiscardCandidate],
) -> list[dict[str, Any]]:
    if not baida:
        return []
    if effective_count % 3 == 1:
        return get_ting_tiles(hand, meld_count, baida, visible)
    if effective_count % 3 == 2:
        merged: dict[str, int] = {}
        for candidate in candidates:
            if candidate.shanten_after != 0:
                continue
            for wait in candidate.ting_tiles:
                tile = str(wait.get("tile") or "")
                if not tile:
                    continue
                merged[tile] = max(merged.get(tile, 0), int(wait.get("remaining", 0)))
        return [{"tile": tile, "remaining": merged[tile]} for tile in sorted(merged)]
    return []


def _strong_reminders(
    *,
    can_recommend: bool,
    hand: list[str],
    baida: str | None,
    current_shanten: int | None,
    recommended: HardDiscardCandidate | None,
    candidates: list[HardDiscardCandidate],
    is_ting: bool,
) -> list[str]:
    reminders: list[str] = []
    if not can_recommend:
        reminders.append("数据不足：未拿到完整手牌、财神或当前事件时不乱给建议")
        return reminders
    if baida and baida in hand:
        reminders.append("打财神属于硬风险，除非没有其他合法选择")
    if recommended and recommended.is_caishen:
        reminders.append("当前推荐会打财神，请人工确认")
    if recommended and current_shanten is not None and recommended.shanten_after > current_shanten:
        reminders.append("当前推荐会导致向听变差")
    if is_ting:
        retreating = [c for c in candidates if c.shanten_after > 0]
        if retreating:
            reminders.append("已听牌，避免选择退听打法")
    if candidates:
        best_shanten = min(c.shanten_after for c in candidates)
        if recommended and recommended.shanten_after > best_shanten:
            reminders.append("存在更低向听打法，当前推荐可能漏听")
    return reminders or ["无硬错误"]


def _caishen_risk(
    baida: str | None,
    recommended: HardDiscardCandidate | None,
    candidates: list[HardDiscardCandidate],
) -> str:
    if not baida:
        return "等待财神后评估"
    if not recommended:
        return "等待可计算出牌"
    if recommended.is_caishen:
        return "高：推荐牌是财神，会损失 wildcard 价值"
    caishen_candidate = next((c for c in candidates if c.discard == baida), None)
    if not caishen_candidate:
        return "低：手牌中没有可打财神"
    best_non_caishen = min((c for c in candidates if not c.is_caishen), key=lambda c: (c.shanten_after, -c.ukeire_count), default=None)
    if best_non_caishen and (
        caishen_candidate.shanten_after > best_non_caishen.shanten_after
        or caishen_candidate.ukeire_count < best_non_caishen.ukeire_count
    ):
        return "高：打财神会让向听或进张变差"
    return "中：打财神虽未立即变差，但会损失替代价值"


def _advice_reason(
    recommended: HardDiscardCandidate | None,
    candidates: list[HardDiscardCandidate],
    current_shanten: int | None,
    is_ting: bool,
    has_core_data: bool,
) -> str:
    if not has_core_data:
        return "数据可信度不足，先等待抓包补齐手牌、财神和当前事件"
    if not recommended:
        return "当前手牌张数不适合枚举出牌"
    reasons: list[str] = []
    if recommended.model_reasons:
        reasons.extend(recommended.model_reasons[:4])
    if is_ting and recommended.ting_tiles:
        reasons.append("不退听")
    if current_shanten is not None and recommended.shanten_after < current_shanten:
        reasons.append("进听")
    max_ukeire = max((c.ukeire_count for c in candidates if not c.is_caishen), default=recommended.ukeire_count)
    if recommended.ukeire_count >= max_ukeire:
        reasons.append("有效进张最多")
    if not recommended.is_caishen:
        reasons.append("不打财神")
    reasons.append(f"打出后向听 {recommended.shanten_after}，有效进张 {recommended.ukeire_count} 张")
    return "；".join(reasons)


def _data_confidence(snapshot: dict[str, Any], hand: list[str], effective_count: int) -> list[str]:
    parts: list[str] = []
    parts.append("完整手牌：已拿到" if snapshot.get("hand_trusted") and hand else "完整手牌：不足")
    parts.append("财神：已解析" if snapshot.get("baida_tile") and snapshot.get("baida_trusted") else "财神：未解析")
    parts.append("当前事件：可信" if snapshot.get("turn_trusted") else "当前事件：等待可信事件")
    if snapshot.get("unknowns"):
        parts.append(f"未知牌值：{len(snapshot.get('unknowns') or [])} 个")
    if effective_count not in (13, 14):
        parts.append(f"有效张数：{effective_count}")
    return parts


def _opponent_predictions(
    *,
    enemy_discards: list[str],
    enemy_meld_tiles: list[str],
    enemy_meld_count: int,
    enemy_hand_count: int,
    remaining_tiles: int,
    current_turn: str,
    visible: dict[str, int],
) -> tuple[str, str]:
    discard_suits = _suit_counts(enemy_discards)
    meld_suits = _suit_counts(enemy_meld_tiles)
    focus_suits = _opponent_focus_suits(discard_suits, meld_suits, enemy_discards, enemy_meld_tiles)
    visible_pressure = _visible_pressure(focus_suits, visible)

    if not enemy_discards and not enemy_meld_tiles:
        hand_prediction = "估计：对方可见信息不足，暂不判断隐藏手牌；先关注后续弃牌和副露。"
    else:
        focus_text = "、".join(focus_suits) if focus_suits else "未形成明显花色"
        meld_text = f"副露 {enemy_meld_count} 组" if enemy_meld_count else "暂无副露"
        hand_prediction = (
            f"估计：对方可能围绕 {focus_text} 保留搭子；{meld_text}，"
            f"需关注 {visible_pressure}。"
        )

    discard_count = len(enemy_discards)
    if enemy_meld_count >= 3 or (enemy_meld_count >= 2 and discard_count <= 6):
        progress_level = "高"
        progress_note = "可能已接近听牌或进入强进攻阶段"
    elif enemy_meld_count >= 2 or remaining_tiles <= 35:
        progress_level = "中高"
        progress_note = "可能在一向听到听牌附近"
    elif enemy_meld_count == 1 or discard_count >= 8:
        progress_level = "中"
        progress_note = "可能仍在整理牌型，但已有明确方向"
    else:
        progress_level = "中低"
        progress_note = "早中期概率较高，继续观察弃牌节奏"

    turn_note = "当前轮到对方，风险需上调关注。" if current_turn == "enemy" else "当前未轮到对方，按可见牌保守估计。"
    progress_prediction = (
        f"估计进度：{progress_level}；{progress_note}；"
        f"对方已弃 {discard_count} 张、{enemy_meld_count} 组副露、手牌计数 {enemy_hand_count}。{turn_note}"
    )
    return hand_prediction, progress_prediction


def _suit_counts(tiles: list[str]) -> dict[str, int]:
    counts = {"万": 0, "条": 0, "筒": 0, "字牌": 0}
    for tile in tiles:
        if tile.endswith("m"):
            counts["万"] += 1
        elif tile.endswith("s"):
            counts["条"] += 1
        elif tile.endswith("p"):
            counts["筒"] += 1
        elif tile.endswith("z"):
            counts["字牌"] += 1
    return counts


def _opponent_focus_suits(
    discard_suits: dict[str, int],
    meld_suits: dict[str, int],
    enemy_discards: list[str],
    enemy_meld_tiles: list[str],
) -> list[str]:
    suit_names = ["万", "条", "筒", "字牌"]
    scored: list[tuple[int, str]] = []
    has_visible = bool(enemy_discards or enemy_meld_tiles)
    for suit in suit_names:
        score = int(meld_suits.get(suit, 0)) * 2 - int(discard_suits.get(suit, 0))
        if has_visible and int(discard_suits.get(suit, 0)) == 0:
            score += 1
        scored.append((score, suit))
    best = max((score for score, _ in scored), default=0)
    if best <= 0:
        return []
    return [suit for score, suit in sorted(scored, key=lambda item: (-item[0], item[1])) if score == best][:2]


def _visible_pressure(focus_suits: list[str], visible: dict[str, int]) -> str:
    if not focus_suits:
        return "中张和未现字牌"
    suit_to_suffix = {"万": "m", "条": "s", "筒": "p", "字牌": "z"}
    pressure: list[str] = []
    for suit in focus_suits:
        suffix = suit_to_suffix.get(suit)
        if not suffix:
            continue
        unseen = [
            tile_display_name(tile)
            for tile in ALL_TILES
            if tile.endswith(suffix) and int(visible.get(tile, 0)) <= 1
        ][:4]
        if unseen:
            pressure.append(f"{suit}侧未充分出现的 {'/'.join(unseen)}")
    return "；".join(pressure) if pressure else "未充分出现的同花色牌"


def _can_recommend(
    snapshot: dict[str, Any],
    hand: list[str],
    baida_trusted: bool,
    effective_count: int,
) -> bool:
    return (
        bool(snapshot.get("hand_trusted"))
        and baida_trusted
        and bool(snapshot.get("turn_trusted"))
        and str(snapshot.get("current_turn") or "") == "self"
        and effective_count == 14
        and not snapshot.get("optional_actions")
        and not snapshot.get("unknowns")
        and bool(hand)
    )


def _blocked_reason(snapshot: dict[str, Any], effective_count: int) -> str:
    explicit = str(snapshot.get("analysis_blocked_reason") or "").strip()
    if explicit:
        return explicit
    if not snapshot.get("hand_trusted"):
        return "等待可信手牌"
    if not snapshot.get("baida_tile") or not snapshot.get("baida_trusted"):
        return "等待抓包解析财神"
    if snapshot.get("unknowns"):
        return "等待补全未知牌值映射"
    if not snapshot.get("turn_trusted"):
        return "等待可信回合事件"
    if str(snapshot.get("current_turn") or "") != "self":
        return "等待我方出牌回合"
    if snapshot.get("optional_actions"):
        return "等待处理可选动作"
    if effective_count != 14:
        return f"有效手牌数为 {effective_count}，需要 14"
    return "等待完整数据"


def _valid_tiles(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if str(v) in ALL_TILES]


def _meld_tiles(melds: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(melds, list):
        return result
    for meld in melds:
        if isinstance(meld, dict):
            result.extend(_valid_tiles(meld.get("tiles", [])))
    return result
