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
    self_hand: list[TileMatch] = field(default_factory=list)
    self_discards: list[TileMatch] = field(default_factory=list)
    self_melds: list[MeldGroup] = field(default_factory=list)
    enemy_discards: list[TileMatch] = field(default_factory=list)
    enemy_melds: list[MeldGroup] = field(default_factory=list)
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

    def reset_round(self) -> None:
        self.baida_tile = ""
        self.remaining_tiles = 108
        self.self_hand.clear()
        self.self_discards.clear()
        self.self_melds.clear()
        self.enemy_discards.clear()
        self.enemy_melds.clear()
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
        phase = "shengjia" if remaining <= 15 else "playing"
        return {
            "rules": {
                "variant": "taizhou_mahjong",
                "tile_count": 136,
                "win_shape": "1 pair + 4 groups",
                "shengjia_threshold": 15,
                "one_shot_multi_win_priority": "lower_seat_first",
                "baida_tile": self.baida_tile or None,
            },
            "phase": phase,
            "remaining_tiles": remaining,
            "recognition_source": self.recognition_source,
            "self": {
                "hand": tiles_to_ids(self.self_hand),
                "discards": tiles_to_ids(self.self_discards),
                "melds": melds_to_payload(self.self_melds),
            },
            "enemy": {
                "discards": tiles_to_ids(self.enemy_discards),
                "melds": melds_to_payload(self.enemy_melds),
            },
            "trigger_reason": self.last_trigger_reason,
            "logs": self.operation_logs[-300:],
        }
