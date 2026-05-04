from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime


def _connect_db(session_dir: str) -> sqlite3.Connection:
    db_path = os.path.join(session_dir, "session.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS frames (
            frame_index INTEGER PRIMARY KEY,
            timestamp_ms INTEGER NOT NULL,
            phase TEXT,
            remaining_tiles INTEGER,
            decision_prompt_json TEXT NOT NULL,
            events_json TEXT NOT NULL,
            min_confidence REAL,
            state_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS region_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frame_index INTEGER NOT NULL,
            region_name TEXT NOT NULL,
            kind TEXT,
            x INTEGER,
            y INTEGER,
            w INTEGER,
            h INTEGER,
            item_count INTEGER,
            recognized_count INTEGER,
            confidence_min REAL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_region_frame ON region_observations(frame_index);
        CREATE INDEX IF NOT EXISTS idx_region_name ON region_observations(region_name);

        CREATE TABLE IF NOT EXISTS tile_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frame_index INTEGER NOT NULL,
            region_name TEXT NOT NULL,
            seat TEXT,
            slot_index INTEGER,
            tile_id TEXT,
            confidence REAL,
            method TEXT,
            x INTEGER,
            y INTEGER,
            w INTEGER,
            h INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tile_frame ON tile_observations(frame_index);
        CREATE INDEX IF NOT EXISTS idx_tile_region ON tile_observations(region_name);
        CREATE INDEX IF NOT EXISTS idx_tile_id ON tile_observations(tile_id);

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frame_index INTEGER NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_event_frame ON events(frame_index);
        CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type);

        CREATE TABLE IF NOT EXISTS game_state_current (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            frame_index INTEGER NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            phase TEXT,
            remaining_tiles INTEGER,
            dealer_seat TEXT,
            self_hand_json TEXT NOT NULL,
            discards_json TEXT NOT NULL,
            melds_json TEXT NOT NULL,
            opponents_json TEXT NOT NULL,
            decision_prompt_json TEXT NOT NULL,
            visible_tile_counts_json TEXT NOT NULL,
            unknown_summary_json TEXT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def _load_recognition_summary(session_dir: str, frame_index: int) -> list[dict]:
    path = os.path.join(session_dir, "recognition", f"frame_{frame_index:04d}", "summary.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    return summary.get("tiles", [])


def _visible_counts(state: dict) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    unknown = 0
    player = state.get("self", {})
    opponents = state.get("opp", [])
    groups = [player.get("hand", []), player.get("discards", [])]
    groups.extend(opp.get("discards", []) for opp in opponents)
    for tiles in groups:
        for tile in tiles:
            tid = tile.get("t")
            if tid:
                counts[tid] = counts.get(tid, 0) + 1
            else:
                unknown += 1
    return counts, unknown


def backfill(session_dir: str) -> None:
    frames_path = os.path.join(session_dir, "frames.jsonl")
    if not os.path.isfile(frames_path):
        raise FileNotFoundError(frames_path)

    conn = _connect_db(session_dir)
    cur = conn.cursor()
    for table in ("frames", "region_observations", "tile_observations", "events", "game_state_current"):
        cur.execute(f"DELETE FROM {table}")

    details_path = os.path.join(session_dir, "frame_details.jsonl")
    last_state: dict | None = None
    frame_count = 0

    with open(frames_path, "r", encoding="utf-8") as f, open(details_path, "w", encoding="utf-8") as details:
        for line in f:
            if not line.strip():
                continue
            state = json.loads(line)
            fi = int(state.get("fi", frame_count))
            ts = int(state.get("ts", 0))
            events = state.get("events", [])
            decision = state.get("decision", [])
            recognition_tiles = _load_recognition_summary(session_dir, fi)

            hand_items = []
            for i, tile in enumerate(recognition_tiles or state.get("self", {}).get("hand", [])):
                tile_id = tile.get("tile_id", tile.get("t"))
                conf = tile.get("confidence", tile.get("c", 0))
                hand_items.append({
                    "slot": i,
                    "tile_id": tile_id,
                    "confidence": conf,
                    "method": tile.get("method", "backfill"),
                })

            regions = {
                "self_hand": {
                    "name": "self_hand",
                    "rect": {},
                    "kind": "tile_sequence",
                    "items": hand_items,
                    "summary": {
                        "source": "backfill_from_recognition_summary",
                        "tile_count": len(hand_items),
                        "recognized_count": sum(1 for item in hand_items if item.get("tile_id")),
                    },
                }
            }

            for seat_idx, seat in enumerate(("right", "across", "left")):
                opp = state.get("opp", [{} for _ in range(3)])[seat_idx] if len(state.get("opp", [])) > seat_idx else {}
                regions[f"discard.{seat}"] = {
                    "name": f"discard.{seat}",
                    "rect": {},
                    "kind": "discard_grid",
                    "items": [
                        {"slot": i, "tile_id": t.get("t"), "confidence": t.get("c", 0), "method": "backfill"}
                        for i, t in enumerate(opp.get("discards", []))
                    ],
                    "summary": {"source": "backfill_from_frames_jsonl", "seat": seat},
                }
            regions["discard.self"] = {
                "name": "discard.self",
                "rect": {},
                "kind": "discard_grid",
                "items": [
                    {"slot": i, "tile_id": t.get("t"), "confidence": t.get("c", 0), "method": "backfill"}
                    for i, t in enumerate(state.get("self", {}).get("discards", []))
                ],
                "summary": {"source": "backfill_from_frames_jsonl", "seat": "self"},
            }
            regions["remaining_tiles"] = {
                "name": "remaining_tiles",
                "rect": {},
                "kind": "number",
                "items": [],
                "summary": {"value": state.get("rt"), "source": "backfill_from_frames_jsonl"},
            }
            regions["decision_buttons"] = {
                "name": "decision_buttons",
                "rect": {},
                "kind": "buttons",
                "items": [{"button": b, "visible": True} for b in decision],
                "summary": {"visible_buttons": decision, "count": len(decision)},
            }
            regions["game_overlay"] = {
                "name": "game_overlay",
                "rect": {},
                "kind": "overlay",
                "items": [],
                "summary": {"phase": state.get("phase"), "source": "backfill_from_frames_jsonl"},
            }

            detail = {
                "frame_index": fi,
                "timestamp_ms": ts,
                "phase": state.get("phase"),
                "remaining_tiles": state.get("rt"),
                "events": events,
                "regions": regions,
                "state": {
                    "self": state.get("self", {}),
                    "opponents": state.get("opp", []),
                    "decision": decision,
                },
                "debug": state.get("dbg", {}),
                "backfilled": True,
            }
            details.write(json.dumps(detail, ensure_ascii=False) + "\n")

            cur.execute(
                """
                INSERT INTO frames
                (frame_index, timestamp_ms, phase, remaining_tiles, decision_prompt_json,
                 events_json, min_confidence, state_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fi,
                    ts,
                    state.get("phase"),
                    state.get("rt"),
                    json.dumps(decision, ensure_ascii=False),
                    json.dumps(events, ensure_ascii=False),
                    state.get("dbg", {}).get("min_conf"),
                    json.dumps(state, ensure_ascii=False),
                ),
            )
            for region_name, region in regions.items():
                items = region.get("items", [])
                confidences = [float(item.get("confidence")) for item in items if item.get("confidence") is not None]
                cur.execute(
                    """
                    INSERT INTO region_observations
                    (frame_index, region_name, kind, item_count, recognized_count,
                     confidence_min, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fi,
                        region_name,
                        region.get("kind"),
                        len(items),
                        sum(1 for item in items if item.get("tile_id") or item.get("button")),
                        min(confidences) if confidences else None,
                        json.dumps(region, ensure_ascii=False),
                    ),
                )
                seat = region_name.split(".", 1)[1] if "." in region_name else region_name
                for item in items:
                    if "tile_id" not in item:
                        continue
                    cur.execute(
                        """
                        INSERT INTO tile_observations
                        (frame_index, region_name, seat, slot_index, tile_id, confidence, method)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fi,
                            region_name,
                            seat,
                            item.get("slot"),
                            item.get("tile_id"),
                            item.get("confidence"),
                            item.get("method"),
                        ),
                    )
            for event in events:
                cur.execute(
                    "INSERT INTO events (frame_index, timestamp_ms, event_type, payload_json) VALUES (?, ?, ?, ?)",
                    (fi, ts, event, json.dumps({"event": event, "backfilled": True}, ensure_ascii=False)),
                )

            counts, unknown = _visible_counts(state)
            cur.execute(
                """
                INSERT OR REPLACE INTO game_state_current
                (id, frame_index, timestamp_ms, phase, remaining_tiles, dealer_seat,
                 self_hand_json, discards_json, melds_json, opponents_json,
                 decision_prompt_json, visible_tile_counts_json, unknown_summary_json,
                 state_json, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fi,
                    ts,
                    state.get("phase"),
                    state.get("rt"),
                    None,
                    json.dumps(state.get("self", {}).get("hand", []), ensure_ascii=False),
                    json.dumps({
                        "self": state.get("self", {}).get("discards", []),
                        "right": state.get("opp", [{}])[0].get("discards", []) if len(state.get("opp", [])) > 0 else [],
                        "across": state.get("opp", [{}, {}])[1].get("discards", []) if len(state.get("opp", [])) > 1 else [],
                        "left": state.get("opp", [{}, {}, {}])[2].get("discards", []) if len(state.get("opp", [])) > 2 else [],
                    }, ensure_ascii=False),
                    json.dumps(state.get("self", {}).get("melds", []), ensure_ascii=False),
                    json.dumps(state.get("opp", []), ensure_ascii=False),
                    json.dumps(decision, ensure_ascii=False),
                    json.dumps(counts, ensure_ascii=False),
                    json.dumps({"unknown_visible_tiles": unknown, "backfilled": True}, ensure_ascii=False),
                    json.dumps(state, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            last_state = state
            frame_count += 1

    conn.commit()
    conn.close()
    print(f"backfilled {frame_count} frames")
    print(details_path)
    print(os.path.join(session_dir, "session.db"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python backfill_session_db.py <session_dir>")
    backfill(sys.argv[1])
