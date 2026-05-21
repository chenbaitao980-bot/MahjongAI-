from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from battle.state import BattleState, meld_from_ids, tile_from_id
from game.shanten import calc_shanten
from game.stable_hard_analysis import analyze_snapshot
from game.tiles import ALL_TILES, hand_to_counts, rank_of, suit_of, tile_display_name, tile_sort_key


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
        self.pending_response: dict[str, Any] | None = None
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
        self.pending_response = {
            "responder": self.opponent_player,
            "discarder": self.local_player,
            "tile": tile_id,
            "actions": self.available_response_actions(self.opponent_player, self.local_player, tile_id),
        }

    def advance_opponent(self) -> None:
        if self.phase != "playing" or self.current_turn != "enemy":
            return
        if self.pending_response and self.pending_response.get("responder") == self.opponent_player:
            action = self._choose_computer_response(self.pending_response.get("actions", []))
            self.apply_response_action(action)
            if self.phase != "playing":
                return
            if action.get("type") != "pass":
                discard = self._choose_opponent_discard()
                if discard:
                    self._discard(self.opponent_player, discard)
                    self._set_local_pending_response(discard)
                return

        self._draw_for(self.opponent_player)
        if self._is_win(self.opponent_player):
            self._win(self.opponent_player, "自摸")
            return
        self._apply_best_closed_kong(self.opponent_player)
        discard = self._choose_opponent_discard()
        if discard:
            self._discard(self.opponent_player, discard)
            self._set_local_pending_response(discard)

    def _discard(self, player_id: int, tile_id: str) -> None:
        player = self.players[player_id]
        if tile_id not in player.hand:
            raise ValueError(f"手牌中没有 {tile_id}")
        player.hand.remove(tile_id)
        player.discards.append(tile_id)
        actor = "我方" if player_id == self.local_player else "对面"
        self.event_log.append(f"{_now_text()} {actor}打出{tile_display_name(tile_id)}")

    def _set_local_pending_response(self, discarded_tile: str) -> None:
        actions = self.available_response_actions(self.local_player, self.opponent_player, discarded_tile)
        self.pending_response = {
            "responder": self.local_player,
            "discarder": self.opponent_player,
            "tile": discarded_tile,
            "actions": actions,
        }
        self.current_turn = "self"

    def available_self_actions(self) -> list[dict[str, Any]]:
        if self.phase != "playing" or self.current_turn != "self":
            return []
        actions: list[dict[str, Any]] = []
        if self._is_win(self.local_player):
            actions.append({"type": "hu", "label": "胡"})
        for tile in sorted(set(self.players[self.local_player].hand), key=tile_sort_key):
            if self.players[self.local_player].hand.count(tile) >= 4:
                actions.append({"type": "kan_closed", "tile": tile, "label": f"暗杠 {tile_display_name(tile)}"})
        return actions

    def available_response_actions(self, responder: int, discarder: int, tile: str) -> list[dict[str, Any]]:
        hand = self.players[responder].hand
        actions: list[dict[str, Any]] = []
        if self._is_win(responder, extra_tile=tile):
            actions.append({"type": "hu", "tile": tile, "label": f"胡 {tile_display_name(tile)}"})
        same_count = hand.count(tile)
        if same_count >= 3:
            actions.append({"type": "kan_open", "tile": tile, "label": f"明杠 {tile_display_name(tile)}"})
        if same_count >= 2:
            actions.append({"type": "pon", "tile": tile, "label": f"碰 {tile_display_name(tile)}"})
        if responder == self.local_player:
            for seq in self._chi_sequences(hand, tile):
                label = "吃 " + " ".join(tile_display_name(t) for t in seq)
                actions.append({"type": "chi", "tile": tile, "tiles": seq, "label": label})
        actions.append({"type": "pass", "tile": tile, "label": "过"})
        return actions

    def apply_self_action(self, action: dict[str, Any]) -> None:
        action_type = str(action.get("type") or "")
        if action_type == "hu":
            self._win(self.local_player, "自摸")
        elif action_type == "kan_closed":
            tile = str(action.get("tile") or "")
            self._remove_tiles(self.local_player, [tile] * 4)
            self.players[self.local_player].melds.append({"type": "kan_closed", "tiles": [tile] * 4})
            self.event_log.append(f"{_now_text()} 我方暗杠{tile_display_name(tile)}")
            self._draw_for(self.local_player)
            self.current_turn = "self"

    def apply_response_action(self, action: dict[str, Any]) -> None:
        if not self.pending_response:
            return
        action_type = str(action.get("type") or "pass")
        responder = int(self.pending_response.get("responder"))
        discarder = int(self.pending_response.get("discarder"))
        tile = str(self.pending_response.get("tile") or action.get("tile") or "")
        self.pending_response = None
        if action_type == "pass":
            if responder == self.local_player:
                self._draw_for(self.local_player)
                self.current_turn = "self"
            else:
                self.current_turn = "enemy"
            return
        if action_type == "hu":
            self._win(responder, f"胡 {tile_display_name(tile)}")
            return
        if action_type == "pon":
            self._remove_tiles(responder, [tile, tile])
            self._remove_last_discard(discarder, tile)
            self.players[responder].melds.append({"type": "pon", "tiles": [tile, tile, tile]})
            self.current_turn = "self" if responder == self.local_player else "enemy"
            self.event_log.append(f"{_now_text()} {self._actor(responder)}碰{tile_display_name(tile)}")
            return
        if action_type == "kan_open":
            self._remove_tiles(responder, [tile, tile, tile])
            self._remove_last_discard(discarder, tile)
            self.players[responder].melds.append({"type": "kan_open", "tiles": [tile] * 4})
            self.event_log.append(f"{_now_text()} {self._actor(responder)}明杠{tile_display_name(tile)}")
            self._draw_for(responder)
            self.current_turn = "self" if responder == self.local_player else "enemy"
            return
        if action_type == "chi":
            tiles = list(action.get("tiles") or [])
            remove = list(tiles)
            remove.remove(tile)
            self._remove_tiles(responder, remove)
            self._remove_last_discard(discarder, tile)
            self.players[responder].melds.append({"type": "chi", "tiles": sorted(tiles, key=tile_sort_key)})
            self.current_turn = "self" if responder == self.local_player else "enemy"
            self.event_log.append(
                f"{_now_text()} {self._actor(responder)}吃{' '.join(tile_display_name(t) for t in sorted(tiles, key=tile_sort_key))}"
            )

    def _choose_opponent_discard(self) -> str:
        opponent = self.players[self.opponent_player]
        if not opponent.hand:
            return ""
        return sorted(opponent.hand, key=tile_sort_key)[-1]

    def _choose_computer_response(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        priority = {"hu": 0, "kan_open": 1, "pon": 2, "chi": 3, "pass": 9}
        return sorted(actions or [{"type": "pass", "label": "过"}], key=lambda a: priority.get(str(a.get("type")), 8))[0]

    def _apply_best_closed_kong(self, player_id: int) -> bool:
        hand = self.players[player_id].hand
        for tile in sorted(set(hand), key=tile_sort_key):
            if hand.count(tile) >= 4:
                self._remove_tiles(player_id, [tile] * 4)
                self.players[player_id].melds.append({"type": "kan_closed", "tiles": [tile] * 4})
                self.event_log.append(f"{_now_text()} {self._actor(player_id)}暗杠{tile_display_name(tile)}")
                self._draw_for(player_id)
                return True
        return False

    def _is_win(self, player_id: int, extra_tile: str | None = None) -> bool:
        player = self.players[player_id]
        hand = list(player.hand)
        if extra_tile:
            hand.append(extra_tile)
        counts, baida_count = hand_to_counts(hand, self.baida_tile)
        return calc_shanten(counts, len(player.melds), baida_count) == -1

    def _win(self, player_id: int, note: str) -> None:
        self.phase = "finished"
        self.current_turn = "none"
        self.pending_response = None
        self.event_log.append(f"{_now_text()} {self._actor(player_id)}{note}")

    def _actor(self, player_id: int) -> str:
        return "我方" if player_id == self.local_player else "对面"

    def _remove_tiles(self, player_id: int, tiles: list[str]) -> None:
        hand = self.players[player_id].hand
        for tile in tiles:
            hand.remove(tile)

    def _remove_last_discard(self, player_id: int, tile: str) -> None:
        discards = self.players[player_id].discards
        for idx in range(len(discards) - 1, -1, -1):
            if discards[idx] == tile:
                del discards[idx]
                return

    def _chi_sequences(self, hand: list[str], tile: str) -> list[list[str]]:
        if not tile or suit_of(tile) == "z":
            return []
        rank = rank_of(tile)
        suit = suit_of(tile)
        result: list[list[str]] = []
        for start in (rank - 2, rank - 1, rank):
            seq = [f"{start + i}{suit}" for i in range(3)]
            if start < 1 or start + 2 > 9 or tile not in seq:
                continue
            needed = list(seq)
            needed.remove(tile)
            if all(hand.count(t) >= needed.count(t) for t in set(needed)):
                result.append(seq)
        return result

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
            tuple((m["type"], tuple(m["tiles"])) for m in self_player.melds),
            tuple((m["type"], tuple(m["tiles"])) for m in opponent.melds),
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
        effective_count = len(self_player.hand) + sum(len(m.get("tiles", [])) for m in self_player.melds)
        optional_actions = []
        if self.pending_response and self.pending_response.get("responder") == self.local_player:
            optional_actions = [str(a.get("type")) for a in self.pending_response.get("actions", [])]
        elif self.current_turn == "self":
            optional_actions = [str(a.get("type")) for a in self.available_self_actions()]
        blocked = ""
        if self.phase != "playing":
            blocked = "模拟局已结束"
        elif self.current_turn != "self":
            blocked = "等待我方出牌回合"
        elif optional_actions:
            blocked = "等待处理模拟可选动作"
        elif effective_count != 14:
            blocked = f"有效手牌数为 {effective_count}，需要 14"
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
            "optional_actions": optional_actions,
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
            "analysis_ready": (
                self.current_turn == "self"
                and effective_count == 14
                and self.phase == "playing"
                and not optional_actions
            ),
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
