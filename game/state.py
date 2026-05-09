from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


# 34种牌的标准ID（万1-9, 筒1-9, 条1-9, 字牌东南西北中发白）
ALL_TILE_IDS: list[str] = (
    [f"{i}m" for i in range(1, 10)]   # 万
    + [f"{i}p" for i in range(1, 10)] # 筒
    + [f"{i}s" for i in range(1, 10)] # 条
    + [f"{i}z" for i in range(1, 8)]  # 字：1z=东 2z=南 3z=西 4z=北 5z=中 6z=发 7z=白
)

# 决策按钮ID
BUTTON_IDS: list[str] = ["碰", "吃", "杠_明", "杠_暗", "杠_补", "胡", "过"]

# 游戏阶段
PHASE_PLAYING = "playing"
PHASE_SHENGJIA = "shengjia"   # 生牌阶段（剩余≤30张，约15对）
PHASE_HUANGPAI = "huangpai"    # 黄牌阶段（剩余≤16张，约8对）
PHASE_LIUJU = "liuju"          # 流局
PHASE_HUPAI = "hupai"          # 胡牌结算


@dataclass
class TileMatch:
    tile_id: Optional[str]   # 如 "1m"，None 表示未识别
    confidence: float         # 匹配置信度 [0, 1]

    def to_dict(self) -> dict:
        return {"t": self.tile_id, "c": round(self.confidence, 3)}


@dataclass
class RegionObservation:
    """单帧某个视觉区域的识别明细，用于流水记录和诊断回放。"""
    name: str
    rect: dict
    kind: str
    items: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rect": self.rect,
            "kind": self.kind,
            "items": self.items,
            "summary": self.summary,
        }


@dataclass
class MeldGroup:
    """一组副露（碰/吃/杠）"""
    meld_type: str             # "chi"/"pon"/"kan_open"/"kan_closed"/"kan_added"
    tiles: list[TileMatch] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": self.meld_type, "tiles": [t.to_dict() for t in self.tiles]}


@dataclass
class PlayerState:
    """自家状态（有完整牌面信息）"""
    hand: list[TileMatch] = field(default_factory=list)       # 当前手牌
    discards: list[TileMatch] = field(default_factory=list)   # 弃牌历史
    melds: list[MeldGroup] = field(default_factory=list)      # 副露列表

    def to_dict(self) -> dict:
        return {
            "hand": [t.to_dict() for t in self.hand],
            "melds": [m.to_dict() for m in self.melds],
            "discards": [t.to_dict() for t in self.discards],
        }


@dataclass
class OpponentState:
    """对手状态（只有背面手牌数 + 可见弃牌/副露）"""
    seat: str                                                   # "right"/"across"/"left"
    tile_count: int = 13                                        # 背面手牌数（推算）
    discards: list[TileMatch] = field(default_factory=list)
    melds: list[MeldGroup] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seat": self.seat,
            "tile_count": self.tile_count,
            "melds": [m.to_dict() for m in self.melds],
            "discards": [t.to_dict() for t in self.discards],
        }


@dataclass
class GameState:
    """单帧完整游戏状态"""
    frame_index: int
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    remaining_tiles: Optional[int] = None

    self_player: PlayerState = field(default_factory=PlayerState)
    opponents: list[OpponentState] = field(default_factory=list)  # [右家, 对家, 左家]

    decision_prompt: list[str] = field(default_factory=list)  # 当前可操作按钮
    game_phase: str = PHASE_PLAYING
    events: list[str] = field(default_factory=list)           # 本帧推断事件
    regions: dict[str, RegionObservation] = field(default_factory=dict)

    raw_confidence_min: float = 1.0   # 本帧最低识别置信度

    # 生牌标记：34维，True 表示该牌本局从未被打出/吃碰杠过
    is_sheng: list[bool] = field(default_factory=lambda: [True] * 34)

    def to_dict(self) -> dict:
        return {
            "fi": self.frame_index,
            "ts": self.timestamp_ms,
            "rt": self.remaining_tiles,
            "phase": self.game_phase,
            "decision": self.decision_prompt,
            "events": self.events,
            "self": self.self_player.to_dict(),
            "opp": [o.to_dict() for o in self.opponents],
            "regions": {name: region.to_dict() for name, region in self.regions.items()},
            "is_sheng": self.is_sheng,
            "dbg": {
                "min_conf": round(self.raw_confidence_min, 3),
                "hand_count": len(self.self_player.hand),
                "meld_count": len(self.self_player.melds),
            },
        }
