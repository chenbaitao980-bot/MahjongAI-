from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from game.state import MeldGroup, TileMatch


def tile_from_id(tile_id: str, confidence: float = 1.0) -> TileMatch:
    return TileMatch(tile_id=tile_id, confidence=confidence)


def meld_from_ids(meld_type: str, tile_ids: list[str]) -> MeldGroup:
    return MeldGroup(
        meld_type=meld_type,
        tiles=[tile_from_id(tile_id) for tile_id in tile_ids],
    )


def tiles_to_ids(tiles: list[TileMatch]) -> list[str]:
    return [tile.tile_id for tile in tiles if tile.tile_id]


def melds_to_payload(melds: list[MeldGroup]) -> list[dict]:
    payload: list[dict] = []
    for meld in melds:
        payload.append(
            {
                "type": meld.meld_type,
                "tiles": tiles_to_ids(meld.tiles),
            }
        )
    return payload


@dataclass
class BattleAdvice:
    recommended_discard: str = ""
    strategy_type: str = ""
    reasoning_summary: str = ""
    risk_notes: str = ""
    forbidden_discards: list[str] = field(default_factory=list)
    candidate_actions: list[str] = field(default_factory=list)
    raw_response: str = ""


@dataclass
class BattleState:
    ai_recognition_enabled: bool = True
    deepseek_enabled: bool = True
    vision_provider: str = "auto"
    baida_tile: str = ""
    remaining_tiles: int = 108
    dealer_seat: str = "self"   # 当前庄家座位：self / right / across / left
    self_wind: str = "1z"       # 自家门风：1z=东 2z=南 3z=西 4z=北
    self_hand: list[TileMatch] = field(default_factory=list)
    self_discards: list[TileMatch] = field(default_factory=list)
    self_melds: list[MeldGroup] = field(default_factory=list)
    self_melds_locked: bool = False   # True when user manually set/corrected melds
    enemy_discards: list[TileMatch] = field(default_factory=list)
    enemy_melds: list[MeldGroup] = field(default_factory=list)
    kan_closed_count: int = 0   # 暗杠次数（影响基础牌点计算）
    last_trigger_reason: str = ""
    last_analysis_at: str = ""
    last_analysis_duration_ms: int = 0
    last_recognition_duration_ms: int = 0
    last_advice_duration_ms: int = 0
    recognition_source: str = "manual"
    operation_logs: list[dict] = field(default_factory=list)

    def mark_analysis(self, trigger_reason: str) -> None:
        self.last_trigger_reason = trigger_reason
        self.last_analysis_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_analysis_duration_ms = 0
        self.last_recognition_duration_ms = 0
        self.last_advice_duration_ms = 0

    def append_operation(self, action: str, detail: dict | None = None) -> None:
        self.operation_logs.append(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": action,
                "detail": detail or {},
                "snapshot": {
                    "baida_tile": self.baida_tile,
                    "remaining_tiles": self.remaining_tiles,
                    "self_hand": tiles_to_ids(self.self_hand),
                    "self_discards": tiles_to_ids(self.self_discards),
                    "self_melds": melds_to_payload(self.self_melds),
                    "enemy_discards": tiles_to_ids(self.enemy_discards),
                    "enemy_melds": melds_to_payload(self.enemy_melds),
                    "recognition_source": self.recognition_source,
                },
            }
        )
        if len(self.operation_logs) > 300:
            self.operation_logs = self.operation_logs[-300:]

    def _compute_analysis(self) -> dict:
        """
        本地分析计算。任何异常都安静返回 {}，不阻断主流程。
        手牌张数：
          - 13张：只算当前向听数，不算 candidates
          - 14张：调用 analyze_discard_candidates，得到完整候选列表
          - 其他：返回 {}
        """
        try:
            from game.tiles import build_visible_tiles, hand_to_counts, tiles_to_ids
            from game.shanten import calc_shanten
            from game.evaluator import analyze_discard_candidates

            hand = tiles_to_ids(self.self_hand)
            baida = self.baida_tile or None

            meld_count = len(self.self_melds)

            self_meld_tiles = []
            for m in self.self_melds:
                self_meld_tiles.extend(tiles_to_ids(m.tiles))

            enemy_meld_tiles = []
            for m in self.enemy_melds:
                enemy_meld_tiles.extend(tiles_to_ids(m.tiles))

            visible = build_visible_tiles(
                hand,
                tiles_to_ids(self.self_discards),
                self_meld_tiles,
                tiles_to_ids(self.enemy_discards),
                enemy_meld_tiles,
            )

            counts, baida_count = hand_to_counts(hand, baida)

            # 统计暗杠数
            kan_closed_count = sum(
                1 for m in self.self_melds if m.meld_type == "kan_closed"
            )

            if len(hand) == 13:
                shanten = calc_shanten(counts, meld_count, baida_count)
                return {
                    "shanten": shanten,
                    "kan_closed_count": kan_closed_count,
                    "candidates": [],
                    "top_recommendation": None,
                }

            elif len(hand) == 14:
                eval_result = analyze_discard_candidates(
                    hand,
                    self.self_melds,
                    baida,
                    visible,
                    tiles_to_ids(self.enemy_discards),
                    self.enemy_melds,
                    tiles_to_ids(self.self_discards),
                    self.remaining_tiles,
                )
                candidates = eval_result.get("candidates", [])
                mode = eval_result.get("strategy_mode", "balance")
                top = candidates[0]["discard"] if candidates else None
                top_score = candidates[0].get("score") if candidates else None
                shanten = calc_shanten(counts, meld_count, baida_count)
                return {
                    "shanten": shanten,
                    "kan_closed_count": kan_closed_count,
                    "strategy_mode": mode,
                    "candidates": candidates[:5],
                    "top_recommendation": top,
                    "top_score": top_score,
                }

            return {}
        except Exception:
            return {}

    def reset_round(self) -> None:
        self.baida_tile = ""
        self.remaining_tiles = 108
        self.dealer_seat = "self"
        self.self_wind = "1z"
        self.self_hand.clear()
        self.self_discards.clear()
        self.self_melds.clear()
        self.self_melds_locked = False
        self.enemy_discards.clear()
        self.enemy_melds.clear()
        self.kan_closed_count = 0
        self.last_trigger_reason = ""
        self.last_analysis_at = ""
        self.last_analysis_duration_ms = 0
        self.last_recognition_duration_ms = 0
        self.last_advice_duration_ms = 0
        self.recognition_source = "manual"
        self.operation_logs.clear()
        self.deepseek_enabled = True

    def to_payload(self) -> dict:
        remaining = self.remaining_tiles
        if remaining <= 16:
            phase = "huangpai"
        elif remaining <= 30:
            phase = "shengjia"
        else:
            phase = "playing"
        return {
            "rules": {
                "variant": "taizhou_mahjong",
                "num_players": 2,
                "tile_count": 136,
                "win_shape": "1 pair + 4 groups",
                "shengjia_threshold": 30,
                "huangpai_threshold": 16,
                "one_shot_multi_win_priority": "lower_seat_first",
                "baida_tile": self.baida_tile or None,
                "dealer_seat": self.dealer_seat,
                "self_wind": self.self_wind,
            },
            "phase": phase,
            "remaining_tiles": remaining,
            "recognition_source": self.recognition_source,
            "self": {
                "hand": tiles_to_ids(self.self_hand),
                "discards": tiles_to_ids(self.self_discards),
                "melds": melds_to_payload(self.self_melds),
                "analysis": self._compute_analysis(),
            },
            "enemy": {
                "discards": tiles_to_ids(self.enemy_discards),
                "melds": melds_to_payload(self.enemy_melds),
            },
            "trigger_reason": self.last_trigger_reason,
            "logs": self.operation_logs[-300:],
        }
