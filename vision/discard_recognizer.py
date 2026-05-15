from __future__ import annotations
import os
import logging
from typing import TYPE_CHECKING

import cv2
import numpy as np

from vision.discard_tile_cropper import (
    extract_primary_discard_tile,
    prepare_trainable_discard_roi_image,
)
from vision.recognizer import TileRecognizer, MatchResult
from vision.layout import LayoutCalculator, Rect
from vision.capture import ScreenCapture

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mahjongai.discard_recognizer")

_SEAT_NAMES = ["self", "right", "across", "left"]


class DiscardAreaRecognizer:
    """弃牌区域识别器。

    与手牌区域共享模板文件，但使用独立的训练样本目录
    (data/tile_samples_discard_cleaned/)，使两者的 exemplar
    nearest-neighbor 记忆彼此隔离，互不干扰。
    """

    def __init__(self, template_dir: str, threshold: float = 0.60):
        """
        Args:
            template_dir: 与手牌识别器相同的模板目录（共用模板）。
            threshold: 置信度阈值，透传给内部 TileRecognizer。
        """
        self._template_dir = template_dir
        self._threshold = threshold
        # 内部独立的 TileRecognizer 实例
        self._recognizer = TileRecognizer(template_dir, threshold, use_orb=True)
        # TileRecognizer.__init__ 自动加载 tile_samples_cleaned，立即覆盖为弃牌专属目录
        discard_samples = _resolve_discard_samples_dir(template_dir)
        self._discard_samples_dir = discard_samples
        self._recognizer.load_training_samples(discard_samples)
        logger.info(
            "DiscardAreaRecognizer 初始化: template_dir=%s, samples=%s",
            template_dir, discard_samples,
        )

    # ------------------------------------------------------------------ #
    #  公共接口                                                            #
    # ------------------------------------------------------------------ #

    def recognize_player(
        self,
        frame: np.ndarray,
        layout: LayoutCalculator,
        capture: ScreenCapture,
        player_idx: int,
    ) -> tuple[list[MatchResult], list[tuple[int, int, int, int]]]:
        """识别单个玩家的弃牌区域。

        Returns:
            results: 每个格子的 MatchResult，遇到第一个空格后截断。
            slot_rects: 所有查询格子的 (x, y, w, h) 列表（与 results 长度一致）。
        """
        if player_idx == 0:
            region = layout.discard_region(player_idx)
            region_roi = capture.grab_from_frame(frame, region)
            results, slot_rects = self._recognize_self_from_region(region_roi, region)
            if results:
                return results, slot_rects

        discard_slots: list[Rect] = layout.discard_slots(player_idx)
        results: list[MatchResult] = []
        # Allow up to this many leading empty slots before the first tile,
        # so minor coordinate misalignment doesn't prematurely truncate.
        _MAX_LEADING_EMPTY = 3
        leading_empty = 0
        tile_found = False

        for slot in discard_slots:
            roi = capture.grab_from_frame(frame, slot)
            if not self._recognizer.is_probably_tile_roi(roi):
                if not tile_found and leading_empty < _MAX_LEADING_EMPTY:
                    leading_empty += 1
                    continue  # skip leading empties before first tile
                results.append(MatchResult(tile_id=None, confidence=0.0, method="empty_slot"))
                break  # 弃牌连续排列，第一个空格后截断
            tile_found = True
            leading_empty = 0
            ok, clean_roi, _reason = extract_primary_discard_tile(roi)
            results.append(self._recognizer.match_tile(clean_roi if ok else roi))

        slot_rects = [(s.x, s.y, s.w, s.h) for s in discard_slots[: len(results)]]
        return results, slot_rects

    def _recognize_self_from_region(
        self,
        region_roi: np.ndarray,
        region_rect: Rect,
    ) -> tuple[list[MatchResult], list[tuple[int, int, int, int]]]:
        if region_roi is None or region_roi.size == 0 or len(region_roi.shape) != 3:
            return [], []

        h, w = region_roi.shape[:2]
        hsv = cv2.cvtColor(region_roi, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(region_roi, cv2.COLOR_BGR2GRAY)

        white = (
            (hsv[:, :, 2] > 138)
            & (hsv[:, :, 1] < 128)
            & (gray > 108)
        ).astype(np.uint8) * 255
        white = cv2.morphologyEx(
            white, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        )
        band_y1 = max(0, int(h * 0.05))
        band_y2 = min(h, int(h * 0.62))
        band = white[band_y1:band_y2]
        if band.size == 0:
            return [], []

        col_score = cv2.GaussianBlur(
            (band > 0).mean(axis=0).reshape(1, -1).astype(np.float32),
            (1, 5),
            0,
        ).reshape(-1)
        active = col_score > 0.08
        runs: list[tuple[int, int]] = []
        start = None
        for i, flag in enumerate(active):
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                if i - start >= max(30, int(w * 0.03)):
                    runs.append((start, i))
                start = None
        if start is not None and len(active) - start >= max(30, int(w * 0.03)):
            runs.append((start, len(active)))
        if not runs:
            return [], []

        main_left, main_right = max(runs, key=lambda item: item[1] - item[0])
        main_col = col_score[main_left:main_right]
        row_mask = (white[:, main_left:main_right] > 0).mean(axis=1)
        rows = np.where(row_mask > 0.10)[0]
        if len(rows) < 10:
            return [], []
        row_y1 = max(0, int(rows[0]) - max(2, int(h * 0.02)))
        row_y2 = min(h, int(rows[-1]) + 1 + max(2, int(h * 0.02)))
        row_h = max(1, row_y2 - row_y1)

        est_tile_w = max(22.0, row_h * 0.64)
        est_count = max(1, min(14, int(round((main_right - main_left) / est_tile_w))))
        step = (main_right - main_left) / max(1, est_count)
        boundaries = [main_left]
        for i in range(1, est_count):
            target = main_left + i * step
            radius = max(5, int(step * 0.22))
            lo = max(main_left + 4, int(round(target - radius)))
            hi = min(main_right - 4, int(round(target + radius)))
            if hi <= lo:
                boundaries.append(int(round(target)))
                continue
            local = col_score[lo:hi]
            split = lo + int(np.argmin(local))
            boundaries.append(split)
        boundaries.append(main_right)

        results: list[MatchResult] = []
        slot_rects: list[tuple[int, int, int, int]] = []
        for left, right in zip(boundaries, boundaries[1:]):
            bw = right - left
            if bw < max(18, int(w * 0.018)):
                continue
            pad_x = max(2, int(round(bw * 0.06)))
            x1 = max(0, left + pad_x)
            x2 = min(w, right - pad_x)
            y1 = row_y1
            y2 = row_y2
            if x2 <= x1 or y2 <= y1:
                continue
            tile_roi = region_roi[y1:y2, x1:x2]
            if tile_roi.size == 0:
                continue
            ok, clean_roi, _reason = prepare_trainable_discard_roi_image(tile_roi)
            match_roi = clean_roi if ok and clean_roi is not None else tile_roi
            result = self._recognizer.match_tile(match_roi)
            if result.tile_id is None and result.confidence <= 0.0:
                continue
            results.append(result)
            slot_rects.append((region_rect.x + x1, region_rect.y + y1, x2 - x1, y2 - y1))

        return results, slot_rects

    def reload_samples(self) -> int:
        """热重载弃牌训练样本（用户加入新样本后调用）。"""
        loaded = self._recognizer.load_training_samples(self._discard_samples_dir)
        logger.info(
            "DiscardAreaRecognizer 重载样本: %d 张，来自 %s",
            loaded, self._discard_samples_dir,
        )
        return loaded

    @property
    def inner_recognizer(self) -> TileRecognizer:
        """暴露内部 TileRecognizer 供 RoiTrainingDialog 使用。"""
        return self._recognizer

    @property
    def discard_samples_dir(self) -> str:
        return self._discard_samples_dir


# ------------------------------------------------------------------ #
#  模块级工具函数                                                      #
# ------------------------------------------------------------------ #

def _resolve_discard_samples_dir(template_dir: str) -> str:
    """返回弃牌样本目录，兼容开发环境和打包后的 exe。"""
    from utils.paths import data_path
    return data_path(os.path.join("data", "tile_samples_discard_cleaned"))
