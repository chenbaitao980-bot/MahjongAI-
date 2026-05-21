from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from battle.state import BattleState, meld_from_ids, tile_from_id
from game.stable_hard_analysis import analyze_snapshot
from game.tiles import ALL_TILES, tile_display_name, tile_sort_key


def _now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


@dataclass
class SimPlayer:
    hand: list[str] = field(default_factory=list)
    discards: list[str] = field(default_factory=list)
    melds: list[dict[str, Any]] = field(default_factory=list)


class StableSimulationGame:
    """Small 2-player simulation that emits stable-reader shaped snapshots."""

    def __init__(self, seed: int | None = None):
        self.local_player = 0
        self.opponent_player = 1
        self.phase = "playing"
        self.current_turn = "self"
        self.baida_tile = ""
        self.wall: list[str] = []
        self.players = {
            self.local_player: SimPlayer(),
            self.opponent_player: SimPlayer(),
        }
        self.event_log: list[str] = []
        self.last_error = ""
        self._rng = random.Random(seed)
        self._last_analyzed_signature: tuple | None = None
        self._start_round()

    def _start_round(self) -> None:
        self.wall = [tile for tile in ALL_TILES for _ in range(4)]
        self._rng.shuffle(self.wall)
        self.baida_tile = self._draw_raw() or "7z"
        for _ in range(13):
            self.players[self.local_player].hand.append(self._draw_raw())
            self.players[self.opponent_player].hand.append(self._draw_raw())
        self._draw_for(self.local_player)
        self.current_turn = "self"
        self.event_log.append(f"{_now_text()} 模拟开局：财神{tile_display_name(self.baida_tile)}，我方先出牌")

    @property
    def remaining_tiles(self) -> int:
        return len(self.wall)

    def _draw_raw(self) -> str:
        if not self.wall:
            self.phase = "finished"
            return ""
        return self.wall.pop()

    def _draw_for(self, player_id: int) -> str:
        tile = self._draw_raw()
        if tile:
            self.players[player_id].hand.append(tile)
            actor = "我方" if player_id == self.local_player else "对面"
            self.event_log.append(f"{_now_text()} {actor}摸牌")
        return tile

    def discard_self(self, tile_id: str) -> None:
        if self.current_turn != "self":
            raise ValueError("当前不是我方回合")
        self._discard(self.local_player, tile_id)
        self.current_turn = "enemy"

    def advance_opponent(self) -> None:
        if self.phase != "playing" or self.current_turn != "enemy":
            return
        self._draw_for(self.opponent_player)
        discard = self._choose_opponent_discard()
        if discard:
            self._discard(self.opponent_player, discard)
        self._draw_for(self.local_player)
        self.current_turn = "self" if self.phase == "playing" else "none"

    def _discard(self, player_id: int, tile_id: str) -> None:
        player = self.players[player_id]
        if tile_id not in player.hand:
            raise ValueError(f"手牌中没有 {tile_id}")
        player.hand.remove(tile_id)
        player.discards.append(tile_id)
        actor = "我方" if player_id == self.local_player else "对面"
        self.event_log.append(f"{_now_text()} {actor}打出{tile_display_name(tile_id)}")

    def _choose_opponent_discard(self) -> str:
        opponent = self.players[self.opponent_player]
        if not opponent.hand:
            return ""
        return sorted(opponent.hand, key=tile_sort_key)[-1]

    def recommended_discard(self) -> str:
        analysis = analyze_snapshot(self.snapshot())
        return analysis.recommended_discard

    def analysis_signature(self) -> tuple:
        self_player = self.players[self.local_player]
        opponent = self.players[self.opponent_player]
        return (
            tuple(self_player.hand),
            tuple(self_player.discards),
            tuple(opponent.discards),
            self.current_turn,
            self.remaining_tiles,
        )

    def should_analyze(self) -> bool:
        return self.current_turn == "self" and self.analysis_signature() != self._last_analyzed_signature

    def mark_analyzed(self) -> None:
        self._last_analyzed_signature = self.analysis_signature()

    def snapshot(self) -> dict[str, Any]:
        self_player = self.players[self.local_player]
        opponent = self.players[self.opponent_player]
        hand_count = len(self_player.hand)
        blocked = ""
        if self.current_turn != "self":
            blocked = "等待我方出牌回合"
        elif hand_count != 14:
            blocked = f"有效手牌数为 {hand_count}，需要 14"
        return {
            "phase": self.phase,
            "local_player": self.local_player,
            "opponent_player": self.opponent_player,
            "current_turn": self.current_turn,
            "remaining_tiles": self.remaining_tiles,
            "baida_tile": self.baida_tile,
            "hand_trusted": True,
            "baida_trusted": bool(self.baida_tile),
            "turn_trusted": True,
            "optional_actions": [],
            "action_note": "模拟对战中" if self.phase == "playing" else "模拟局已结束",
            "hand_incomplete_reason": "",
            "marked_tiles": [],
            "players": {
                self.local_player: {
                    "hand": sorted(self_player.hand, key=tile_sort_key),
                    "hand_count": len(self_player.hand),
                    "discards": list(self_player.discards),
                    "melds": list(self_player.melds),
                },
                self.opponent_player: {
                    "hand": [],
                    "hand_count": len(opponent.hand),
                    "discards": list(opponent.discards),
                    "melds": list(opponent.melds),
                },
            },
            "events": list(self.event_log[-120:]),
            "unknowns": [],
            "analysis_ready": self.current_turn == "self" and hand_count == 14 and self.phase == "playing",
            "analysis_blocked_reason": blocked,
            "analysis_mode": "full" if not blocked and self.phase == "playing" else "blocked",
            "last_error": self.last_error,
        }

    def to_battle_state(self) -> BattleState:
        state = BattleState(ai_recognition_enabled=False)
        self_player = self.players[self.local_player]
        opponent = self.players[self.opponent_player]
        state.baida_tile = self.baida_tile
        state.remaining_tiles = self.remaining_tiles
        state.current_turn = self.current_turn
        state.recognition_source = "simulation"
        state.self_hand = [tile_from_id(t) for t in self_player.hand]
        state.self_discards = [tile_from_id(t) for t in self_player.discards]
        state.self_melds = [meld_from_ids(m["type"], list(m["tiles"])) for m in self_player.melds]
        state.enemy_discards = [tile_from_id(t) for t in opponent.discards]
        state.enemy_melds = [meld_from_ids(m["type"], list(m["tiles"])) for m in opponent.melds]
        state.append_operation(
            "simulation_snapshot",
            {
                "phase": self.phase,
                "events": self.event_log[-20:],
            },
        )
        return state
