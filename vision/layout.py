from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass
class Rect:
    """像素坐标矩形（相对于游戏窗口左上角）。"""
    x: int
    y: int
    w: int
    h: int

    def to_slice(self) -> tuple[slice, slice]:
        """返回 numpy 裁剪切片 (row_slice, col_slice)。"""
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)

    def split_horizontal(self, n: int, gap: int = 0) -> list[Rect]:
        """等分成 n 个横向子区域。"""
        if n <= 0:
            return []
        slot_w = (self.w - gap * (n - 1)) / n
        result = []
        for i in range(n):
            x = self.x + round(i * (slot_w + gap))
            next_x = self.x + round((i + 1) * (slot_w + gap) - gap) if i < n - 1 else self.x + self.w
            result.append(Rect(x=x, y=self.y, w=next_x - x, h=self.h))
        return result

    def split_grid(self, cols: int, rows: int, gap: int = 0) -> list[list[Rect]]:
        """切分成 rows×cols 的网格，返回 [行][列] 的二维列表。"""
        row_rects = Rect(self.x, self.y, self.w, self.h)
        result = []
        slot_h = (self.h - gap * (rows - 1)) / rows
        for r in range(rows):
            y = self.y + round(r * (slot_h + gap))
            next_y = self.y + round((r + 1) * (slot_h + gap) - gap) if r < rows - 1 else self.y + self.h
            row_rect = Rect(self.x, y, self.w, next_y - y)
            result.append(row_rect.split_horizontal(cols, gap))
        return result


class LayoutCalculator:
    """根据 settings.yaml 的 layout 配置，将比例坐标转换为绝对像素 Rect。"""

    def __init__(self, config: dict):
        """
        config: settings.yaml 完整内容（含 game_window 和 layout 节）。
        """
        gw = config.get("game_window", {})
        self._win_x = gw.get("left", 0)
        self._win_y = gw.get("top", 0)
        self._win_w = gw.get("width", 1280)
        self._win_h = gw.get("height", 720)
        self._layout = config.get("layout", {})

    def _scale(self, rx: float, ry: float, rw: float, rh: float) -> Rect:
        """将比例坐标转换为相对于游戏窗口的绝对像素 Rect。"""
        return Rect(
            x=round(rx * self._win_w),
            y=round(ry * self._win_h),
            w=round(rw * self._win_w),
            h=round(rh * self._win_h),
        )

    def hand_region(self, meld_count: int = 0) -> Rect:
        """自家手牌整体区域（随副露数量收缩）。

        当 meld_side == "left" 时，副露在手牌左侧，
        手牌区域向右偏移（x 增大），宽度同步缩减。
        当 meld_side == "right"（默认）时，手牌区域右边界收缩（w 减小）。
        """
        sh = self._layout.get("self_hand", {})
        x = sh.get("x", 0.08)
        y = sh.get("y", 0.80)
        base_w = sh.get("w", 0.72)
        h = sh.get("h", 0.17)
        meld_unit_w = sh.get("meld_unit_w", 0.12)
        meld_side = sh.get("meld_side", "right")

        shrink = meld_count * meld_unit_w
        if meld_side == "left":
            # 副露在左侧：x 向右移动，w 等量缩减
            x = x + shrink
            w = base_w - shrink
        else:
            # 副露在右侧（默认）：w 右边界收缩
            w = base_w - shrink

        # 左右各外扩 pad_x，防止最边缘的牌被裁切
        pad = sh.get("pad_x", 0.03)
        if meld_side == "left":
            # 左侧副露时，只向左扩（不往副露方向扩）
            x = max(0.0, x - pad)
            w = min(1.0 - x, w + pad)
        else:
            x = max(0.0, x - pad)
            w = min(1.0 - x, w + pad * 2)
        return self._scale(x, y, max(w, 0.05), h)

    def hand_slots(self, tile_count: int, meld_count: int = 0) -> list[Rect]:
        """自家手牌每张牌的 Rect 列表。"""
        region = self.hand_region(meld_count)
        return region.split_horizontal(tile_count)

    def meld_slots(self, player: int, meld_index: int, meld_type: str) -> list[Rect]:
        """
        副露牌槽列表。
        player: 0=自家 1=右家 2=对家 3=左家
        meld_index: 从右到左第几组（0起）
        meld_type: "chi"/"pon"/"kan_open"/"kan_closed"/"kan_added"
        """
        m = self._layout.get("meld", {})
        tile_w = m.get("meld_tile_w", 0.035)
        gap = m.get("meld_gap", 0.004)
        n_tiles = 4 if meld_type.startswith("kan") else 3

        if player == 0:
            right_edge = m.get("self_right_edge", 0.92)
            group_w = n_tiles * tile_w + (n_tiles - 1) * gap
            # 第 meld_index 组从右边界向左偏移
            rx = right_edge - (meld_index + 1) * (group_w + gap)
            ry = self._layout.get("self_hand", {}).get("y", 0.80)
            rh = self._layout.get("self_hand", {}).get("h", 0.17)
            region = self._scale(rx, ry, group_w, rh)
            return region.split_horizontal(n_tiles)
        # 对家/左右家副露识别后续再精细化
        return []

    def discard_slots(self, player: int) -> list[Rect]:
        """弃牌堆所有格子的平铺列表（按出牌顺序，从左上到右下）。"""
        dc = self._discard_config(player)
        rx, ry = dc.get("x", 0.28), dc.get("y", 0.58)
        rw, rh = dc.get("w", 0.44), dc.get("h", 0.20)
        cols = dc.get("cols", 6)
        rows = dc.get("rows", 4)
        region = self._scale(rx, ry, rw, rh)
        grid = region.split_grid(cols, rows)
        return [cell for row in grid for cell in row]

    def discard_region(self, player: int) -> Rect:
        dc = self._discard_config(player)
        return self._scale(
            dc.get("x", 0.28),
            dc.get("y", 0.58),
            dc.get("w", 0.44),
            dc.get("h", 0.20),
        )

    def _discard_config(self, player: int) -> dict:
        key = {0: "self", 1: "right", 2: "across", 3: "left"}.get(player, "self")
        return self._layout.get("discard", {}).get(key, {})

    def remaining_tiles_region(self) -> Rect:
        rt = self._layout.get("remaining_tiles", {})
        return self._scale(rt.get("x", 0.46), rt.get("y", 0.44),
                           rt.get("w", 0.08), rt.get("h", 0.08))

    def decision_buttons_region(self) -> Rect:
        db = self._layout.get("decision_buttons", {})
        return self._scale(db.get("x", 0.25), db.get("y", 0.68),
                           db.get("w", 0.50), db.get("h", 0.10))

    def game_overlay_region(self) -> Rect:
        go = self._layout.get("game_overlay", {})
        return self._scale(go.get("x", 0.30), go.get("y", 0.20),
                           go.get("w", 0.40), go.get("h", 0.40))

    def update_window(self, top: int, left: int, width: int, height: int) -> None:
        """更新游戏窗口坐标（区域重新选取后调用）。"""
        self._win_x = left
        self._win_y = top
        self._win_w = width
        self._win_h = height

    @property
    def window_region(self) -> dict:
        """mss 格式的截图区域。"""
        return {
            "top": self._win_y,
            "left": self._win_x,
            "width": self._win_w,
            "height": self._win_h,
        }
