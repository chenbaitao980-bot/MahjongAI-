from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from battle.state import BattleState, meld_from_ids, tile_from_id
from game.state import ALL_TILE_IDS
from game.tiles import tile_display_name, tile_sort_key
from stable.mapping import MappingStore
from stable.protocol import (
    HIDDEN_TILE,
    ProtocolMessage,
    SOURCE_TRUSTED_ACTION,
    SOURCE_TRUSTED_HAND,
    SOURCE_UNTRUSTED_ROUND_MARKER,
    is_hidden_tile,
    raw_key,
)


LOCAL_PLAYER_DEFAULT = 1
NOTE_CN = {
    "deal": "发牌",
    "hand": "手牌",
    "draw": "摸牌",
    "discard": "出牌",
    "kong": "杠牌",
    "baida": "财神",
}
MELD_TYPE_CN = {
    "chi": "吃",
    "pon": "碰",
    "kan_open": "明杠",
    "kan_closed": "暗杠",
    "kan_added": "补杠",
}


@dataclass
class PacketPlayerState:
    player_id: int
    hand: list[str] = field(default_factory=list)
    hand_count: int = 0
    discards: list[str] = field(default_factory=list)
    melds: list[dict[str, Any]] = field(default_factory=list)


class PacketStateTracker:
    """Build a decision-ready battle state from decoded packet events."""

    def __init__(self, mapping_store: MappingStore, local_player: int = LOCAL_PLAYER_DEFAULT, player_count: int = 4):
        self.mapping_store = mapping_store
        self.local_player = int(local_player)
        self.player_count = max(2, min(4, int(player_count)))
        self.history: list[ProtocolMessage] = []
        self._last_analyzed_signature: tuple[Any, ...] | None = None
        self.reset()

    def reset(self, keep_history: bool = False) -> None:
        if not keep_history:
            self.history = []
        self.players = {i: PacketPlayerState(i) for i in range(4)}
        self.remaining_tiles = 108
        self.baida_tile = ""
        self.hand_trusted = False
        self.baida_trusted = False
        self.turn_trusted = False
        self.current_turn = "none"
        self.phase = "idle"
        self.event_log: list[str] = []
        self.last_error = ""
        self._last_discard_echo: tuple[int, str] | None = None

    @property
    def opponent_player(self) -> int:
        if self.player_count == 2:
            return 1 - self.local_player if self.local_player in (0, 1) else (self.local_player + 1) % 4
        return (self.local_player + 2) % 4

    def _maybe_lock_local_player(self, player_id: int, raw_len: int, source: str) -> None:
        if source != SOURCE_TRUSTED_HAND:
            return
        if self.hand_trusted:
            return
        if raw_len < 13:
            return
        if player_id not in self.players:
            return
        self.local_player = player_id

    def _is_relevant_player(self, player_id: int) -> bool:
        return player_id in (self.local_player, self.opponent_player)

    def rebuild_from_history(self) -> None:
        history = list(self.history)
        self.mapping_store.clear_unknowns()
        self.reset(keep_history=True)
        self.history = []
        for msg in history:
            self.apply(msg, record_history=True)

    def apply(self, message: ProtocolMessage, record_history: bool = True) -> bool:
        if record_history:
            self.history.append(message)
            if len(self.history) > 1000:
                self.history = self.history[-1000:]
        game = message.game or {}
        event = game.get("event")
        if not event and "baida_raw" not in game:
            return False

        try:
            changed = self._apply_game_event(game)
        except Exception as exc:
            self.last_error = str(exc)
            return False
        if changed and not bool(game.get("suppress_event_log")):
            self._append_event(message, game)
        return changed


    def _apply_game_event(self, game: dict[str, Any]) -> bool:
        event = str(game.get("event") or "")
        player = game.get("player")
        source = str(game.get("source") or "")

        if event == "deal":
            self.reset(keep_history=True)
            self.phase = "playing"
            self.current_turn = "none"
            self.turn_trusted = False
            if source == SOURCE_TRUSTED_HAND:
                player_id = int(player if player is not None else self.local_player)
                hand = self._resolve_tiles(game.get("hand_raw", []), str(game.get("hand_context") or "linear"), "deal")
                if player_id == self.local_player:
                    self.players[player_id].hand = hand
                    self.players[player_id].hand_count = len(
                        [v for v in game.get("hand_raw", []) if int(v) not in (0, HIDDEN_TILE)]
                    )
                    self.hand_trusted = True
                self._apply_baida(game)
            return True

        if event in ("draw", "discard", "kong", "win") and source != SOURCE_TRUSTED_ACTION:
            return False
        if event == "win" and not self.hand_trusted:
            return False

        if event == "hand_update":
            player_id = int(player)
            raw_len = len(game.get("hand_raw", []))
            if self._is_new_round_hand_update(player_id, raw_len, source):
                history = self.history
                self.reset(keep_history=True)
                self.history = history
                self.phase = "playing"
            self._maybe_lock_local_player(player_id, raw_len, source)
            if self._is_relevant_player(player_id):
                if source == SOURCE_TRUSTED_HAND:
                    hand = self._resolve_tiles(game.get("hand_raw", []), str(game.get("hand_context") or "nibble"), "hand")
                    self.players[player_id].hand = hand
                    if player_id == self.local_player:
                        self.hand_trusted = True
                elif player_id == self.local_player:
                    self.hand_trusted = False
            self.players[player_id].hand_count = int(raw_len)
            if player_id == self.local_player and self._effective_self_count() == 14:
                self.current_turn = "self"
                self.turn_trusted = source == SOURCE_TRUSTED_HAND
            elif player_id == self.local_player:
                self.current_turn = "none"
                self.turn_trusted = False
            return True

        if event == "draw":
            player_id = int(player if player is not None else -1)
            tile = self._resolve_tile_from_game(game, "draw", note_zero=False) if self._is_relevant_player(player_id) else None
            if tile and self._consume_discard_echo(player_id, tile):
                game["suppress_event_log"] = True
                if player_id == self.local_player:
                    self.current_turn = "self"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
                elif player_id == self.opponent_player:
                    self.current_turn = "enemy"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
                return True
            self._last_discard_echo = None
            self.remaining_tiles = max(0, self.remaining_tiles - 1)
            if player_id in self.players:
                self.players[player_id].hand_count += 1
                if tile and player_id == self.local_player:
                    self.players[player_id].hand.append(tile)
                if player_id == self.local_player:
                    self.current_turn = "self"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
                elif player_id == self.opponent_player:
                    self.current_turn = "enemy"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
            return True

        if event == "discard":
            player_id = int(player if player is not None else -1)
            tile = self._resolve_tile_from_game(game, "discard") if self._is_relevant_player(player_id) else None
            if player_id in self.players:
                if tile:
                    self.players[player_id].discards.append(tile)
                    self._last_discard_echo = (player_id, tile)
                self.players[player_id].hand_count = max(0, self.players[player_id].hand_count - 1)
                if player_id == self.local_player:
                    if tile:
                        self._remove_one(self.players[player_id].hand, tile)
                    self.current_turn = "enemy"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
                elif player_id == self.opponent_player:
                    self.current_turn = "none"
                    self.turn_trusted = source == SOURCE_TRUSTED_ACTION
            return True

        if event == "kong":
            self._last_discard_echo = None
            player_id = int(player if player is not None else self.local_player)
            tile = self._resolve_tile_from_game(game, "kong", note_zero=self._is_relevant_player(player_id))
            if tile:
                self._remove_claimed_discard(tile, claimant=player_id)
            if player_id in self.players and self._is_relevant_player(player_id) and tile and game.get("meld_type"):
                meld_type = str(game.get("meld_type") or "kan_open")
                meld_tiles = self._resolve_tiles(
                    list(game.get("meld_tiles_raw") or []),
                    str(game.get("tile_context") or "stable"),
                    "kong",
                ) or [tile] * 4
                self.players[player_id].melds.append(
                    {"type": meld_type, "tiles": meld_tiles}
                )
                if player_id == self.local_player:
                    for meld_tile in meld_tiles:
                        self._remove_one(self.players[player_id].hand, meld_tile)
                if meld_type.startswith("kan"):
                    self.remaining_tiles = max(0, self.remaining_tiles - 1)
            return True

        if event == "win":
            self.phase = "hupai"
            self.current_turn = "none"
            return True

        if "baida_raw" in game:
            return self._apply_baida(game)

        return False

    def _apply_baida(self, game: dict[str, Any]) -> bool:
        if "baida_raw" not in game:
            return False
        if not bool(game.get("baida_trusted")):
            return False
        value = int(game.get("baida_raw") or 0)
        if value in (0, HIDDEN_TILE):
            return False
        key = raw_key(str(game.get("baida_context") or "linear"), value)
        tile = self.mapping_store.resolve_tile(key)
        if tile in ALL_TILE_IDS:
            self.baida_tile = tile
            self.baida_trusted = True
        else:
            self.mapping_store.note_unknown(key, "baida")
        return True

    def _resolve_tiles(self, raw_values: list[int], context: str, note: str) -> list[str]:
        tiles: list[str] = []
        for value in raw_values:
            if int(value) == 0 or is_hidden_tile(int(value)):
                continue
            key = raw_key(context, int(value))
            tile = self.mapping_store.resolve_tile(key)
            if tile in ALL_TILE_IDS:
                tiles.append(tile)
            else:
                self.mapping_store.note_unknown(key, note)
        return tiles

    def _resolve_tile_from_game(self, game: dict[str, Any], note: str, note_zero: bool = True) -> str | None:
        if "tile_raw" not in game:
            return None
        value = int(game.get("tile_raw") or 0)
        if value == 0 or value == HIDDEN_TILE:
            if note_zero:
                key = raw_key(str(game.get("tile_context") or "linear"), value)
                self.mapping_store.note_unknown(key, note)
            return None
        key = raw_key(str(game.get("tile_context") or "linear"), value)
        tile = self.mapping_store.resolve_tile(key)
        if tile in ALL_TILE_IDS:
            return tile
        self.mapping_store.note_unknown(key, note)
        return None

    def _is_new_round_hand_update(self, player_id: int, raw_len: int, source: str) -> bool:
        if source != SOURCE_TRUSTED_HAND:
            return False
        if player_id != self.local_player:
            return False
        if raw_len not in (13, 14):
            return False
        if not self.hand_trusted:
            return False
        if self.phase == "hupai":
            return True
        has_visible_old_round = any(
            p.discards or p.melds
            for p in self.players.values()
        )
        return self.phase == "playing" and has_visible_old_round and self.remaining_tiles <= 70

    @staticmethod
    def _remove_one(items: list[str], tile: str) -> None:
        try:
            items.remove(tile)
        except ValueError:
            pass

    def _consume_discard_echo(self, player_id: int, tile: str) -> bool:
        if self._last_discard_echo is None:
            return False
        discard_player, discard_tile = self._last_discard_echo
        self._last_discard_echo = None
        return discard_player != player_id and discard_tile == tile


    def _remove_claimed_discard(self, tile: str, claimant: int) -> None:
        for pid in (self.local_player, self.opponent_player):
            if pid == claimant:
                continue
            discards = self.players[pid].discards
            for idx in range(len(discards) - 1, -1, -1):
                if discards[idx] == tile:
                    del discards[idx]
                    return

    def _append_event(self, message: ProtocolMessage, game: dict[str, Any]) -> None:
        event = game.get("event", "")
        player_raw = game.get("player")
        player_id = int(player_raw) if player_raw is not None else self.local_player
        if event not in ("deal", "win") and not self._is_relevant_player(player_id):
            return
        time_text = message.ts[11:19]
        actor = self._actor_name(player_id)
        tile_text = self._tile_text_from_game(game)
        if event == "deal" and str(game.get("source") or "") != SOURCE_TRUSTED_HAND:
            text = f"{time_text} 开局标记：等待可信手牌包"
        elif event == "deal":
            text = f"{time_text} 开局发牌：我方手牌 {len(game.get('hand_raw', []))} 张"
        elif event == "hand_update":
            text = f"{time_text} {actor}手牌更新：{len(game.get('hand_raw', []))} 张"
        elif event == "draw":
            text = f"{time_text} {actor}摸牌" + (tile_text if tile_text else "")
        elif event == "discard":
            text = f"{time_text} {actor}打出" + (tile_text if tile_text else "")
        elif event == "kong":
            meld_text = MELD_TYPE_CN.get(str(game.get("meld_type") or "kan_open"), "副露")
            text = f"{time_text} {actor}{meld_text}" + (tile_text if tile_text else "")
        elif event == "win":
            text = f"{time_text} 胡牌结算"
        elif "baida_raw" in game:
            text = f"{time_text} 财神更新：{self._baida_text_from_game(game)}"
        else:
            return
        self.event_log.append(text)
        if len(self.event_log) > 300:
            self.event_log = self.event_log[-300:]

    def _actor_name(self, player_id: int) -> str:
        if player_id == self.local_player:
            return "我方"
        if player_id == self.opponent_player:
            return "对面"
        return "旁家"

    def _tile_text_from_game(self, game: dict[str, Any]) -> str:
        if "tile_raw" not in game:
            return ""
        key = raw_key(str(game.get("tile_context") or "linear"), int(game.get("tile_raw") or 0))
        tile = self.mapping_store.resolve_tile(key)
        if tile in ALL_TILE_IDS:
            return tile_display_name(tile)
        return f"未识别牌（{self._raw_key_display(key)}）"

    def _baida_text_from_game(self, game: dict[str, Any]) -> str:
        if "baida_raw" not in game:
            return ""
        key = raw_key(str(game.get("baida_context") or "linear"), int(game.get("baida_raw") or 0))
        tile = self.mapping_store.resolve_tile(key)
        if tile in ALL_TILE_IDS:
            return tile_display_name(tile)
        return f"未识别财神（{self._raw_key_display(key)}）"

    @staticmethod
    def _raw_key_display(key: str) -> str:
        context, _, value = key.partition(":")
        context_name = {
            "instance": "实体牌",
            "linear": "线性牌",
            "nibble": "半字节牌",
        }.get(context, "原始牌")
        return f"{context_name}{value}"

    def snapshot(self) -> dict[str, Any]:
        visible_players = {
            self.local_player: self.players[self.local_player],
            self.opponent_player: self.players[self.opponent_player],
        }
        return {
            "phase": self.phase,
            "local_player": self.local_player,
            "opponent_player": self.opponent_player,
            "current_turn": self.current_turn,
            "remaining_tiles": self.remaining_tiles,
            "baida_tile": self.baida_tile,
            "hand_trusted": self.hand_trusted,
            "baida_trusted": self.baida_trusted,
            "turn_trusted": self.turn_trusted,
            "players": {
                pid: {
                    "hand": sorted(p.hand, key=tile_sort_key) if pid == self.local_player else list(p.hand),
                    "hand_count": p.hand_count,
                    "discards": list(p.discards),
                    "melds": list(p.melds),
                }
                for pid, p in visible_players.items()
            },
            "events": list(self.event_log[-120:]),
            "unknowns": [
                {
                    "raw_key": u.raw_key,
                    "display_key": self._raw_key_display(u.raw_key),
                    "count": u.count,
                    "note": NOTE_CN.get(u.note, u.note),
                }
                for u in self.mapping_store.unknowns()
            ],
            "analysis_ready": self.should_analyze(),
            "analysis_blocked_reason": self.analysis_blocked_reason(),
            "last_error": self.last_error,
        }

    def to_battle_state(self) -> BattleState:
        state = BattleState(ai_recognition_enabled=False)
        self_player = self.players[self.local_player]
        enemy_player = self.players[self.opponent_player]
        state.baida_tile = self.baida_tile
        state.remaining_tiles = self.remaining_tiles
        state.current_turn = self.current_turn
        state.recognition_source = "packet"
        state.self_hand = [tile_from_id(t) for t in self_player.hand]
        state.self_discards = [tile_from_id(t) for t in self_player.discards]
        state.self_melds = [meld_from_ids(m["type"], list(m["tiles"])) for m in self_player.melds]
        state.enemy_discards = [tile_from_id(t) for t in enemy_player.discards]
        state.enemy_melds = [meld_from_ids(m["type"], list(m["tiles"])) for m in enemy_player.melds]
        state.append_operation(
            "packet_snapshot",
            {
                "local_player": self.local_player,
                "opponent_player": self.opponent_player,
                "phase": self.phase,
                "events": self.event_log[-20:],
            },
        )
        return state

    def should_analyze(self) -> bool:
        if self.analysis_blocked_reason():
            return False
        sig = self.analysis_signature()
        return sig != self._last_analyzed_signature

    def mark_analyzed(self) -> None:
        self._last_analyzed_signature = self.analysis_signature()

    def analysis_signature(self) -> tuple[Any, ...]:
        player = self.players[self.local_player]
        opponent = self.players[self.opponent_player]
        return (
            tuple(player.hand),
            tuple(player.discards),
            tuple((m["type"], tuple(m["tiles"])) for m in player.melds),
            tuple(opponent.discards),
            tuple((m["type"], tuple(m["tiles"])) for m in opponent.melds),
            self.remaining_tiles,
            self.baida_tile,
            self.current_turn,
            self.hand_trusted,
            self.baida_trusted,
            self.turn_trusted,
        )

    def analysis_blocked_reason(self) -> str:
        if not self.hand_trusted:
            return "等待可信手牌包"
        if not self.baida_tile or not self.baida_trusted:
            return "等待抓包解析财神"
        if self.mapping_store.unknowns():
            return f"还有 {len(self.mapping_store.unknowns())} 个未确认牌值"
        if not self.turn_trusted:
            return "等待可信回合包"
        if self.current_turn != "self":
            return "还没轮到我方出牌"
        count = self._effective_self_count()
        if count != 14:
            return f"我方有效手牌数为 {count}，需要 14"
        return ""

    def _effective_self_count(self) -> int:
        player = self.players[self.local_player]
        meld_tile_count = sum(len(m.get("tiles", [])) for m in player.melds)
        return len(player.hand) + meld_tile_count
