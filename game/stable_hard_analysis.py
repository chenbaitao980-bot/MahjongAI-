from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from game.opponent_inference import OpponentPrediction, infer_opponent_hand
from game.shanten import calc_shanten
from game.stable_strategy_model import StrategyModelContext, rank_discard_candidates
from game.tiles import ALL_TILES, build_visible_tiles, hand_to_counts, tile_display_name
from game.ukeire import calc_ukeire
from game.win import is_win


@dataclass
class HardDiscardCandidate:
    discard: str
    shanten_after: int
    ting_tiles: list[dict[str, Any]] = field(default_factory=list)
    ukeire_tiles: list[str] = field(default_factory=list)
    ukeire_count: int = 0
    is_caishen: bool = False
    shanten_delta: int = 0
    shape_value: int = 0
    remaining_hand: list[str] = field(default_factory=list)
    model_score: float = 0.0
    model_source: str = ""
    model_reasons: list[str] = field(default_factory=list)
    model_features: dict[str, float] = field(default_factory=dict)
    opponent_penalty: float = 0.0


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
    opponent_prediction: OpponentPrediction | None = None


def analyze_snapshot(snapshot: dict[str, Any], analysis_config: dict[str, Any] | None = None) -> StableHardAnalysis:
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
    phase = str(snapshot.get("phase") or "")

    current_status = infer_current_status(snapshot, effective_count)
    caishen_text = tile_display_name(baida) if baida and baida_trusted else "等待财神"
    visible = build_visible_tiles(hand, self_discards, self_meld_tiles, enemy_discards, enemy_meld_tiles)

    confidence_parts = _data_confidence(snapshot, hand, effective_count)
    response_actions = _response_actions(snapshot, hand, enemy_discards, baida if baida_trusted else None, meld_count)
    is_finished = phase == "hupai" or bool(snapshot.get("last_event") == "win")
    can_recommend = (
        _can_recommend(snapshot, hand, baida_trusted, effective_count)
        and not response_actions
        and not is_finished
    )

    current_shanten: int | None = None
    if hand and baida and baida_trusted:
        counts, baida_count = hand_to_counts(hand, baida)
        current_shanten = calc_shanten(counts, meld_count, baida_count)

    opponent_config = {}
    if isinstance(analysis_config, dict):
        raw_opponent_config = analysis_config.get("opponent_prediction", {})
        if isinstance(raw_opponent_config, dict):
            opponent_config = raw_opponent_config
    opponent_prediction = infer_opponent_hand(snapshot, opponent_config)

    candidates: list[HardDiscardCandidate] = []
    if can_recommend and baida:
        legal_discards = _legal_discards(snapshot, hand, current_shanten)
        candidates = _discard_candidates(
            hand,
            meld_count,
            baida,
            visible,
            current_shanten,
            effective_count,
            legal_discards=legal_discards,
        )
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
                opponent_prediction=opponent_prediction,
            ),
        )

    ting_tiles = _current_ting_tiles(hand, meld_count, baida, visible, effective_count, candidates)
    is_ting = bool(ting_tiles)
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
    if opponent_prediction.enabled:
        opponent_hand_prediction = opponent_prediction.summary
        opponent_progress_prediction = opponent_prediction.progress_summary
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
    response_advice, response_reason = _response_advice(
        response_actions,
        snapshot=snapshot,
        hand=hand,
        enemy_discards=enemy_discards,
        baida=baida if baida_trusted else None,
        meld_count=meld_count,
        visible=visible,
    )
    if is_finished:
        current_advice = "胡牌结算"
        advice_reason = "当前牌局已进入胡牌/结算状态，不再给出牌建议"
        recommended_discard = ""
        effective_tiles = []
        effective_count_after = 0
        candidates = []
        model_status = "finished"
    elif response_advice:
        current_advice = response_advice
        advice_reason = response_reason
        recommended_discard = ""
        effective_tiles = []
        effective_count_after = 0
        candidates = []
        model_status = "response_action"

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
        opponent_prediction=opponent_prediction,
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
    effective_count: int,
    legal_discards: list[str] | None = None,
) -> list[HardDiscardCandidate]:
    result: list[HardDiscardCandidate] = []
    discard_pool = sorted(set(hand))
    if legal_discards is not None:
        legal_set = {tile for tile in legal_discards if tile in hand}
        discard_pool = [tile for tile in discard_pool if tile in legal_set]
    for discard in discard_pool:
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
                shanten_delta=0,
                shape_value=_discard_shape_value(hand, discard),
                remaining_hand=after,
            )
        )
    if result:
        if effective_count % 3 == 2:
            baseline = min(c.shanten_after for c in result)
        else:
            baseline = current_shanten if current_shanten is not None else min(c.shanten_after for c in result)
        for candidate in result:
            candidate.shanten_delta = candidate.shanten_after - baseline
    result.sort(key=lambda c: (c.is_caishen, c.shanten_after, -c.ukeire_count, c.discard))
    return result


def _legal_discards(snapshot: dict[str, Any], hand: list[str], current_shanten: int | None) -> list[str] | None:
    explicit = _valid_tiles(snapshot.get("legal_discards", []))
    if explicit:
        return explicit
    drawn_tile = str(snapshot.get("drawn_tile") or "")
    if current_shanten == 0 and drawn_tile in hand:
        return [drawn_tile]
    return None


def _discard_shape_value(hand: list[str], discard: str) -> int:
    if not discard:
        return 0
    same_count = hand.count(discard)
    if same_count >= 3:
        return -30
    if same_count == 2:
        return -20
    if discard.endswith("z"):
        return 45

    rank = int(discard[:-1])
    suit = discard[-1]
    ranks = [int(tile[:-1]) for tile in hand if tile.endswith(suit) and tile != discard]
    rank_set = set(ranks)
    in_sequence = any(
        all(1 <= value <= 9 and (value == rank or value in rank_set) for value in (start, start + 1, start + 2))
        for start in (rank - 2, rank - 1, rank)
        if start <= rank <= start + 2
    )
    if in_sequence:
        return -10

    left = rank - 1 in rank_set
    right = rank + 1 in rank_set
    gap_left = rank - 2 in rank_set
    gap_right = rank + 2 in rank_set
    if not (left or right or gap_left or gap_right):
        return 55
    if (rank == 1 and right) or (rank == 9 and left):
        return 50
    if gap_left or gap_right:
        return 34
    if left and right:
        return 8
    return 16


def _choose_recommendation(candidates: list[HardDiscardCandidate]) -> HardDiscardCandidate | None:
    if not candidates:
        return None
    return candidates[0]


def _normalize_actions(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    aliases = {
        "吃": "chi",
        "碰": "pon",
        "杠": "kong",
        "明杠": "kong",
        "暗杠": "kong",
        "补杠": "kong",
        "胡": "hu",
        "胡牌": "hu",
        "过": "pass",
        "chi": "chi",
        "pon": "pon",
        "peng": "pon",
        "kong": "kong",
        "gang": "kong",
        "hu": "hu",
        "pass": "pass",
    }
    result: list[str] = []
    for value in values:
        action = aliases.get(str(value).strip())
        if action and action not in result:
            result.append(action)
    return result


def _last_opponent_discard(snapshot: dict[str, Any], enemy_discards: list[str]) -> str:
    action_tile = str(snapshot.get("action_tile") or "")
    if action_tile in ALL_TILES:
        return action_tile
    return enemy_discards[-1] if enemy_discards else ""


def _response_actions(
    snapshot: dict[str, Any],
    hand: list[str],
    enemy_discards: list[str],
    baida: str | None,
    meld_count: int,
) -> list[str]:
    explicit = _normalize_actions(snapshot.get("optional_actions"))
    if explicit:
        return explicit
    if not hand or len(hand) % 3 != 1:
        return []
    if str(snapshot.get("current_turn") or "") not in ("none", "response"):
        return []
    tile = _last_opponent_discard(snapshot, enemy_discards)
    if tile not in ALL_TILES:
        return []
    actions: list[str] = []
    if baida:
        counts, baida_count = hand_to_counts(hand + [tile], baida)
        if is_win(counts, meld_count, baida_count):
            actions.append("hu")
    same_count = sum(1 for t in hand if t == tile)
    if same_count >= 3:
        actions.append("kong")
    if same_count >= 2:
        actions.append("pon")
    if _can_chi(hand, tile):
        actions.append("chi")
    if actions:
        actions.append("pass")
    return actions


def _can_chi(hand: list[str], tile: str) -> bool:
    if tile not in ALL_TILES or tile.endswith("z"):
        return False
    suit = tile[-1]
    rank = int(tile[:-1])
    ranks = {int(t[:-1]) for t in hand if t.endswith(suit) and not t.endswith("z")}
    for a, b in ((rank - 2, rank - 1), (rank - 1, rank + 1), (rank + 1, rank + 2)):
        if 1 <= a <= 9 and 1 <= b <= 9 and a in ranks and b in ranks:
            return True
    return False


def _find_chi_tiles(hand: list[str], tile: str) -> list[str]:
    if tile not in ALL_TILES or tile.endswith("z"):
        return []
    suit = tile[-1]
    rank = int(tile[:-1])
    available = set(hand)
    for a, b in ((rank - 1, rank + 1), (rank - 2, rank - 1), (rank + 1, rank + 2)):
        ta = f"{a}{suit}"
        tb = f"{b}{suit}"
        if 1 <= a <= 9 and 1 <= b <= 9 and ta in available and tb in available:
            return [ta, tb]
    return []


def _simulate_response_shanten(
    hand: list[str],
    action: str,
    tile: str,
    baida: str | None,
    meld_count: int,
    visible: dict[str, int],
    action_tiles: list[str] | None = None,
) -> tuple[int | None, int]:
    if not baida or tile not in ALL_TILES:
        return None, 0
    simulated = list(hand)
    next_meld_count = meld_count
    if action == "pon":
        remove_count = 2
    elif action == "kong":
        remove_count = 3
    elif action == "chi":
        tiles = [t for t in (action_tiles or []) if t in ALL_TILES]
        if tiles and tile in tiles:
            meld = list(tiles)
            remove_tiles = list(tiles)
            remove_tiles.remove(tile)
        else:
            meld = _find_chi_tiles(simulated, tile)
            remove_tiles = list(meld)
        if not remove_tiles:
            return None, 0
        for value in remove_tiles:
            if value not in simulated:
                return None, 0
            simulated.remove(value)
        next_meld_count += 1
        counts, baida_count = hand_to_counts(simulated, baida)
        ukeire = calc_ukeire(simulated, next_meld_count, baida, visible)
        return calc_shanten(counts, next_meld_count, baida_count), int(ukeire.get("count", 0))
    else:
        return None, 0
    removed = 0
    kept: list[str] = []
    for value in simulated:
        if value == tile and removed < remove_count:
            removed += 1
        else:
            kept.append(value)
    if removed < remove_count:
        return None, 0
    next_meld_count += 1
    counts, baida_count = hand_to_counts(kept, baida)
    ukeire = calc_ukeire(kept, next_meld_count, baida, visible)
    return calc_shanten(counts, next_meld_count, baida_count), int(ukeire.get("count", 0))


def _response_action_options(snapshot: dict[str, Any], actions: list[str], tile: str) -> list[dict[str, Any]]:
    details = snapshot.get("optional_action_details")
    options: list[dict[str, Any]] = []
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            action = _normalize_actions([item.get("type")])
            if not action:
                continue
            action_type = action[0]
            if action_type not in actions:
                continue
            tiles = [str(t) for t in item.get("tiles", []) if str(t) in ALL_TILES]
            options.append(
                {
                    "type": action_type,
                    "tile": str(item.get("tile") or tile),
                    "tiles": tiles,
                    "label": str(item.get("label") or ""),
                }
            )
    if options:
        return options
    return [{"type": action, "tile": tile, "tiles": [], "label": ""} for action in actions]


def _response_option_label(option: dict[str, Any], fallback: dict[str, str]) -> str:
    label = str(option.get("label") or "").strip()
    if label:
        return label
    action = str(option.get("type") or "")
    tiles = [str(t) for t in option.get("tiles", []) if str(t) in ALL_TILES]
    if action == "chi" and tiles:
        return "吃 " + " ".join(tile_display_name(t) for t in tiles)
    tile = str(option.get("tile") or "")
    if tile in ALL_TILES and action in fallback:
        return f"{fallback[action]} {tile_display_name(tile)}"
    return fallback.get(action, action)


def _response_advice(
    actions: list[str],
    *,
    snapshot: dict[str, Any],
    hand: list[str],
    enemy_discards: list[str],
    baida: str | None,
    meld_count: int,
    visible: dict[str, int],
) -> tuple[str, str]:
    if not actions:
        return "", ""
    tile = _last_opponent_discard(snapshot, enemy_discards)
    tile_text = tile_display_name(tile) if tile else "当前牌"
    if "hu" in actions:
        return "建议胡", f"当前可胡 {tile_text}，胡牌优先级高于杠、碰、吃和过"
    scored: list[tuple[int, int, int, str, str, str]] = []
    priority = {"kong": 0, "pon": 1, "chi": 2}
    label = {"kong": "杠", "pon": "碰", "chi": "吃"}
    for option in _response_action_options(snapshot, actions, tile):
        action = str(option.get("type") or "")
        if action not in ("kong", "pon", "chi"):
            continue
        option_label = _response_option_label(option, label)
        action_tile = str(option.get("tile") or tile)
        action_tiles = [str(t) for t in option.get("tiles", []) if str(t) in ALL_TILES]
        shanten_after, ukeire_count = _simulate_response_shanten(
            hand,
            action,
            action_tile,
            baida,
            meld_count,
            visible,
            action_tiles,
        )
        if shanten_after is None:
            scored.append((99, 0, priority.get(action, 9), action, option_label, "数据不足，无法可靠评估响应后牌型"))
        else:
            scored.append(
                (
                    shanten_after,
                    -ukeire_count,
                    priority.get(action, 9),
                    action,
                    option_label,
                    f"{option_label}后向听 {shanten_after}，有效进张 {ukeire_count} 张",
                )
            )
    if not scored:
        return "建议过", "当前只有过或缺少可验证响应动作，保守过"
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    best_shanten, _neg_ukeire, _priority, best_action, best_label, reason = scored[0]
    if best_shanten > 1:
        return "建议过", f"{reason}，收益不明确，保守过"
    return f"建议{best_label}", reason + "；过为备选"


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
    if recommended and recommended.shanten_delta > 0:
        reminders.append("当前推荐会导致向听变差")
    if is_ting:
        retreating = [c for c in candidates if c.shanten_delta > 0]
        if retreating:
            reminders.append("已听牌，避免选择退听打法")
    if recommended and recommended.shanten_delta > 0:
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
