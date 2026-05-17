from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from game.tiles import tile_display_name
from stable.mapping import MappingStore
from stable.protocol import (
    MJProtocol,
    PcapParser,
    ProtocolMessage,
    SOURCE_TRUSTED_ACTION,
    SOURCE_TRUSTED_HAND,
    raw_key,
)
from stable.tracker import PacketStateTracker


def _message_from_json(data: dict[str, Any]) -> ProtocolMessage:
    message = ProtocolMessage(
        ts=str(data.get("ts") or ""),
        direction=str(data.get("dir") or data.get("direction") or ""),
        msg_type=int(data.get("type") or data.get("msg_type") or 0),
        type_name=str(data.get("type_name") or ""),
        sub_type=int(data.get("sub") or data.get("sub_type") or 0),
        extra=str(data.get("extra") or ""),
        size=int(data.get("size") or 0),
        pay_len=int(data.get("pay_len") or 0),
        game=data.get("game"),
        raw_hex=str(data.get("raw_hex") or ""),
    )
    if message.raw_hex:
        try:
            raw = bytes.fromhex(message.raw_hex)
            if len(raw) >= 12:
                pay_len = int.from_bytes(raw[2:4], "little")
                total = 12 + pay_len
                if len(raw) >= total:
                    decoded = MJProtocol()._decode_frame(raw[:total], message.direction or "S->C", 0)
                    if decoded is not None:
                        decoded.ts = message.ts
                        return decoded
        except Exception:
            pass
    return message


def _iter_jsonl(path: Path) -> Iterable[ProtocolMessage]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield _message_from_json(json.loads(line))


def _iter_pcap(path: Path, port: int) -> Iterable[ProtocolMessage]:
    parser = PcapParser()
    protocol = MJProtocol(server_port=port)
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            for pkt in parser.feed(chunk):
                yield from protocol.process_packet(pkt)


def _iter_messages(path: Path, port: int) -> Iterable[ProtocolMessage]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        yield from _iter_jsonl(path)
        return
    if suffix in {".pcap", ".cap"}:
        yield from _iter_pcap(path, port)
        return
    raise ValueError(f"unsupported replay input: {path}")


def _map_raw(store: MappingStore, context: str, value: int) -> str:
    key = raw_key(context, int(value))
    tile = store.resolve_tile(key)
    if not tile:
        return f"{key}->?"
    return f"{key}->{tile_display_name(tile)}({tile})"


def _mapped_list(store: MappingStore, context: str, values: list[int]) -> str:
    return " ".join(_map_raw(store, context, int(v)) for v in values)


def _event_label(game: dict[str, Any]) -> str:
    source = str(game.get("source") or "")
    if source in (SOURCE_TRUSTED_ACTION, SOURCE_TRUSTED_HAND):
        return "TRUSTED"
    if game.get("event"):
        return "UNTRUSTED"
    return "RAW"


def _describe_game(store: MappingStore, game: dict[str, Any]) -> str:
    parts = [
        f"sub={game.get('sub_name')}({game.get('sub_cmd')})",
        f"event={game.get('event') or '-'}",
        f"source={game.get('source') or '-'}",
    ]
    if "player" in game:
        parts.append(f"player={game.get('player')}")
    if "hand_raw" in game:
        parts.append(
            "hand="
            + _mapped_list(store, str(game.get("hand_context") or "linear"), list(game.get("hand_raw") or []))
        )
    if "untrusted_hand_raw_candidate" in game:
        parts.append(
            "untrusted_hand_candidate="
            + _mapped_list(
                store,
                str(game.get("untrusted_hand_context") or "linear"),
                list(game.get("untrusted_hand_raw_candidate") or []),
            )
        )
    if "tile_raw" in game:
        parts.append("tile=" + _map_raw(store, str(game.get("tile_context") or "linear"), int(game["tile_raw"])))
    if "baida_raw" in game:
        parts.append("baida=" + _map_raw(store, str(game.get("baida_context") or "linear"), int(game["baida_raw"])))
    if "untrusted_baida_raw_candidate" in game:
        parts.append(
            "untrusted_baida_candidate="
            + _map_raw(
                store,
                str(game.get("untrusted_baida_context") or "linear"),
                int(game["untrusted_baida_raw_candidate"]),
            )
        )
    if game.get("body_hex"):
        parts.append(f"body={str(game.get('body_hex'))[:96]}")
    return " | ".join(parts)


def replay(path: Path, port: int, local_player: int, mapping_path: str | None) -> int:
    store = MappingStore(path=mapping_path)
    tracker = PacketStateTracker(store, local_player=local_player)
    total = 0
    shown = 0
    for msg in _iter_messages(path, port):
        total += 1
        game = msg.game or {}
        if not game:
            continue
        before_reason = tracker.analysis_blocked_reason()
        changed = tracker.apply(msg)
        after = tracker.snapshot()
        label = _event_label(game)
        if changed or game.get("event") or "untrusted_hand_raw_candidate" in game or "baida_raw" in game:
            shown += 1
            ts = msg.ts[11:23] if len(msg.ts) >= 23 else msg.ts
            print(f"{ts} [{label}] {_describe_game(store, game)}")
            if before_reason != after.get("analysis_blocked_reason"):
                print(f"  blocked: {before_reason or '-'} -> {after.get('analysis_blocked_reason') or '-'}")
            print(
                "  state: "
                f"phase={after.get('phase')} turn={after.get('current_turn')} "
                f"hand_trusted={after.get('hand_trusted')} baida_trusted={after.get('baida_trusted')} "
                f"self_hand={after.get('players', {}).get(local_player, {}).get('hand', [])} "
                f"baida={after.get('baida_tile') or '-'}"
            )
    print(f"\nmessages={total} displayed={shown} final_blocked={tracker.analysis_blocked_reason() or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay saved stable-reader packet events.")
    parser.add_argument("path", help="events_*.jsonl or raw_*.pcap")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--local-player", type=int, default=1)
    parser.add_argument("--mapping-path", default=None)
    args = parser.parse_args(argv)
    return replay(Path(args.path), args.port, args.local_player, args.mapping_path)


if __name__ == "__main__":
    raise SystemExit(main())
