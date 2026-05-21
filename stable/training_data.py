from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from game.stable_hard_analysis import StableHardAnalysis, analyze_snapshot
from stable.mapping import MappingStore
from stable.protocol import ProtocolMessage, SOURCE_TRUSTED_ACTION, raw_key
from stable.tracker import PacketStateTracker


SCHEMA_VERSION = 1
SAMPLE_TYPE_DISCARD_DECISION = "discard_decision"


@dataclass
class ExportStats:
    messages: int = 0
    samples: int = 0
    trainable: int = 0
    blocked: int = 0


def export_training_samples(
    messages: Iterable[ProtocolMessage],
    *,
    mapping_store: MappingStore,
    local_player: int = 1,
    player_count: int = 2,
    source_path: str = "",
    include_blocked: bool = True,
    record_enabled: bool = True,
    train_enabled: bool = False,
    session_mode: str | None = None,
) -> tuple[list[dict[str, Any]], ExportStats]:
    tracker = PacketStateTracker(
        mapping_store,
        local_player=local_player,
        player_count=player_count,
    )
    samples: list[dict[str, Any]] = []
    stats = ExportStats()

    for message_index, message in enumerate(messages, start=1):
        stats.messages += 1
        if not record_enabled:
            tracker.apply(message)
            continue
        game = message.game or {}
        if _is_local_discard(game, tracker.local_player):
            sample = build_discard_decision_sample(
                snapshot=tracker.snapshot(),
                game=game,
                message=message,
                message_index=message_index,
                mapping_store=mapping_store,
                source_path=source_path,
                record_enabled=record_enabled,
                train_enabled=train_enabled,
                session_mode=session_mode,
            )
            if sample["is_trainable"]:
                stats.trainable += 1
                samples.append(sample)
            else:
                stats.blocked += 1
                if include_blocked:
                    samples.append(sample)

        tracker.apply(message)

    stats.samples = len(samples)
    return samples, stats


def build_discard_decision_sample(
    *,
    snapshot: dict[str, Any],
    game: dict[str, Any],
    message: ProtocolMessage,
    message_index: int,
    mapping_store: MappingStore,
    source_path: str = "",
    record_enabled: bool = True,
    train_enabled: bool = False,
    session_mode: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_snapshot(snapshot)
    actual_tile, tile_blocked_reason = _resolve_action_tile(game, mapping_store)
    trainable, blocked_reason = _training_gate(snapshot, analysis, actual_tile)

    mode = session_mode or ("train_enabled" if train_enabled else "record_only")
    sample = {
        "schema_version": SCHEMA_VERSION,
        "sample_type": SAMPLE_TYPE_DISCARD_DECISION,
        "learning": {
            "record_enabled": bool(record_enabled),
            "train_enabled": bool(train_enabled),
            "session_mode": mode,
        },
        "source": {
            "path": source_path,
            "message_index": int(message_index),
            "ts": message.ts,
            "direction": message.direction,
            "msg_type": message.msg_type,
            "sub_type": message.sub_type,
        },
        "state": _snapshot_for_sample(snapshot),
        "hard_analysis": _analysis_for_sample(analysis),
        "actual_action": {
            "action": "discard",
            "tile": actual_tile or "",
            "player": game.get("player"),
            "raw_key": _action_raw_key(game),
        },
        "label": None,
        "is_label_eligible": False,
        "is_trainable": False,
        "blocked_reason": tile_blocked_reason or blocked_reason,
    }

    if trainable:
        sample["is_label_eligible"] = True
        sample["label"] = {"action": "discard", "tile": actual_tile}
        if train_enabled:
            sample["is_trainable"] = True
            sample["blocked_reason"] = ""
        else:
            sample["blocked_reason"] = "training_disabled"
    return sample


def _training_gate(
    snapshot: dict[str, Any],
    analysis: StableHardAnalysis,
    actual_tile: str | None,
) -> tuple[bool, str]:
    if not actual_tile:
        return False, "actual_discard_unresolved"
    if not snapshot.get("hand_trusted"):
        return False, "hand_not_trusted"
    if not snapshot.get("baida_tile") or not snapshot.get("baida_trusted"):
        return False, "baida_not_trusted"
    if not snapshot.get("turn_trusted") or str(snapshot.get("current_turn") or "") != "self":
        return False, "turn_not_trusted_self"
    if snapshot.get("optional_actions"):
        return False, "optional_action_pending"
    if snapshot.get("unknowns"):
        return False, "unknown_mapping"
    candidates = [c.discard for c in analysis.candidates]
    if not candidates:
        return False, str(snapshot.get("analysis_blocked_reason") or analysis.model_status or "no_candidates")
    if actual_tile not in candidates:
        return False, "actual_discard_not_in_candidates"
    return True, ""


def _is_local_discard(game: dict[str, Any], local_player: int) -> bool:
    return (
        str(game.get("event") or "") == "discard"
        and str(game.get("source") or "") == SOURCE_TRUSTED_ACTION
        and int(game.get("player", -1)) == int(local_player)
    )


def _resolve_action_tile(game: dict[str, Any], mapping_store: MappingStore) -> tuple[str | None, str]:
    if "tile_raw" not in game:
        return None, "actual_discard_missing_raw_tile"
    key = _action_raw_key(game)
    tile = mapping_store.resolve_tile(key)
    if not tile:
        mapping_store.note_unknown(key, "training_label")
        return None, "actual_discard_unknown_mapping"
    return tile, ""


def _action_raw_key(game: dict[str, Any]) -> str:
    context = str(game.get("tile_context") or "linear")
    return raw_key(context, int(game.get("tile_raw") or 0))


def _snapshot_for_sample(snapshot: dict[str, Any]) -> dict[str, Any]:
    local = snapshot.get("local_player")
    opponent = snapshot.get("opponent_player")
    players = snapshot.get("players", {}) if isinstance(snapshot.get("players"), dict) else {}
    return {
        "phase": snapshot.get("phase"),
        "local_player": local,
        "opponent_player": opponent,
        "current_turn": snapshot.get("current_turn"),
        "remaining_tiles": snapshot.get("remaining_tiles"),
        "baida_tile": snapshot.get("baida_tile") or "",
        "hand_trusted": bool(snapshot.get("hand_trusted")),
        "baida_trusted": bool(snapshot.get("baida_trusted")),
        "turn_trusted": bool(snapshot.get("turn_trusted")),
        "optional_actions": list(snapshot.get("optional_actions") or []),
        "unknowns": list(snapshot.get("unknowns") or []),
        "analysis_blocked_reason": snapshot.get("analysis_blocked_reason") or "",
        "players": {
            str(pid): _player_for_sample(players.get(pid) or players.get(str(pid)) or {})
            for pid in (local, opponent)
            if pid is not None
        },
    }


def _player_for_sample(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "hand": list(player.get("hand") or []),
        "hand_count": int(player.get("hand_count") or 0),
        "discards": list(player.get("discards") or []),
        "melds": list(player.get("melds") or []),
    }


def _analysis_for_sample(analysis: StableHardAnalysis) -> dict[str, Any]:
    return {
        "current_shanten": analysis.current_shanten,
        "is_ting": bool(analysis.is_ting),
        "ting_tiles": list(analysis.ting_tiles),
        "effective_tiles": list(analysis.effective_tiles),
        "effective_count": int(analysis.effective_count),
        "recommended_discard": analysis.recommended_discard,
        "model_status": analysis.model_status,
        "recommendation_source": analysis.recommendation_source,
        "candidates": [
            {
                "discard": c.discard,
                "shanten_after": c.shanten_after,
                "ukeire_count": c.ukeire_count,
                "ukeire_tiles": list(c.ukeire_tiles),
                "is_caishen": c.is_caishen,
                "model_score": c.model_score,
                "model_source": c.model_source,
                "model_reasons": list(c.model_reasons),
                "model_features": dict(c.model_features),
            }
            for c in analysis.candidates
        ],
    }
