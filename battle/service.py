from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import time
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, TYPE_CHECKING

import cv2
import numpy as np

from battle.state import BattleAdvice, BattleState, tile_from_id
from game.state import MeldGroup, TileMatch
from utils.paths import data_path
from vision.hand_region_module import prepare_trainable_hand_roi_image
from vision.hog_classifier import TileHOGClassifier

if TYPE_CHECKING:
    from game.session import GameSession


TAIZHOU_RULES_PROMPT = """你是台州麻将2人对战专家AI，只根据我提供的真实牌局数据给出最优决策。

【台州麻将2人模式核心规则】
1. 共136张牌，2人对局，无花牌。
2. 胡牌结构：1对将 + 4组（面子/刻子），财神（白板7z）为万能牌，可替代任意一张牌，但不能单独作将牌。
3. 计分公式：
   - 赢家得分 = (10 + 基础分) × 2^番数
   - 输家付出 = 基础分 × 2^番数
   - 常用番型加番：清一色+4番，杠上开花+1番，平胡0番（不计基础分），普通胡1番
4. 包牌规则：若某玩家打出的牌让对手接连用该牌碰/杠，或点炮成刻子，该玩家承包全部得分差额。
5. 生牌阶段：剩余牌≤15时进入，此后摸到局内未出现过的牌胡则加1番。此阶段防守权重≥70%。
6. 黄牌：剩余牌≤8时若未有人胡，则流局（平局，不计分）。
7. 能胡不胡：上家打出可胡的牌但选择放弃，则该局后续不得再胡（即使自摸）。
8. 能碰不碰：上家打出可碰的牌但选择放弃，则本轮不能再碰该牌，但下轮重新打出时仍可碰。

【最优策略框架（按优先级排序）】
A. 向听优先：优先计算当前手牌向听数（shanten），向听越少越优先推进。
B. 价值最大化：在听牌时评估待牌张数 × 番型价值，选择期望得分最高的听法。
C. 风险控制：
   - 剩余牌≤30时分析对手已打牌，推断危险区域，主动安全牌池建立。
   - 若对手已出多张某花色，谨慎打同花色牌。
   - 生牌阶段：停止碰/杠，优先打对手已出过的"熟牌"，保留安全牌。
D. 财神运用：财神优先填补高番型（如清一色）的缺口，而非凑将或凑普通顺子。
E. 包牌意识：避免连续打同一类型的牌，防止被对方利用造成包牌损失。

【决策流程】
1. 计算当前向听数和最优听牌方案
2. 判断当前阶段（普通/生牌/黄牌边缘）
3. 评估对手危险度（对手已出牌+碰杠情况）
4. 综合攻守权重输出建议

【输出要求】
只返回以下JSON，不要任何解释：
{
  "recommended_discard": "推荐打出的牌（如5m），自摸时填null",
  "strategy_type": "攻牌或守牌或平衡",
  "reasoning_summary": "简明理由，说明向听数和期望胡法",
  "risk_notes": "风险说明，如对手危险牌、包牌风险（无风险则留空）",
  "forbidden_discards": ["绝对不能打的牌列表，如已听牌不能打的搭子牌"],
  "candidate_actions": ["候选方案1：如打X保清一色", "候选方案2：如打Y换普通胡"]
}
strategy_type 只允许三个值之一：攻牌、守牌、平衡"""


QWEN_VISION_SYSTEM_PROMPT = (
    "You are a JSON-only mahjong tile classifier. "
    "Return exactly one JSON object with key tile. "
    "Valid values are only 1-9m, 1-9p, 1-9s, 1-7z. "
    "SUIT IDENTIFICATION RULES (apply in order): "
    "1. Wan/Characters (Xm): tile shows a black numeral on top and a RED 万/萬 character on the bottom half. "
    "   The red 万/萬 is the definitive marker — if present the suit is always m, never z or anything else. "
    "2. Sou/Bamboo (Xs): tile shows multiple ELONGATED OVAL or CAPSULE shapes (taller than wide, like vertical pills or bamboo sections). "
    "   They are arranged in rows/columns. These ovals are NOT round — they are clearly stretched vertically. "
    "   Count the total number of ovals to get the number. "
    "3. Pin/Circles (Xp): tile shows round CIRCULAR disc patterns (width ≈ height), like coins or bullseyes with concentric rings. "
    "   The circles are clearly round, NOT elongated. "
    "4. Honor (Xz): tile shows a single large Chinese character filling most of the tile: 东(1z) 南(2z) 西(3z) 北(4z) 中(5z) 发(6z) 白(7z). "
    "   No numerals, no 万, no repeating patterns. "
    "CRITICAL: Do NOT confuse elongated ovals (bamboo/s) with round circles (circle/p). "
    "If the shapes are clearly stretched/elongated → s. If the shapes are clearly round → p. "
    "Output JSON only."
)

QWEN_VISION_USER_PROMPT_TEMPLATE = (
    "这是一张台州麻将我方手牌切图，第 {tile_index} 张。"
    "请只输出 JSON，格式固定为 {{\”tile\”: \”1m\”}}。"
    "tile 只允许是 1-9m, 1-9p, 1-9s, 1-7z 之一。"
    "先看牌面下半部分是否有清晰的红色”万/萬”字。"
    "如果有红色”万/萬”字，则这张牌的花色必须是 m，绝不能输出 z。"
    "再根据上半部分黑色数字判断是几万。"
    "只有当整张牌是单个大字，且没有下方红色”万/萬”字时，才可能输出 z。"
    "忽略图片里的非牌面元素，如高亮、边缘阴影、光标、UI 装饰。"
    "本地候选可能是错的，不要被它影响。当前本地候选：{local_guess}。"
    "如果图中上方是黑色数字”三”，下方是红色”万/萬”，答案必须是 {{\”tile\”:\”3m\”}}。"
    "只返回最终 tile，不要解释。"
)

VOLC_VISION_PROMPT_TEMPLATE = (
    "这是一张台州麻将我方手牌切图，第 {tile_index} 张。"
    '请只输出 JSON，格式固定为 {{“tile”: "1m"}}。'
    "tile 只允许是 1-9m, 1-9p, 1-9s, 1-7z 之一。"
    "本地识别候选是 {local_guess}。"
    "规则补充：万牌通常包含上方数字和下方红色“万”字；字牌通常是单个大字，例如东南西北中发白。"
    "如果牌面下方有明显红色“万”字，就不要识别成西、东、南、北、中、发、白。"
    "忽略图片里所有非麻将牌元素，例如鼠标光标、黄色箭头、选中高亮、边缘阴影、UI 图标、背景装饰。"
    "不要把光标、箭头或高亮误判成牌面的笔画。"
    "如果本地识别有误，请直接返回你认为正确的 tile。"
)

VISION_PROVIDERS = {
    "volc": {
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "default_model": "",
    },
    "glm": {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "glm-4.6v-flash",
    },
    "qwen": {
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen-vl-plus-latest",
    },
}

VALID_TILE_IDS = {f"{i}m" for i in range(1, 10)} | {f"{i}p" for i in range(1, 10)} | {f"{i}s" for i in range(1, 10)} | {f"{i}z" for i in range(1, 8)}
HONOR_TILE_ALIASES = {
    "east": "1z",
    "dong": "1z",
    "东": "1z",
    "south": "2z",
    "nan": "2z",
    "南": "2z",
    "west": "3z",
    "xi": "3z",
    "西": "3z",
    "north": "4z",
    "bei": "4z",
    "北": "4z",
    "red": "5z",
    "zhong": "5z",
    "中": "5z",
    "green": "6z",
    "fa": "6z",
    "发": "6z",
    "發": "6z",
    "white": "7z",
    "bai": "7z",
    "白": "7z",
}


class BattleService:
    def __init__(self, capture, layout, hand_region, tile_recognizer, config: dict):
        self._capture = capture
        self._layout = layout
        self._hand_region = hand_region
        self._tile_recognizer = tile_recognizer
        self._config = config
        self._picture_log_lock = threading.Lock()
        self._json_log_lock = threading.Lock()
        self._session: "GameSession | None" = None
        self._last_hand_strip: np.ndarray | None = None
        self._last_match_rois: list[np.ndarray] = []
        self._last_meld_rois: list[np.ndarray] = []   # flat list: meld0_tile0, meld0_tile1, ...
        self._last_capture_debug: dict[str, Any] = {}

    def analyze_opening(self, state: BattleState) -> tuple[BattleState, BattleAdvice]:
        return self._analyze(state, "start")

    def analyze_after_action(self, state: BattleState, trigger_reason: str) -> tuple[BattleState, BattleAdvice]:
        return self._analyze(state, trigger_reason)

    def set_session(self, session: "GameSession | None") -> None:
        self._session = session

    def capture_self_hand_local(self, state: BattleState) -> tuple[list[TileMatch], str]:
        self._refresh_local_recognizer_from_disk()
        _hand_strip, rois = self._capture_hand_rois(state)
        self._last_hand_strip = _hand_strip
        match_rois = [self._prepare_roi_for_local_match(roi) for roi in rois]
        local_tiles = [self._tile_recognizer.match_tile(roi) for roi in match_rois]
        tiles = []
        for match in local_tiles:
            if match.tile_id:
                tm = tile_from_id(match.tile_id)
                tm.confidence = match.confidence
                tiles.append(tm)
        if not tiles:
            raise RuntimeError("本地识别未得到有效手牌结果，请先完善牌面样本。")
        self._last_match_rois = list(match_rois)
        self._persist_local_tile_samples(
            hand_strip=_hand_strip,
            rois=match_rois,
            matches=local_tiles,
        )
        self._persist_capture_debug(
            provider="local",
            model="hog",
            hand_strip=_hand_strip,
            raw_hand_rois=rois,
            prepared_hand_rois=match_rois,
            hand_matches=local_tiles,
        )
        return tiles, "local"

    def capture_self_hand_with_vision(self, state: BattleState) -> tuple[list[TileMatch], str]:
        self._refresh_local_recognizer_from_disk()
        configured_provider = self._get_configured_vision_provider()
        provider = self._get_vision_provider()
        provider_key = self._get_vision_api_key(provider)
        if not provider_key:
            raise RuntimeError(f"{provider} 图片模型 API Key 未配置，无法开启 AI 识别。")

        hand_strip, rois = self._capture_hand_rois(state)
        self._last_hand_strip = hand_strip
        match_rois = [self._prepare_roi_for_local_match(roi) for roi in rois]
        local_tiles = [self._tile_recognizer.match_tile(roi) for roi in match_rois]
        local_ids = [match.tile_id or "" for match in local_tiles]
        self._persist_capture_debug(
            provider=provider,
            model="hog",
            hand_strip=hand_strip,
            raw_hand_rois=rois,
            prepared_hand_rois=match_rois,
            hand_matches=local_tiles,
        )
        model = self._get_vision_model(provider)
        endpoint = self._get_vision_endpoint(provider)
        if provider == "volc" and not model:
            raise RuntimeError("火山方舟未配置推理接入点 ID。请在 API 设置里填写火山接入点 ID（通常形如 ep-...）。")
        vision_ids = self._recognize_hand_with_vision(
            provider=provider,
            api_key=provider_key,
            model=model,
            endpoint=endpoint,
            hand_strip=hand_strip,
            rois=rois,
            local_matches=local_tiles,
            local_guess=local_ids,
        )
        if not vision_ids:
            raise RuntimeError(f"{provider} 图片模型未返回可用的手牌结果。")

        source = f"vision:auto->{provider}" if configured_provider == "auto" else f"vision:{provider}"
        return [tile_from_id(tile_id) for tile_id in vision_ids], source

    def capture_self_hand(self, state: BattleState) -> tuple[list[TileMatch], str]:
        if state.ai_recognition_enabled:
            return self.capture_self_hand_with_vision(state)
        return self.capture_self_hand_local(state)

    def persist_round_event(self, state: BattleState, event_type: str, detail: dict | None = None) -> None:
        payload = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "detail": detail or {},
            "state": state.to_payload(),
        }
        self._write_capped_json("requestdeepseek", payload)

    def _capture_hand_rois(self, state: BattleState):
        frame = self._capture.grab()
        full_hand_rect = self._layout.hand_region(0)
        full_hand_strip = self._capture.grab_from_frame(frame, full_hand_rect)
        full_tile_layout = self._extract_tile_layout(full_hand_strip)
        detected_melds, meld_debug = self._detect_self_melds(frame, strip=full_hand_strip, tile_layout=full_tile_layout)
        debug: dict[str, Any] = {
            "capture_path": "layout-fallback",
            "full_strip_shape": self._image_shape_list(full_hand_strip),
            "split_runs_count": len(full_tile_layout[0]) if full_tile_layout else 0,
            "split_runs": [list(run) for run in full_tile_layout[0]] if full_tile_layout else [],
            "tile_row_bounds": [full_tile_layout[1], full_tile_layout[2]] if full_tile_layout else [],
            "meld_debug": meld_debug,
        }
        # Refresh self_melds unless the user has manually corrected/locked them.
        # Auto-unlock when detection returns empty: the round ended or melds are gone,
        # so the locked correction is now stale and would cause wrong hand-region geometry.
        if not detected_melds and state.self_melds_locked:
            state.self_melds = []
            state.self_melds_locked = False
        elif not state.self_melds_locked:
            state.self_melds = detected_melds
        if detected_melds and not state.self_melds_locked:
            dynamic_capture = self._capture_hand_rois_from_full_strip(
                full_hand_strip,
                full_tile_layout,
                len(detected_melds) * 3,
            )
            if dynamic_capture is not None:
                hand_strip, rois = dynamic_capture
                debug["capture_path"] = "dynamic-full-strip"
                debug["hand_strip_shape"] = self._image_shape_list(hand_strip)
                debug["hand_roi_count"] = len(rois)
                debug["expected_hand_counts"] = sorted(self._expected_visible_hand_counts(len(detected_melds) * 3))
                self._last_capture_debug = debug
                return hand_strip, rois
            if not state.self_melds_locked:
                state.self_melds = []
            debug["capture_path"] = "meld-rejected-fallback"
            debug["fallback_reason"] = "dynamic_full_strip_invalid"
        meld_groups = len(state.self_melds)
        meld_tiles = meld_groups * 3
        hand_rect = self._layout.hand_region(meld_groups)
        hand_strip = self._capture.grab_from_frame(frame, hand_rect)

        rois = self._segment_visible_tiles_uniform(hand_strip, meld_tiles)
        if rois:
            debug["capture_path"] = "uniform-segmentation"
            debug["hand_strip_shape"] = self._image_shape_list(hand_strip)
            debug["hand_roi_count"] = len(rois)
            debug["expected_hand_counts"] = sorted(self._expected_visible_hand_counts(meld_tiles))
            self._last_capture_debug = debug
            return hand_strip, rois

        rois, slots, selected_expected = self._segment_hand_strip_with_expected_counts(
            hand_strip,
            sorted(self._expected_visible_hand_counts(meld_tiles), reverse=True),
        )
        if not rois:
            debug["capture_path"] = "segmentation-failed"
            debug["hand_strip_shape"] = self._image_shape_list(hand_strip)
            debug["expected_hand_counts"] = sorted(self._expected_visible_hand_counts(meld_tiles))
            self._last_capture_debug = debug
        if not rois:
            raise RuntimeError("未能从当前画面切出我方手牌区域。")
        debug["capture_path"] = "layout-fallback"
        debug["hand_strip_shape"] = self._image_shape_list(hand_strip)
        debug["hand_roi_count"] = len(rois)
        debug["selected_expected_count"] = selected_expected
        debug["slot_count"] = len(slots)
        debug["expected_hand_counts"] = sorted(self._expected_visible_hand_counts(meld_tiles))
        self._last_capture_debug = debug
        return hand_strip, rois

    def _segment_visible_tiles_uniform(self, strip, meld_tiles: int) -> list[np.ndarray]:
        tile_layout = self._extract_tile_layout(strip)
        if tile_layout is None:
            return []

        split_runs, y1, y2 = tile_layout
        if len(split_runs) < meld_tiles + 8:
            return []

        h, w = strip.shape[:2]
        rois: list[np.ndarray] = []
        for index, (left, right) in enumerate(split_runs):
            if index < meld_tiles:
                continue
            pad_x = max(1, min(4, int((right - left) * 0.04)))
            x1 = max(0, left + pad_x)
            x2 = min(w, right - pad_x)
            if x2 <= x1:
                continue
            roi = strip[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            rois.append(roi)

        min_expected = max(1, 13 - meld_tiles)
        max_expected = max(1, 14 - meld_tiles)
        if min_expected <= len(rois) <= max_expected:
            return rois
        return []

    def _capture_hand_rois_from_full_strip(
        self,
        full_strip,
        tile_layout: tuple[list[tuple[int, int]], int, int] | None,
        meld_tiles: int,
    ) -> tuple[np.ndarray, list[np.ndarray]] | None:
        if full_strip is None or full_strip.size == 0 or tile_layout is None or meld_tiles <= 0:
            return None

        split_runs, y1, y2 = tile_layout
        if len(split_runs) <= meld_tiles:
            return None

        hand_runs = split_runs[meld_tiles:]
        if not hand_runs:
            return None

        left_boundary = max(0, hand_runs[0][0] - max(2, int((hand_runs[0][1] - hand_runs[0][0]) * 0.08)))
        hand_strip = full_strip[:, left_boundary:]
        if hand_strip.size == 0:
            return None

        adjusted_runs = [(left - left_boundary, right - left_boundary) for left, right in hand_runs]
        rois: list[np.ndarray] = []
        h, w = hand_strip.shape[:2]
        for left, right in adjusted_runs:
            pad_x = max(1, min(4, int((right - left) * 0.04)))
            x1 = max(0, left + pad_x)
            x2 = min(w, right - pad_x)
            if x2 <= x1:
                continue
            roi = hand_strip[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            rois.append(roi)

        if len(rois) in self._expected_visible_hand_counts(meld_tiles):
            return hand_strip, rois
        fallback_rois, _slots, _selected = self._segment_hand_strip_with_expected_counts(
            hand_strip,
            sorted(self._expected_visible_hand_counts(meld_tiles), reverse=True),
        )
        if fallback_rois:
            return hand_strip, fallback_rois
        return None

    def _extract_tile_layout(self, strip) -> tuple[list[tuple[int, int]], int, int] | None:
        if strip is None or strip.size == 0 or len(strip.shape) != 3:
            return None

        h, w = strip.shape[:2]
        if h < 60 or w < 200:
            return None

        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        band_top = max(0, int(h * 0.08))
        band_bottom = min(h, int(h * 0.98))
        band = hsv[band_top:band_bottom]
        if band.size == 0:
            return None

        white = ((band[:, :, 2] > 145) & (band[:, :, 1] < 150)).astype(np.uint8)
        col_strength = cv2.GaussianBlur(white.mean(axis=0).reshape(1, -1).astype(np.float32), (1, 5), 0).reshape(-1)
        active = col_strength > 0.14

        runs: list[tuple[int, int]] = []
        start: int | None = None
        min_run_width = max(24, int(w * 0.015))
        for idx, value in enumerate(active):
            if value and start is None:
                start = idx
            elif not value and start is not None:
                if idx - start >= min_run_width:
                    runs.append((start, idx))
                start = None
        if start is not None and len(active) - start >= min_run_width:
            runs.append((start, len(active)))
        if not runs:
            return None

        widths = [end - begin for begin, end in runs]
        base_width = float(np.median(widths))
        if base_width <= 0:
            return None

        split_runs: list[tuple[int, int]] = []
        for begin, end in runs:
            run_width = end - begin
            split_count = 1
            if run_width > base_width * 1.35:
                split_count = max(1, min(4, int(round(run_width / base_width))))
            sub_width = run_width / split_count
            for offset in range(split_count):
                left = int(round(begin + offset * sub_width))
                right = int(round(begin + (offset + 1) * sub_width))
                if right - left >= max(22, int(base_width * 0.5)):
                    split_runs.append((left, right))
        if not split_runs:
            return None

        left_bound = split_runs[0][0]
        right_bound = split_runs[-1][1]
        row_strength = white[:, left_bound:right_bound].mean(axis=1)
        active_rows = np.where(row_strength > 0.08)[0]
        if len(active_rows) < 8:
            return None

        y1 = max(0, band_top + int(active_rows[0]) - int(h * 0.06))
        y2 = min(h, band_top + int(active_rows[-1]) + 1 + int(h * 0.05))
        return split_runs, y1, y2

    def _detect_self_melds(
        self,
        frame: np.ndarray,
        strip=None,
        tile_layout: tuple[list[tuple[int, int]], int, int] | None = None,
    ) -> tuple[list[MeldGroup], dict[str, Any]]:
        sh = self._layout._layout.get("self_hand", {})
        if str(sh.get("meld_side", "right")).lower() != "left":
            return [], {"reason": "meld_side_not_left"}

        if strip is None:
            full_region = self._layout.hand_region(0)
            strip = self._capture.grab_from_frame(frame, full_region)
        if tile_layout is None:
            tile_layout = self._extract_tile_layout(strip)
        if tile_layout is None:
            return [], {"reason": "no_tile_layout"}

        split_runs, y1, y2 = tile_layout
        candidate = self._detect_left_meld_candidate(split_runs)
        debug: dict[str, Any] = {
            "split_runs_count": len(split_runs),
            "split_runs": [list(run) for run in split_runs],
            "row_bounds": [y1, y2],
            "candidate": candidate,
        }
        if not candidate:
            debug["reason"] = "no_candidate"
            return [], debug
        meld_tile_count = int(candidate["meld_tile_count"])
        if not self._is_reliable_meld_candidate(split_runs, candidate):
            debug["reason"] = "candidate_failed_structure"
            return [], debug

        melds: list[MeldGroup] = []
        current_tiles: list[TileMatch] = []
        meld_matches: list[dict[str, Any]] = []
        raw_meld_rois: list[np.ndarray] = []
        prepared_meld_rois: list[np.ndarray] = []
        for left, right in split_runs[:meld_tile_count]:
            pad_x = max(1, min(4, int((right - left) * 0.04)))
            x1 = max(0, left + pad_x)
            x2 = min(strip.shape[1], right - pad_x)
            if x2 <= x1:
                continue
            roi = strip[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            prepared_roi = self._prepare_roi_for_local_match(roi)
            match = self._tile_recognizer.match_tile(prepared_roi)
            raw_meld_rois.append(roi)
            prepared_meld_rois.append(prepared_roi)
            current_tiles.append(
                TileMatch(
                    tile_id=self._normalize_tile_id(match.tile_id) or None,
                    confidence=float(match.confidence or 0.0),
                )
            )
            meld_matches.append(
                {
                    "tile_id": self._normalize_tile_id(match.tile_id) or "",
                    "confidence": round(float(match.confidence or 0.0), 4),
                    "raw_shape": self._image_shape_list(roi),
                    "prepared_shape": self._image_shape_list(prepared_roi),
                }
            )
            if len(current_tiles) == 3:
                melds.append(
                    MeldGroup(
                        meld_type=self._infer_meld_type([tile.tile_id or "" for tile in current_tiles]),
                        tiles=current_tiles.copy(),
                    )
                )
                current_tiles.clear()

        avg_conf = float(np.mean([tile.confidence for meld in melds for tile in meld.tiles])) if melds else 0.0
        debug["avg_confidence"] = round(avg_conf, 4)
        debug["meld_matches"] = meld_matches
        debug["raw_meld_rois"] = raw_meld_rois
        debug["prepared_meld_rois"] = prepared_meld_rois
        expected_groups = int(candidate["meld_groups"])
        if len(melds) != expected_groups:
            debug["reason"] = "group_count_mismatch"
            return [], debug
        if any(not tile.tile_id for meld in melds for tile in meld.tiles):
            debug["reason"] = "empty_tile_id"
            return [], debug
        if avg_conf < 0.78:
            debug["reason"] = "low_confidence"
            return [], debug
        debug["reason"] = "accepted"
        self._last_meld_rois = list(prepared_meld_rois)
        return melds, debug

    def _detect_left_meld_candidate(self, split_runs: list[tuple[int, int]]) -> dict[str, Any] | None:
        if len(split_runs) < 6:
            return None
        widths = [right - left for left, right in split_runs]
        if not widths:
            return None
        base_width = float(np.median(widths))
        if base_width <= 0:
            return None
        gap_threshold = max(10.0, base_width * 0.25)
        best_candidate: dict[str, Any] | None = None
        best_score = float("-inf")
        for meld_groups in range(1, min(4, len(split_runs) // 3) + 1):
            meld_tile_count = meld_groups * 3
            if len(split_runs) <= meld_tile_count:
                break
            remaining_tiles = len(split_runs) - meld_tile_count
            expected_hand_counts = self._expected_visible_hand_counts(meld_tile_count)
            if remaining_tiles not in expected_hand_counts:
                continue
            gap = split_runs[meld_tile_count][0] - split_runs[meld_tile_count - 1][1]
            if gap < gap_threshold:
                continue
            left_widths = widths[:meld_tile_count]
            width_ratio = (max(left_widths) / max(1.0, min(left_widths))) if left_widths else 999.0
            inside_gaps = [
                split_runs[idx + 1][0] - split_runs[idx][1]
                for idx in range(max(0, meld_tile_count - 1))
            ]
            max_internal_gap = max(inside_gaps) if inside_gaps else 0.0
            score = (meld_groups * 1000.0) + gap - (width_ratio * 10.0) - max_internal_gap
            candidate = {
                "meld_groups": meld_groups,
                "meld_tile_count": meld_tile_count,
                "remaining_tiles": remaining_tiles,
                "expected_hand_counts": sorted(expected_hand_counts),
                "gap": round(float(gap), 2),
                "gap_threshold": round(float(gap_threshold), 2),
                "base_width": round(float(base_width), 2),
                "left_widths": [int(value) for value in left_widths],
                "width_ratio": round(float(width_ratio), 4),
                "inside_gaps": [int(value) for value in inside_gaps],
                "max_internal_gap": round(float(max_internal_gap), 2),
            }
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate

    def _is_reliable_meld_candidate(self, split_runs: list[tuple[int, int]], candidate: dict[str, Any]) -> bool:
        meld_tile_count = int(candidate.get("meld_tile_count") or 0)
        if meld_tile_count <= 0 or len(split_runs) <= meld_tile_count:
            return False
        width_ratio = float(candidate.get("width_ratio") or 0.0)
        if width_ratio > 1.7:
            return False
        gap = float(candidate.get("gap") or 0.0)
        max_internal_gap = float(candidate.get("max_internal_gap") or 0.0)
        if gap <= max_internal_gap * 1.1:
            return False
        left_widths = [float(value) for value in candidate.get("left_widths", [])]
        if not left_widths:
            return False
        base_width = float(candidate.get("base_width") or 0.0)
        if base_width <= 0:
            return False
        if any(abs(width - base_width) > base_width * 0.65 for width in left_widths):
            return False
        remaining_tiles = len(split_runs) - meld_tile_count
        return remaining_tiles in self._expected_visible_hand_counts(meld_tile_count)

    def _infer_meld_type(self, tile_ids: list[str]) -> str:
        ids = [tile_id for tile_id in tile_ids if tile_id]
        if len(ids) < 3:
            return "auto"
        if len(set(ids)) == 1:
            return "pon"
        families = {self._tile_family(tile_id) for tile_id in ids}
        if len(families) == 1 and families != {"z"}:
            try:
                numbers = sorted(int(tile_id[0]) for tile_id in ids)
            except ValueError:
                return "auto"
            if numbers == list(range(numbers[0], numbers[0] + len(numbers))):
                return "chi"
        return "auto"

    def _analyze(self, state: BattleState, trigger_reason: str) -> tuple[BattleState, BattleAdvice]:
        state.mark_analysis(trigger_reason)
        recognition_started_at = time.perf_counter()
        hand_tiles, source = self.capture_self_hand(state)
        state.last_recognition_duration_ms = max(
            1,
            int((time.perf_counter() - recognition_started_at) * 1000),
        )
        state.self_hand = hand_tiles
        state.recognition_source = source

        payload = state.to_payload()
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        advice_started_at = time.perf_counter()
        raw_text = ""
        advice_error = ""
        advice = BattleAdvice()
        if state.deepseek_enabled:
            try:
                raw_text = self._call_deepseek(payload_json, trigger_reason)
                advice_data = self._extract_json_object(raw_text)
                advice = BattleAdvice(
                    recommended_discard=str(advice_data.get("recommended_discard") or ""),
                    strategy_type=str(advice_data.get("strategy_type") or ""),
                    reasoning_summary=str(advice_data.get("reasoning_summary") or ""),
                    risk_notes=str(advice_data.get("risk_notes") or ""),
                    forbidden_discards=[str(x) for x in advice_data.get("forbidden_discards", []) if str(x).strip()],
                    candidate_actions=[str(item) for item in advice_data.get("candidate_actions", []) if str(item).strip()],
                    raw_response=raw_text,
                )
            except Exception as exc:
                advice_error = str(exc)
                advice = BattleAdvice(
                    reasoning_summary="手牌识别已完成，但 AI 建议解析失败。",
                    risk_notes=advice_error,
                    raw_response=raw_text,
                )
            finally:
                state.last_advice_duration_ms = max(
                    1,
                    int((time.perf_counter() - advice_started_at) * 1000),
                )
        else:
            state.last_advice_duration_ms = 0
        state.last_analysis_duration_ms = state.last_recognition_duration_ms + state.last_advice_duration_ms
        if advice_error:
            state.append_operation(
                "advice_failed",
                {
                    "error": advice_error,
                    "raw_response": raw_text[:500],
                },
            )
        # 持久化到 session（如已设置）
        if self._session is not None:
            try:
                self._session.append_frame(state)
                if self._last_hand_strip is not None:
                    _, encoded = cv2.imencode(".png", self._last_hand_strip)
                    if encoded is not None:
                        hand_info = [
                            {
                                "tile_id": getattr(t, "tile_id", ""),
                                "confidence": getattr(t, "confidence", 0.0),
                                "method": getattr(t, "method", "unknown"),
                            }
                            for t in state.self_hand
                        ]
                        self._session.save_keyframe(
                            frame_index=self._session.frame_count,
                            image_bytes=encoded.tobytes(),
                            hand_info=hand_info,
                        )
            except Exception:
                pass  # 持久化失败不影响分析主流程
        return state, advice

    def _persist_local_tile_samples(
        self,
        hand_strip,
        rois: list[np.ndarray],
        matches: list[TileMatch],
    ) -> None:
        local_guess = [match.tile_id or "" for match in matches]
        self._persist_picture_request(
            event_type="picture_hand_summary",
            provider="local",
            model="hog",
            image=hand_strip,
            local_guess=local_guess,
            response_text=json.dumps({"tiles": local_guess}, ensure_ascii=False),
            extra={
                "tile_count": len(rois),
                "kind": "hand_summary",
                "request_mode": "local",
            },
        )
        for index, roi in enumerate(rois):
            match = matches[index] if index < len(matches) else None
            tile_id = match.tile_id if match else ""
            confidence = float(getattr(match, "confidence", 0.0) or 0.0)
            self._persist_picture_request(
                event_type="picture_tile_response",
                provider="local",
                model="hog",
                image=roi,
                local_guess=[tile_id] if tile_id else [],
                response_text=json.dumps({"tile": tile_id}, ensure_ascii=False),
                extra={
                    "tile_index": index + 1,
                    "kind": "tile_response",
                    "local_confidence": round(confidence, 4),
                    "source": "local_capture",
                },
            )

    def _call_deepseek(self, payload_json: str, trigger_reason: str) -> str:
        api_key = self._config.get("deepseek", {}).get("api_key", "").strip()
        if not api_key:
            raise RuntimeError("DeepSeek API Key 未配置，请先在 API 设置里填写。")

        model = self._config.get("deepseek", {}).get("model", "deepseek-chat").strip() or "deepseek-chat"
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": TAIZHOU_RULES_PROMPT},
                {"role": "user", "content": payload_json},
            ],
        }

        error_message = ""
        raw_text = ""
        try:
            response = self._http_post_json(
                url="https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                body=body,
            )
            raw_text = response["choices"][0]["message"]["content"]
            return raw_text
        except (KeyError, IndexError, TypeError) as exc:
            error_message = f"DeepSeek 返回结构无法解析: {exc}"
            raise RuntimeError(error_message) from exc
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            self._persist_deepseek_request(
                trigger_reason=trigger_reason,
                model=model,
                payload=json.loads(payload_json),
                response_text=raw_text,
                error_message=error_message,
            )

    def _recognize_hand_with_vision(
        self,
        provider: str,
        api_key: str,
        model: str,
        endpoint: str,
        hand_strip,
        rois: list,
        local_matches: list,
        local_guess: list[str],
    ) -> list[str]:
        started_at = time.perf_counter()
        max_workers = min(10, max(1, len(rois)))
        self._persist_picture_request(
            event_type="picture_hand_region",
            provider=provider,
            model=model,
            image=hand_strip,
            local_guess=local_guess,
            response_text="",
            extra={
                "tile_count": len(rois),
                "kind": "hand_region",
                "request_mode": "parallel",
                "max_workers": max_workers,
            },
        )

        # 预过滤：剔除扣牌（背面朝上），它们不是有效手牌
        visible_rois: list = []
        visible_local_matches: list = []
        visible_local_guess: list[str] = []
        for i, roi in enumerate(rois):
            if self._is_face_down_tile(roi):
                continue
            visible_rois.append(roi)
            visible_local_matches.append(local_matches[i] if i < len(local_matches) else None)
            visible_local_guess.append(local_guess[i] if i < len(local_guess) else "")
        rois = visible_rois
        local_matches = visible_local_matches
        local_guess = visible_local_guess

        results: list[str | None] = [None] * len(rois)

        for index, roi in enumerate(rois):
            guess = local_guess[index] if index < len(local_guess) else ""
            local_confidence = float(getattr(local_matches[index], "confidence", 0.0)) if index < len(local_matches) else 0.0
            results[index] = self._recognize_single_tile_with_vision(
                provider,
                api_key,
                model,
                endpoint,
                roi,
                index,
                guess,
                local_confidence,
            )

        merged: list[str] = []
        for index, tile_id in enumerate(results):
            if tile_id:
                merged.append(tile_id)
                continue
            guess = local_guess[index] if index < len(local_guess) else ""
            if guess:
                merged.append(guess)
                continue
            raise RuntimeError(f"第 {index + 1} 张牌未得到有效识别结果。")
        self._persist_picture_request(
            event_type="picture_hand_summary",
            provider=provider,
            model=model,
            image=hand_strip,
            local_guess=local_guess,
            response_text=json.dumps({"tiles": merged}, ensure_ascii=False),
            extra={
                "tile_count": len(rois),
                "kind": "hand_summary",
                "request_mode": "parallel",
                "max_workers": max_workers,
                "duration_ms": int((time.perf_counter() - started_at) * 1000),
            },
        )
        return merged

    def _recognize_single_tile_with_vision(
        self,
        provider: str,
        api_key: str,
        model: str,
        endpoint: str,
        roi,
        tile_index: int,
        local_guess: str,
        local_confidence: float,
    ) -> str:
        provider_conf = VISION_PROVIDERS.get(provider)
        if provider_conf is None:
            raise RuntimeError(f"不支持的视觉模型提供方: {provider}")

        started_at = time.perf_counter()
        vision_roi = self._prepare_roi_for_vision(roi)
        ok, encoded = cv2.imencode(".png", vision_roi)
        if not ok or encoded is None:
            raise RuntimeError("单牌图片编码失败")

        image_b64 = base64.b64encode(encoded.tobytes()).decode('ascii')
        prompt = self._get_volc_prompt(tile_index, local_guess)
        image_payload: dict[str, Any] = {
            "url": f"data:image/png;base64,{image_b64}",
        }
        if provider == "volc":
            image_payload["detail"] = "high"

        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": image_payload,
                        },
                    ],
                }
            ],
        }
        prompt = (
            f"这是一张台州麻将我方手牌切图，第 {tile_index + 1} 张。"
            "请只输出 JSON，格式固定为 {\”tile\”: \”1m\”}。"
            "tile 只允许是 1-9m, 1-9p, 1-9s, 1-7z 之一。"
            "【花色判断步骤，按顺序执行】"
            "第一步：牌面下半部分是否有红色”万/萬”字？有 → 花色是 m（万），数字看上半部分黑色数字。"
            "第二步：图案是否是竖向拉长的椭圆形/胶囊形/竹节形（明显高大于宽，像竖立的药丸）？是 → 花色是 s（条），数椭圆个数得数字。"
            "第三步：图案是否是圆形/铜钱形/同心圆（宽≈高，像硬币）？是 → 花色是 p（筒），数圆形个数得数字。"
            "第四步：整张牌是单个大汉字（东南西北中发白）？是 → 花色是 z（字）。"
            "【严禁混淆】竖向椭圆 = s（条）；圆形 = p（筒）。两者绝对不同，椭圆不是圆。"
            "忽略图片里的非牌面元素：高亮、边缘阴影、光标、UI 装饰、鼠标箭头。"
            "只返回最终 tile，不要解释。"
        )
        response_format: dict[str, str] | None = None
        if provider == "qwen":
            prompt += (
                "本地候选可能是错的，不要被它影响。"
                "如果图中上方是黑色数字”三”，下方是红色”万/萬”，答案必须是 {\”tile\”:\”3m\”}。"
            )
            messages = [
                {"role": "system", "content": self._get_qwen_system_prompt()},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": image_payload,
                        },
                    ],
                },
            ]
            response_format = {"type": "json_object"}
        else:
            prompt += f"本地识别候选是 {local_guess or 'unknown'}，如与图像冲突请忽略。"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": image_payload,
                        },
                    ],
                }
            ]
        body = {
            "model": model,
            "temperature": 0,
            "messages": messages,
        }
        if response_format is not None:
            body["response_format"] = response_format

        response_text = ""
        error_message = ""
        self._persist_picture_request(
            event_type="picture_tile_request",
            provider=provider,
            model=model,
            image=vision_roi,
            local_guess=[local_guess] if local_guess else [],
            response_text="",
            extra={
                "tile_index": tile_index + 1,
                "kind": "tile_request",
                "local_confidence": round(local_confidence, 4),
            },
        )
        try:
            response = self._http_post_json(
                url=endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                body=body,
            )
            response_text = response["choices"][0]["message"]["content"]
            parsed = self._extract_json_object(response_text)
            tile_id = self._resolve_tile_choice(
                model_tile=parsed.get("tile", ""),
                local_tile=local_guess,
                local_confidence=local_confidence,
            )
            if tile_id not in VALID_TILE_IDS:
                raise RuntimeError(f"无效 tile 返回: {tile_id or '<empty>'}")
            return tile_id
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            self._persist_picture_request(
                event_type="picture_tile_response",
                provider=provider,
                model=model,
                image=vision_roi,
                local_guess=[local_guess] if local_guess else [],
                response_text=response_text,
                error_message=error_message,
                extra={
                    "tile_index": tile_index + 1,
                    "kind": "tile_response",
                    "local_confidence": round(local_confidence, 4),
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )

    def _is_face_down_tile(self, roi) -> bool:
        """Return True if the ROI looks like a face-down (back-facing) tile.

        Face-down tiles have low saturation throughout (no red/green characters).
        Measured on actual game images:
          face-down: max_sat ≈ 90-100
          face-up:   max_sat ≈ 185-210
        Threshold at 130 gives a clear margin on both sides.
        """
        if roi is None or roi.size == 0:
            return False
        h, w = roi.shape[:2]
        if h < 10 or w < 10:
            return False
        cy1 = int(h * 0.40)
        cy2 = int(h * 0.80)
        cx1 = int(w * 0.20)
        cx2 = int(w * 0.80)
        center = roi[cy1:cy2, cx1:cx2]
        if center.size == 0:
            return False
        hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        return int(hsv[:, :, 1].max()) < 130

    def _prepare_roi_for_vision(self, roi):
        if roi is None or roi.size == 0:
            return roi
        h, w = roi.shape[:2]
        top = min(h - 1, max(0, int(h * 0.10)))
        bottom = min(h, max(top + 1, int(h * 0.98)))
        left = min(w - 1, max(0, int(w * 0.02)))
        right = min(w, max(left + 1, int(w * 0.98)))
        cropped = roi[top:bottom, left:right]
        return cropped if cropped.size else roi

    def _prepare_roi_for_local_match(self, roi):
        if roi is None or roi.size == 0:
            return roi
        ok, clean_img, _reason = prepare_trainable_hand_roi_image(roi)
        if ok and clean_img is not None and clean_img.size != 0:
            return clean_img
        return self._prepare_roi_for_vision(roi)

    def _expected_visible_hand_counts(self, meld_tiles: int) -> set[int]:
        return {
            max(1, 13 - meld_tiles),
            max(1, 14 - meld_tiles),
        }

    def _segment_hand_strip_with_expected_counts(self, hand_strip, expected_counts: list[int]) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]], int | None]:
        seen: set[int] = set()
        for expected in expected_counts:
            if expected in seen or expected <= 0:
                continue
            seen.add(expected)
            rois, slots = self._hand_region.segment_tiles_with_slots(hand_strip, expected_count=expected)
            if rois:
                return rois, slots, expected
        return [], [], None

    def _image_shape_list(self, image) -> list[int]:
        if image is None or getattr(image, "size", 0) == 0:
            return []
        return [int(dim) for dim in image.shape]

    def _refresh_local_recognizer_from_disk(self) -> None:
        model_path = os.path.join(data_path(), "models", "tile_svm.xml")
        if os.path.exists(model_path):
            hog_clf = getattr(self._tile_recognizer, "_hog_clf", None)
            if hog_clf is not None and getattr(hog_clf, "is_ready", False):
                hog_clf.load(model_path)
            else:
                self._tile_recognizer._hog_clf = TileHOGClassifier(model_path)
        cleaned_dir = data_path(os.path.join("data", "tile_samples_cleaned"))
        if hasattr(self._tile_recognizer, "load_training_samples"):
            self._tile_recognizer.load_training_samples(cleaned_dir)

    def _persist_deepseek_request(
        self,
        trigger_reason: str,
        model: str,
        payload: dict[str, Any],
        response_text: str,
        error_message: str = "",
    ) -> None:
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trigger_reason": trigger_reason,
            "model": model,
            "payload": payload,
            "response_text": response_text,
            "error_message": error_message,
        }
        self._write_capped_json("requestdeepseek", record)

    def _persist_picture_request(
        self,
        event_type: str,
        provider: str,
        model: str,
        image,
        local_guess: list[str],
        response_text: str,
        error_message: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        picture_dir = self._battle_data_dir("picture")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"{timestamp}_{event_type}"
        image_path = os.path.join(picture_dir, f"{base_name}.png")
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "provider": provider,
            "model": model,
            "local_guess": local_guess,
            "image_path": image_path,
            "response_text": response_text,
            "error_message": error_message,
        }
        if extra:
            record.update(extra)
        with self._picture_log_lock:
            cv2.imwrite(image_path, image)
            self._write_json_file(picture_dir, record, filename=f"{base_name}.json")
            self._prune_picture_directory(picture_dir, limit=300)
        return record

    def _persist_capture_debug(
        self,
        provider: str,
        model: str,
        hand_strip,
        raw_hand_rois: list[np.ndarray],
        prepared_hand_rois: list[np.ndarray],
        hand_matches: list[Any],
    ) -> None:
        debug_root = self._battle_data_dir("picture_debug")
        os.makedirs(debug_root, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        debug_dir = os.path.join(debug_root, f"{timestamp}_capture_debug")
        os.makedirs(debug_dir, exist_ok=True)

        debug = dict(self._last_capture_debug or {})
        debug.update(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "provider": provider,
                "model": model,
                "hand_match_count": len(hand_matches),
                "hand_matches": [
                    {
                        "tile_id": self._normalize_tile_id(getattr(match, "tile_id", "") or "") or "",
                        "confidence": round(float(getattr(match, "confidence", 0.0) or 0.0), 4),
                    }
                    for match in hand_matches
                ],
            }
        )

        hand_strip_path = os.path.join(debug_dir, "hand_strip.png")
        if hand_strip is not None and getattr(hand_strip, "size", 0) != 0:
            cv2.imwrite(hand_strip_path, hand_strip)
            debug["hand_strip_path"] = hand_strip_path

        def _write_roi_series(prefix: str, rois: list[np.ndarray]) -> list[str]:
            paths: list[str] = []
            for index, roi in enumerate(rois, start=1):
                if roi is None or getattr(roi, "size", 0) == 0:
                    continue
                path = os.path.join(debug_dir, f"{prefix}_{index:02d}.png")
                cv2.imwrite(path, roi)
                paths.append(path)
            return paths

        debug["raw_hand_roi_paths"] = _write_roi_series("hand_raw", raw_hand_rois)
        debug["prepared_hand_roi_paths"] = _write_roi_series("hand_prepared", prepared_hand_rois)

        meld_debug = debug.get("meld_debug") or {}
        raw_meld_rois = meld_debug.pop("raw_meld_rois", []) if isinstance(meld_debug, dict) else []
        prepared_meld_rois = meld_debug.pop("prepared_meld_rois", []) if isinstance(meld_debug, dict) else []
        if isinstance(meld_debug, dict):
            meld_debug["raw_meld_roi_paths"] = _write_roi_series("meld_raw", raw_meld_rois)
            meld_debug["prepared_meld_roi_paths"] = _write_roi_series("meld_prepared", prepared_meld_rois)
            debug["meld_debug"] = meld_debug

        self._write_json_file(debug_dir, debug, "capture_debug.json")
        self._prune_subdirectories(debug_root, limit=80)

    def _write_capped_json(self, subdir: str, payload: dict[str, Any], filename: str | None = None) -> None:
        target_dir = self._battle_data_dir(subdir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_name = filename or f"{timestamp}.json"
        with self._json_log_lock:
            self._write_json_file(target_dir, payload, output_name)
            self._prune_directory(target_dir, limit=300)

    def _battle_data_dir(self, subdir: str) -> str:
        return data_path(os.path.join("data", subdir))

    def _write_json_file(self, directory: str, payload: dict[str, Any], filename: str) -> None:
        output_path = os.path.join(directory, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _prune_directory(self, directory: str, limit: int) -> None:
        paths: list[str] = []
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                paths.append(path)
        paths.sort(key=self._safe_mtime, reverse=True)
        for stale_path in paths[limit:]:
            try:
                os.remove(stale_path)
            except OSError:
                pass

    def _prune_picture_directory(self, directory: str, limit: int) -> None:
        json_paths: list[str] = []
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if name.lower().endswith(".json") and os.path.isfile(path):
                json_paths.append(path)
        json_paths.sort(key=self._safe_mtime, reverse=True)
        for stale_json in json_paths[limit:]:
            base, _ext = os.path.splitext(stale_json)
            paired_png = base + ".png"
            for stale_path in (stale_json, paired_png):
                try:
                    if os.path.exists(stale_path):
                        os.remove(stale_path)
                except OSError:
                    pass

    def _prune_subdirectories(self, directory: str, limit: int) -> None:
        subdirs: list[str] = []
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isdir(path):
                subdirs.append(path)
        subdirs.sort(key=self._safe_mtime, reverse=True)
        for stale_dir in subdirs[limit:]:
            try:
                for root, _dirs, files in os.walk(stale_dir, topdown=False):
                    for file_name in files:
                        try:
                            os.remove(os.path.join(root, file_name))
                        except OSError:
                            pass
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass
            except OSError:
                pass

    def _safe_mtime(self, path: str) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    def _http_post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络请求失败: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"服务返回了非 JSON 内容: {raw[:300]}") from exc

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise RuntimeError("模型未返回文本内容。")
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, re.S)
            if not match:
                raise RuntimeError(f"模型未返回可解析 JSON: {text}")
            return json.loads(match.group(0))

    def _get_volc_prompt(self, tile_index: int, local_guess: str) -> str:
        template = str(
            self._config.get("vision", {}).get("volc_prompt", VOLC_VISION_PROMPT_TEMPLATE)
        ).strip() or VOLC_VISION_PROMPT_TEMPLATE
        try:
            return template.format(tile_index=tile_index + 1, local_guess=local_guess or "unknown")
        except Exception:
            return VOLC_VISION_PROMPT_TEMPLATE.format(
                tile_index=tile_index + 1, local_guess=local_guess or "unknown"
            )

    def _get_qwen_system_prompt(self) -> str:
        return str(
            self._config.get("vision", {}).get("qwen", {}).get("system_prompt", QWEN_VISION_SYSTEM_PROMPT)
        ).strip() or QWEN_VISION_SYSTEM_PROMPT

    def _get_qwen_user_prompt(self, tile_index: int, local_guess: str) -> str:
        template = str(
            self._config.get("vision", {}).get("qwen", {}).get("user_prompt", QWEN_VISION_USER_PROMPT_TEMPLATE)
        ).strip() or QWEN_VISION_USER_PROMPT_TEMPLATE
        try:
            return template.format(tile_index=tile_index + 1, local_guess=local_guess or "unknown")
        except Exception:
            return QWEN_VISION_USER_PROMPT_TEMPLATE.format(
                tile_index=tile_index + 1,
                local_guess=local_guess or "unknown",
            )

    def _normalize_tile_id(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        compact = text.lower().replace(" ", "").replace("_", "").replace("-", "")
        compact = compact.replace("wan", "w").replace("tong", "p").replace("tiao", "s")
        compact = compact.replace("dot", "p").replace("dots", "p").replace("circle", "p").replace("circles", "p")
        compact = compact.replace("bamboo", "s").replace("bamboos", "s").replace("sou", "s")
        compact = compact.replace("character", "m").replace("characters", "m").replace("char", "m")

        if compact in HONOR_TILE_ALIASES:
            return HONOR_TILE_ALIASES[compact]

        compact = compact.replace("萬", "w").replace("万", "w")
        compact = compact.replace("筒", "p").replace("饼", "p").replace("餅", "p")
        compact = compact.replace("条", "s").replace("條", "s").replace("索", "s")

        match = re.fullmatch(r"([1-9])([mpswtd])", compact)
        if match:
            number, suit = match.groups()
            suit_map = {
                "m": "m",
                "w": "m",
                "p": "p",
                "t": "p",
                "d": "p",
                "s": "s",
            }
            return f"{number}{suit_map.get(suit, suit)}"

        if compact in HONOR_TILE_ALIASES:
            return HONOR_TILE_ALIASES[compact]
        return compact

    def _resolve_tile_choice(self, model_tile: Any, local_tile: str, local_confidence: float) -> str:
        normalized_model = self._normalize_tile_id(model_tile)
        normalized_local = self._normalize_tile_id(local_tile)

        # Prefer the vision model whenever it returns a valid tile.
        # Local recognition is only a fallback for invalid / empty model output.
        if normalized_model in VALID_TILE_IDS:
            return normalized_model

        if normalized_local in VALID_TILE_IDS:
            return normalized_local

        return normalized_model

    def _tile_family(self, tile_id: str) -> str:
        if not tile_id:
            return ""
        if tile_id.endswith("z"):
            return "honor"
        if tile_id.endswith("m"):
            return "man"
        if tile_id.endswith("p"):
            return "pin"
        if tile_id.endswith("s"):
            return "sou"
        return ""

    def _get_configured_vision_provider(self) -> str:
        return self._config.get("vision", {}).get("provider", "auto").strip() or "auto"

    def _get_vision_provider(self) -> str:
        configured = self._get_configured_vision_provider()
        if configured != "auto":
            return configured

        volc_key = self._config.get("vision", {}).get("volc", {}).get("api_key", "").strip()
        volc_model = self._config.get("vision", {}).get("volc", {}).get("model", "").strip()
        if volc_key and volc_model:
            return "volc"

        glm_key = self._config.get("vision", {}).get("glm", {}).get("api_key", "").strip()
        if glm_key:
            return "glm"

        qwen_key = self._config.get("vision", {}).get("qwen", {}).get("api_key", "").strip()
        if qwen_key:
            return "qwen"

        return "volc"

    def _get_vision_model(self, provider: str) -> str:
        vision_cfg = self._config.get("vision", {})
        provider_cfg = vision_cfg.get(provider, {})
        return provider_cfg.get("model", VISION_PROVIDERS[provider]["default_model"]).strip()

    def _get_vision_endpoint(self, provider: str) -> str:
        vision_cfg = self._config.get("vision", {})
        provider_cfg = vision_cfg.get(provider, {})
        endpoint = provider_cfg.get("endpoint", VISION_PROVIDERS[provider]["endpoint"])
        return str(endpoint).strip() or VISION_PROVIDERS[provider]["endpoint"]

    def _get_vision_api_key(self, provider: str) -> str:
        vision_cfg = self._config.get("vision", {})
        provider_cfg = vision_cfg.get(provider, {})
        return provider_cfg.get("api_key", "").strip()
