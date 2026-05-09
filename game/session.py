from __future__ import annotations
import json
import os
import queue
import shutil
import sqlite3
import threading
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.state import GameState


class GameSession:
    """管理单局对局数据的存储。"""

    MAX_SESSIONS = 10

    def __init__(self, output_dir: str, config_snapshot: dict):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"session_{ts}"
        self.session_dir = os.path.join(output_dir, self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)

        # 关键帧保存目录（手牌）
        self._keyframes_dir = os.path.join(self.session_dir, "keyframes")
        os.makedirs(self._keyframes_dir, exist_ok=True)

        # 弃牌关键帧目录（独立隔离）
        self._discard_keyframes_dir = os.path.join(self.session_dir, "discard_keyframes")
        os.makedirs(self._discard_keyframes_dir, exist_ok=True)

        meta = {
            "session_id": self.session_id,
            "started_at": datetime.now().isoformat(),
            "app_version": config_snapshot.get("app", {}).get("version", "1.0.0"),
            "config_snapshot": config_snapshot,
        }
        with open(os.path.join(self.session_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        self._frames_path = os.path.join(self.session_dir, "frames.jsonl")
        self._frame_details_path = os.path.join(self.session_dir, "frame_details.jsonl")
        self._analysis_events_path = os.path.join(self.session_dir, "analysis_events.jsonl")
        self._fh = open(self._frames_path, "a", encoding="utf-8", buffering=8192)
        self._details_fh = open(self._frame_details_path, "a", encoding="utf-8", buffering=8192)
        self._analysis_fh = open(self._analysis_events_path, "a", encoding="utf-8", buffering=1)
        self._analysis_event_count = 0
        self._db_path = os.path.join(self.session_dir, "session.db")
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        self._frame_count = 0
        self._keyframe_count = 0
        self._write_queue: queue.Queue = queue.Queue()
        self._writer_error: str | None = None
        self._closed = False
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name=f"GameSessionWriter-{self.session_id}",
            daemon=True,
        )
        self._writer_thread.start()
        self.prune_sessions(output_dir, self.MAX_SESSIONS, keep_session_id=self.session_id)

    def append_frame(self, state: "GameState") -> None:
        state_dict = state.to_dict()
        self._write_queue.put((state, state_dict))
        self._frame_count += 1

    def _writer_loop(self) -> None:
        while True:
            item = self._write_queue.get()
            try:
                if item is None:
                    return
                state, state_dict = item
                line = json.dumps(state_dict, ensure_ascii=False, separators=(",", ":"))
                self._fh.write(line + "\n")
                self._details_fh.write(json.dumps(self._build_frame_detail(state_dict), ensure_ascii=False) + "\n")
                self._append_frame_db(state, state_dict)
            except Exception as exc:
                self._writer_error = str(exc)
            finally:
                self._write_queue.task_done()

    def _init_db(self) -> None:
        """初始化两类数据表：逐帧流水 + 当前牌局现状。"""
        cur = self._db.cursor()
        cur.executescript(
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
                payload_json TEXT NOT NULL,
                FOREIGN KEY(frame_index) REFERENCES frames(frame_index)
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
                h INTEGER,
                FOREIGN KEY(frame_index) REFERENCES frames(frame_index)
            );
            CREATE INDEX IF NOT EXISTS idx_tile_frame ON tile_observations(frame_index);
            CREATE INDEX IF NOT EXISTS idx_tile_region ON tile_observations(region_name);
            CREATE INDEX IF NOT EXISTS idx_tile_id ON tile_observations(tile_id);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frame_index INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(frame_index) REFERENCES frames(frame_index)
            );
            CREATE INDEX IF NOT EXISTS idx_event_frame ON events(frame_index);
            CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type);

            CREATE TABLE IF NOT EXISTS analysis_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trigger TEXT,
                hand_json TEXT,
                candidates_json TEXT,
                advice_json TEXT,
                shanten INTEGER,
                strategy_mode TEXT,
                recommended_discard TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_ts ON analysis_events(timestamp);

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
        self._db.commit()

    def _build_frame_detail(self, state_dict: dict) -> dict:
        return {
            "frame_index": state_dict.get("fi"),
            "timestamp_ms": state_dict.get("ts"),
            "phase": state_dict.get("phase"),
            "remaining_tiles": state_dict.get("rt"),
            "events": state_dict.get("events", []),
            "regions": state_dict.get("regions", {}),
            "state": {
                "self": state_dict.get("self", {}),
                "opponents": state_dict.get("opp", []),
                "decision": state_dict.get("decision", []),
            },
            "debug": state_dict.get("dbg", {}),
        }

    def _append_frame_db(self, state: "GameState", state_dict: dict) -> None:
        cur = self._db.cursor()
        frame_index = state.frame_index
        ts = state.timestamp_ms
        cur.execute(
            """
            INSERT OR REPLACE INTO frames
            (frame_index, timestamp_ms, phase, remaining_tiles, decision_prompt_json,
             events_json, min_confidence, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frame_index,
                ts,
                state.game_phase,
                state.remaining_tiles,
                json.dumps(state.decision_prompt, ensure_ascii=False),
                json.dumps(state.events, ensure_ascii=False),
                state.raw_confidence_min,
                json.dumps(state_dict, ensure_ascii=False),
            ),
        )

        for region_name, region in state.regions.items():
            payload = region.to_dict()
            rect = payload.get("rect", {})
            items = payload.get("items", [])
            confidences = [
                float(item.get("confidence"))
                for item in items
                if item.get("confidence") is not None
            ]
            recognized_count = sum(1 for item in items if item.get("tile_id") or item.get("button"))
            confidence_min = min(confidences) if confidences else None
            cur.execute(
                """
                INSERT INTO region_observations
                (frame_index, region_name, kind, x, y, w, h, item_count,
                 recognized_count, confidence_min, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    frame_index,
                    region_name,
                    payload.get("kind"),
                    rect.get("x"),
                    rect.get("y"),
                    rect.get("w"),
                    rect.get("h"),
                    len(items),
                    recognized_count,
                    confidence_min,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            seat = region_name.split(".", 1)[1] if "." in region_name else region_name
            for item in items:
                if "tile_id" not in item:
                    continue
                item_rect = item.get("rect", {})
                cur.execute(
                    """
                    INSERT INTO tile_observations
                    (frame_index, region_name, seat, slot_index, tile_id, confidence,
                     method, x, y, w, h)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        frame_index,
                        region_name,
                        seat,
                        item.get("slot"),
                        item.get("tile_id"),
                        item.get("confidence"),
                        item.get("method"),
                        item_rect.get("x"),
                        item_rect.get("y"),
                        item_rect.get("w"),
                        item_rect.get("h"),
                    ),
                )

        for event in state.events:
            cur.execute(
                """
                INSERT INTO events (frame_index, timestamp_ms, event_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    frame_index,
                    ts,
                    event,
                    json.dumps({
                        "event": event,
                        "phase": state.game_phase,
                        "remaining_tiles": state.remaining_tiles,
                        "decision_prompt": state.decision_prompt,
                    }, ensure_ascii=False),
                ),
            )

        current = self._build_current_state_payload(state_dict)
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
                frame_index,
                ts,
                state.game_phase,
                state.remaining_tiles,
                current["dealer_seat"],
                json.dumps(current["self_hand"], ensure_ascii=False),
                json.dumps(current["discards"], ensure_ascii=False),
                json.dumps(current["melds"], ensure_ascii=False),
                json.dumps(current["opponents"], ensure_ascii=False),
                json.dumps(state.decision_prompt, ensure_ascii=False),
                json.dumps(current["visible_tile_counts"], ensure_ascii=False),
                json.dumps(current["unknown_summary"], ensure_ascii=False),
                json.dumps(state_dict, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        self._db.commit()

    def _build_current_state_payload(self, state_dict: dict) -> dict:
        self_state = state_dict.get("self", {})
        opponents = state_dict.get("opp", [])
        discards = {
            "self": self_state.get("discards", []),
            "right": opponents[0].get("discards", []) if len(opponents) > 0 else [],
            "across": opponents[1].get("discards", []) if len(opponents) > 1 else [],
            "left": opponents[2].get("discards", []) if len(opponents) > 2 else [],
        }
        melds = {
            "self": self_state.get("melds", []),
            "right": opponents[0].get("melds", []) if len(opponents) > 0 else [],
            "across": opponents[1].get("melds", []) if len(opponents) > 1 else [],
            "left": opponents[2].get("melds", []) if len(opponents) > 2 else [],
        }
        visible_tile_counts: dict[str, int] = {}
        unknown_count = 0
        for tile in self_state.get("hand", []):
            tid = tile.get("t")
            if tid:
                visible_tile_counts[tid] = visible_tile_counts.get(tid, 0) + 1
            else:
                unknown_count += 1
        for seat_tiles in discards.values():
            for tile in seat_tiles:
                tid = tile.get("t")
                if tid:
                    visible_tile_counts[tid] = visible_tile_counts.get(tid, 0) + 1
                else:
                    unknown_count += 1
        for seat_melds in melds.values():
            for meld in seat_melds:
                for tile in meld.get("tiles", []):
                    tid = tile.get("t")
                    if tid:
                        visible_tile_counts[tid] = visible_tile_counts.get(tid, 0) + 1
                    else:
                        unknown_count += 1
        return {
            "dealer_seat": None,
            "self_hand": self_state.get("hand", []),
            "discards": discards,
            "melds": melds,
            "opponents": opponents,
            "visible_tile_counts": visible_tile_counts,
            "unknown_summary": {
                "unknown_visible_tiles": unknown_count,
                "remaining_tiles": state_dict.get("rt"),
                "note": "opponent concealed hands are not visually known yet",
            },
        }

    # 牌ID → 中文名映射
    TILE_NAMES = {
        "1m": "一万", "2m": "二万", "3m": "三万", "4m": "四万", "5m": "五万",
        "6m": "六万", "7m": "七万", "8m": "八万", "9m": "九万",
        "1p": "一筒", "2p": "二筒", "3p": "三筒", "4p": "四筒", "5p": "五筒",
        "6p": "六筒", "7p": "七筒", "8p": "八筒", "9p": "九筒",
        "1s": "一条", "2s": "二条", "3s": "三条", "4s": "四条", "5s": "五条",
        "6s": "六条", "7s": "七条", "8s": "八条", "9s": "九条",
        "1z": "东", "2z": "南", "3z": "西", "4z": "北",
        "5z": "中", "6z": "发", "7z": "白",
    }

    def save_keyframe(self, frame_index: int, image_bytes: bytes,
                      hand_info: list[dict] | None = None) -> str | None:
        """保存关键帧截图 + 手牌识别文本到 session 的 keyframes/ 目录。

        Args:
            frame_index: 帧序号
            image_bytes: PNG 图片字节
            hand_info: 手牌识别结果列表，每项 {"tile_id": "1m", "confidence": 0.85, "method": "structural"}
        """
        if not hasattr(self, '_keyframes_dir'):
            return None
        path = os.path.join(self._keyframes_dir, f"frame_{frame_index:04d}.png")
        try:
            with open(path, "wb") as f:
                f.write(image_bytes)
            self._keyframe_count += 1

            # 保存配套手牌识别文本
            if hand_info is not None:
                txt_path = os.path.join(self._keyframes_dir, f"frame_{frame_index:04d}.txt")
                lines = []
                lines.append(f"关键帧: frame_{frame_index:04d}")
                lines.append(f"手牌数: {len(hand_info)}")
                lines.append("")

                # 逐牌列出
                for i, item in enumerate(hand_info):
                    tid = item.get("tile_id") or "未识别"
                    conf = item.get("confidence", 0)
                    method = item.get("method", "")
                    cn_name = self.TILE_NAMES.get(tid, tid)
                    if tid != "未识别":
                        prefix = "低可信候选 " if method == "low_conf_guess" else ""
                        lines.append(f"  [{i+1:2d}] {prefix}{cn_name} ({tid})  置信度={conf:.3f}  方法={method}")
                    else:
                        lines.append(f"  [{i+1:2d}] ???          置信度={conf:.3f}")

                # 汇总行：纯中文手牌序列
                hand_str = " ".join(
                    self.TILE_NAMES.get(item.get("tile_id", ""), "?") if item.get("tile_id") else "?"
                    for item in hand_info
                )
                lines.append("")
                lines.append(f"手牌序列: {hand_str}")

                # 统计
                recognized = sum(
                    1 for item in hand_info
                    if item.get("tile_id") and item.get("method") != "low_conf_guess"
                )
                low_conf = sum(1 for item in hand_info if item.get("method") == "low_conf_guess")
                lines.append(f"高可信识别率: {recognized}/{len(hand_info)}")
                if low_conf:
                    lines.append(f"低可信候选: {low_conf}/{len(hand_info)}")

                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

            return path
        except Exception:
            return None

    def save_discard_keyframe(
        self,
        frame_index: int,
        image_bytes: bytes,
        discard_info: list[dict] | None = None,
    ) -> str | None:
        """保存弃牌关键帧截图 + 各家弃牌识别文本到 discard_keyframes/ 目录。

        Args:
            frame_index: 帧序号。
            image_bytes: 已编码的 PNG 字节（复用手牌关键帧的同一份截图）。
            discard_info: 列表，每项为一家玩家的弃牌信息：
                {
                    "player_idx": int,       # 0=自家 1=右 2=对家 3=左
                    "seat": str,             # "self"/"right"/"across"/"left"
                    "tiles": [{"tile_id": str | None, "confidence": float}, ...]
                }
        """
        if not hasattr(self, '_discard_keyframes_dir'):
            return None
        path = os.path.join(self._discard_keyframes_dir, f"frame_{frame_index:04d}.png")
        try:
            with open(path, "wb") as f:
                f.write(image_bytes)

            if discard_info is not None:
                txt_path = os.path.join(
                    self._discard_keyframes_dir, f"frame_{frame_index:04d}.txt"
                )
                seat_cn = {"self": "自家", "right": "右家", "across": "对家", "left": "左家"}
                lines = [f"弃牌关键帧: frame_{frame_index:04d}", ""]
                for player in discard_info:
                    seat = player.get("seat", "?")
                    tiles = player.get("tiles", [])
                    tile_str = " ".join(
                        self.TILE_NAMES.get(t.get("tile_id") or "", "?")
                        if t.get("tile_id") else "?"
                        for t in tiles
                    )
                    recognized = sum(1 for t in tiles if t.get("tile_id"))
                    total = len(tiles)
                    lines.append(
                        f"[{seat_cn.get(seat, seat)}] {total}张: "
                        f"{tile_str or '(空)'}  识别率={recognized}/{total}"
                    )
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

            return path
        except Exception:
            return None

    def append_analysis_event(self, event: dict) -> None:
        """将一次 AI 分析事件（手牌+候选+建议）写入 analysis_events.jsonl 和 SQLite。"""
        try:
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            self._analysis_fh.write(line + "\n")
            self._analysis_event_count += 1
            analysis = event.get("analysis", {})
            candidates = analysis.get("candidates", [])
            advice = event.get("advice", {})
            self._db.execute(
                "INSERT INTO analysis_events "
                "(timestamp, trigger, hand_json, candidates_json, advice_json, shanten, strategy_mode, recommended_discard) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.get("timestamp", ""),
                    event.get("trigger", ""),
                    json.dumps(event.get("hand", []), ensure_ascii=False),
                    json.dumps(candidates, ensure_ascii=False),
                    json.dumps(advice, ensure_ascii=False),
                    analysis.get("shanten"),
                    analysis.get("strategy_mode"),
                    advice.get("recommended_discard", ""),
                ),
            )
            self._db.commit()
        except Exception:
            pass

    def flush(self) -> None:
        if hasattr(self, "_write_queue"):
            self._write_queue.join()
        if self._fh and not self._fh.closed:
            self._fh.flush()
        if self._details_fh and not self._details_fh.closed:
            self._details_fh.flush()
        if getattr(self, "_analysis_fh", None) and not self._analysis_fh.closed:
            self._analysis_fh.flush()
        if self._db:
            self._db.commit()

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self.flush()
        self._write_queue.put(None)
        self._write_queue.join()
        if getattr(self, "_writer_thread", None) is not None:
            self._writer_thread.join(timeout=2.0)
        self._closed = True
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()
        if self._details_fh and not self._details_fh.closed:
            self._details_fh.flush()
            self._details_fh.close()
        if getattr(self, "_analysis_fh", None) and not self._analysis_fh.closed:
            self._analysis_fh.flush()
            self._analysis_fh.close()
        if self._db:
            self._db.commit()
            self._db.close()
            self._db = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def frames_path(self) -> str:
        return self._frames_path

    @property
    def frame_details_path(self) -> str:
        return self._frame_details_path

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def keyframes_dir(self) -> str:
        return getattr(self, '_keyframes_dir', '')

    @property
    def discard_keyframes_dir(self) -> str:
        return getattr(self, '_discard_keyframes_dir', '')

    @property
    def keyframe_count(self) -> int:
        return getattr(self, '_keyframe_count', 0)

    @staticmethod
    def list_sessions(output_dir: str) -> list[str]:
        """返回所有 session 目录名，按时间倒序。"""
        if not os.path.isdir(output_dir):
            return []
        entries = [
            d for d in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, d)) and d.startswith("session_")
        ]
        return sorted(entries, reverse=True)

    @staticmethod
    def prune_sessions(output_dir: str, max_sessions: int = 10, keep_session_id: str | None = None) -> list[str]:
        """只保留最新 max_sessions 个 session 目录，删除更旧的目录。"""
        if max_sessions <= 0 or not os.path.isdir(output_dir):
            return []
        sessions: list[tuple[float, str, str]] = []
        for name in os.listdir(output_dir):
            path = os.path.join(output_dir, name)
            if name.startswith("session_") and os.path.isdir(path):
                sessions.append((os.path.getmtime(path), name, path))
        sessions.sort(key=lambda item: (item[0], item[1]), reverse=True)

        kept: set[str] = set()
        for _, name, _ in sessions:
            if len(kept) >= max_sessions:
                break
            kept.add(name)
        if keep_session_id:
            kept.add(keep_session_id)
            while len(kept) > max_sessions:
                for _, name, _ in reversed(sessions):
                    if name in kept and name != keep_session_id:
                        kept.remove(name)
                        break
                else:
                    break

        removed: list[str] = []
        root = os.path.abspath(output_dir)
        for _, name, path in sessions:
            if name in kept:
                continue
            abs_path = os.path.abspath(path)
            if os.path.dirname(abs_path) != root:
                continue
            try:
                shutil.rmtree(abs_path)
                removed.append(name)
            except OSError:
                pass
        return removed
