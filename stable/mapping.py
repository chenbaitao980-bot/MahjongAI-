from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import yaml

from game.state import ALL_TILE_IDS
from utils.paths import data_path

# 台州麻将协议的 instance 编码顺序：条→万→筒→字
# 与 ALL_TILE_IDS（万→筒→条）不同，错用会导致所有牌型错位
_GAME_INSTANCE_TILE_IDS: list[str] = (
    [f"{i}s" for i in range(1, 10)]   # 条 (1s-9s)
    + [f"{i}m" for i in range(1, 10)] # 万 (1m-9m)
    + [f"{i}p" for i in range(1, 10)] # 筒 (1p-9p)
    + [f"{i}z" for i in range(1, 8)]  # 字
)


@dataclass
class UnknownMapping:
    raw_key: str
    count: int = 0
    note: str = ""


class MappingStore:
    """Persistent raw-code to MahjongAI tile-id mapping."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_path("data"), "stable_reader", "mappings.yaml")
        self._manual: dict[str, str] = {}
        self._unknowns: dict[str, UnknownMapping] = {}
        self.load()

    def load(self) -> None:
        self._manual.clear()
        if not os.path.isfile(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        mappings = data.get("tile_mappings", {}) if isinstance(data, dict) else {}
        for key, value in mappings.items():
            if str(value) in ALL_TILE_IDS:
                self._manual[str(key)] = str(value)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data: dict[str, Any] = {
            "tile_mappings": dict(sorted(self._manual.items())),
        }
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)

    def resolve_tile(self, raw_key: str) -> str | None:
        raw_key = str(raw_key)
        if raw_key in self._manual:
            return self._manual[raw_key]
        return self._builtin_tile(raw_key)

    def save_tile_mapping(self, raw_key: str, tile_id: str) -> None:
        if tile_id not in ALL_TILE_IDS:
            raise ValueError(f"invalid tile id: {tile_id}")
        self._manual[str(raw_key)] = tile_id
        self._unknowns.pop(str(raw_key), None)
        self.save()

    def note_unknown(self, raw_key: str, note: str = "") -> None:
        raw_key = str(raw_key)
        if self.resolve_tile(raw_key) is not None:
            return
        item = self._unknowns.get(raw_key)
        if item is None:
            item = UnknownMapping(raw_key=raw_key, count=0, note=note)
            self._unknowns[raw_key] = item
        item.count += 1
        if note:
            item.note = note

    def unknowns(self) -> list[UnknownMapping]:
        return sorted(self._unknowns.values(), key=lambda x: (-x.count, x.raw_key))

    def clear_unknowns(self) -> None:
        self._unknowns.clear()

    @staticmethod
    def _builtin_tile(raw_key: str) -> str | None:
        try:
            context, raw_value = raw_key.split(":", 1)
            value = int(raw_value, 16 if raw_value.startswith("0x") else 10)
        except Exception:
            return None

        if context == "linear":
            if 1 <= value <= 9:
                return f"{value}m"
            if 11 <= value <= 19:
                return f"{value - 10}p"
            if 21 <= value <= 29:
                return f"{value - 20}s"
            if 31 <= value <= 37:
                return f"{value - 30}z"
            return None

        if context == "nibble":
            suit = (value >> 4) & 0x0F
            rank = value & 0x0F
            if suit == 0 and 1 <= rank <= 9:
                return f"{rank}m"
            if suit == 1 and 1 <= rank <= 9:
                return f"{rank}p"
            if suit == 2 and 1 <= rank <= 9:
                return f"{rank}s"
            if suit == 3 and 1 <= rank <= 7:
                return f"{rank}z"
            return None

        if context == "stable":
            suit = (value >> 4) & 0x0F
            rank = value & 0x0F
            if suit == 1 and 1 <= rank <= 9:
                return f"{rank}m"
            if suit == 2 and 1 <= rank <= 9:
                return f"{rank}s"
            if suit == 3 and 1 <= rank <= 9:
                return f"{rank}p"
            if suit == 4 and 1 <= rank <= 4:
                return f"{rank}z"
            if suit == 5 and 1 <= rank <= 3:
                return f"{rank + 4}z"
            return None

        if context == "instance":
            if 1 <= value <= len(_GAME_INSTANCE_TILE_IDS) * 4:
                return _GAME_INSTANCE_TILE_IDS[(value - 1) // 4]
            return None

        return None
