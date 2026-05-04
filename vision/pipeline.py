from __future__ import annotations
import os
import time
import csv
import cv2
import numpy as np
import json
import logging
from typing import Optional, Callable

from vision.capture import ScreenCapture
from vision.discard_tile_cropper import prepare_trainable_discard_roi_image
from vision.layout import LayoutCalculator
from vision.recognizer import TileRecognizer, ButtonRecognizer, MatchResult, StripMatch
from vision.discard_recognizer import DiscardAreaRecognizer
from vision.hand_region_module import HandRegionModule
from game.state import (
    GameState, PlayerState, OpponentState, TileMatch, MeldGroup, RegionObservation,
    PHASE_PLAYING, PHASE_SHENGJIA, PHASE_LIUJU, PHASE_HUPAI,
)
from game.session import GameSession


SHENGJIA_THRESHOLD = 15   # 剩余≤15张进入生牌阶段

logger = logging.getLogger("mahjongai.pipeline")


class RecognitionPipeline:
    """编排单帧全流程：截图 → 9区域识别 → 事件推断 → 写入 session。"""

    def __init__(
        self,
        capture: ScreenCapture,
        layout: LayoutCalculator,
        tile_recognizer: TileRecognizer,
        button_recognizer: ButtonRecognizer,
        session: Optional[GameSession] = None,
        discard_recognizer: Optional[DiscardAreaRecognizer] = None,
    ):
        self._capture = capture
        self._layout = layout
        self._tile_rec = tile_recognizer
        self._btn_rec = button_recognizer
        self._session = session
        self._discard_rec = discard_recognizer
        self._hand_region = HandRegionModule()
        self._frame_index = 0
        self._prev_state: Optional[GameState] = None
        self._on_frame: Optional[Callable[[GameState], None]] = None
        self._tile_match_cache: dict[str, tuple[np.ndarray, MatchResult]] = {}

        # Debug 诊断模式
        self._debug_dir: Optional[str] = None
        self._recognition_save_interval = 10
        self._debug_save_interval = 10
        self._keyframe_interval = 50

        # QTimer（PyQt6），在 UI 线程中启动
        self._timer = None

    # ------------------------------------------------------------------ #
    #  公共接口                                                            #
    # ------------------------------------------------------------------ #

    def set_session(self, session: GameSession) -> None:
        self._session = session

    def set_on_frame(self, callback: Callable[[GameState], None]) -> None:
        """设置每帧识别完成的回调（UI 更新用）。"""
        self._on_frame = callback

    def enable_debug(self, save_dir: str) -> None:
        """启用 debug 诊断模式，保存每帧 ROI 和匹配日志到指定目录。"""
        self._debug_dir = save_dir
        os.makedirs(os.path.join(save_dir, "frames"), exist_ok=True)
        os.makedirs(os.path.join(save_dir, "hand_strips"), exist_ok=True)
        os.makedirs(os.path.join(save_dir, "hand_rois"), exist_ok=True)
        os.makedirs(os.path.join(save_dir, "masks"), exist_ok=True)
        # 写 CSV 表头
        csv_path = os.path.join(save_dir, "match_log.csv")
        if not os.path.exists(csv_path):
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "frame", "slot", "tile_id", "confidence",
                    "roi_w", "roi_h", "best_scale", "note"
                ])

    def disable_debug(self) -> None:
        """关闭 debug 诊断模式。"""
        self._debug_dir = None

    def start(self, interval_ms: int = 500) -> None:
        from PyQt6.QtCore import QTimer
        if self._timer is None:
            self._timer = QTimer()
            self._timer.timeout.connect(self._tick)
        self._frame_index = 0
        self._prev_state = None
        self._tile_match_cache.clear()
        self._timer.start(interval_ms)

    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
        if self._session:
            self._session.flush()

    def run_frame(self) -> GameState:
        """手动触发单帧识别（测试用）。"""
        return self._process_frame()

    def run_from_file(self, image_path: str) -> GameState:
        """从图片文件识别（开发调试用）。"""
        frame = self._capture.grab_file(image_path)
        return self._process_frame(frame)

    def reset_runtime(self) -> None:
        self._frame_index = 0
        self._prev_state = None
        self._tile_match_cache.clear()

    def clear_match_cache(self) -> None:
        self._tile_match_cache.clear()

    # ------------------------------------------------------------------ #
    #  内部方法                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _roi_signature(roi: np.ndarray) -> np.ndarray:
        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi
        small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        return (small // 8).astype(np.uint8)

    def _cached_match_tile(
        self,
        cache_key: str,
        roi: np.ndarray,
        debug_info: dict | None = None,
    ) -> MatchResult:
        sig = self._roi_signature(roi)
        cached = self._tile_match_cache.get(cache_key)
        if cached is not None:
            prev_sig, prev_result = cached
            diff = float(np.mean(np.abs(prev_sig.astype(np.int16) - sig.astype(np.int16))))
            if diff <= 1.0:
                if debug_info is not None:
                    debug_info["cache_hit"] = True
                    debug_info["cache_diff"] = round(diff, 3)
                return prev_result
        result = self._tile_rec.match_tile(roi, debug_info=debug_info)
        self._tile_match_cache[cache_key] = (sig, result)
        return result

    def _tick(self) -> None:
        state = self._process_frame()
        if self._on_frame:
            self._on_frame(state)

    def _process_frame(self, frame: Optional[np.ndarray] = None) -> GameState:
        t0 = time.perf_counter()

        if frame is None:
            frame = self._capture.grab()

        state = GameState(frame_index=self._frame_index)
        state.self_player = PlayerState()
        state.opponents = [
            OpponentState(seat="right"),
            OpponentState(seat="across"),
            OpponentState(seat="left"),
        ]

        def rect_dict(rect) -> dict:
            return {"x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h}

        def tile_items(results: list, slots: list[tuple[int, int, int, int]] | None = None) -> list[dict]:
            items = []
            for i, r in enumerate(results):
                item = {
                    "slot": i,
                    "tile_id": getattr(r, "tile_id", None),
                    "confidence": round(float(getattr(r, "confidence", 0.0)), 4),
                    "method": getattr(r, "method", ""),
                }
                if slots and i < len(slots):
                    x, y, rw, rh = slots[i]
                    item["rect"] = {"x": x, "y": y, "w": rw, "h": rh}
                items.append(item)
            return items

        # 区域1: 自家手牌
        meld_count = len(state.self_player.melds) if state.self_player.melds else 0
        hand_region_rect = self._layout.hand_region(meld_count)
        hand_strip = self._capture.grab_from_frame(frame, hand_region_rect)

        logger.info(
            "[Frame %d] 手牌区域: x=%d y=%d w=%d h=%d",
            self._frame_index,
            hand_region_rect.x, hand_region_rect.y,
            hand_region_rect.w, hand_region_rect.h,
        )

        # 先估计当前是 13 张还是 14 张，再扣除副露占位，避免整局都按 13 张硬切。
        if self._prev_state is None:
            # First frame should not force 13. Let visual segmentation infer
            # whether the visible hand is 13 or 14.
            base_hand = 14
        else:
            detected_hand = self._hand_region.detect_tile_count(frame, meld_count, self._layout, self._capture)
            prev_hand = len(self._prev_state.self_player.hand) if self._prev_state.self_player.hand else 13
            if detected_hand in (13, 14) and abs(detected_hand - prev_hand) <= 1:
                base_hand = detected_hand
            else:
                base_hand = 14 if prev_hand >= 14 else 13
        expected_hand = max(1, base_hand - meld_count * 3)

        # 优先使用亮度投影精切牌（比等分扫描更不容易丢边牌）
        hand_rois, hand_slots = self._hand_region.segment_tiles_with_slots(
            hand_strip,
            expected_hand,
            frame_index=self._frame_index,
            debug_dir=self._debug_dir,
        )
        if 10 <= len(hand_rois) <= 15 and abs(len(hand_rois) - expected_hand) <= 1:
            expected_hand = len(hand_rois)
        state.hand_count = expected_hand
        scan_results: list[StripMatch] = []
        scan_dbg: dict = {}

        if 10 <= len(hand_rois) <= 15:
            hand_results = []
            debug_details = []
            for i, roi in enumerate(hand_rois):
                dbg = {}
                result = self._cached_match_tile(f"self_hand:{i}", roi, debug_info=dbg)
                hand_results.append(result)
                debug_details.append(dbg)
                logger.info(
                    "[Frame %d] ROI[%d] %dx%d → %s (conf=%.3f)",
                    self._frame_index, i,
                    roi.shape[1], roi.shape[0],
                    result.tile_id or "MISS", result.confidence,
                )
            state.self_player.hand = [TileMatch(r.tile_id, r.confidence) for r in hand_results]
            state.regions["self_hand"] = RegionObservation(
                name="self_hand",
                rect=rect_dict(hand_region_rect),
                kind="tile_sequence",
                items=tile_items(hand_results, hand_slots),
                summary={
                    "segment_method": "white_components_or_projection",
                    "tile_count": len(hand_results),
                    "recognized_count": sum(1 for r in hand_results if r.tile_id),
                },
            )
            logger.info(
                "[Frame %d] 亮度投影分割识别: %d 张牌 | %s",
                self._frame_index,
                len(hand_results),
                " | ".join(f"{r.tile_id or '?'}({r.confidence:.2f})" for r in hand_results),
            )
        else:
            # 精切失败，fallback 到滑动窗口扫描
            logger.info(
                "[Frame %d] 亮度投影分割不足(%d张)，回退到滑动窗口扫描",
                self._frame_index, len(hand_rois),
            )
            scan_results = self._tile_rec.scan_hand_strip(
                hand_strip, est_tile_count=expected_hand, debug_info=scan_dbg
            )
            hand_results = [
                MatchResult(
                    tile_id=r.tile_id,
                    confidence=r.confidence,
                    method=r.method,
                )
                for r in scan_results
            ]
            state.self_player.hand = [
                TileMatch(r.tile_id, r.confidence) for r in scan_results
            ]
            hand_rois = []
            hand_slots = [
                (max(0, int(r.x_center) - 1), 0, 2, hand_strip.shape[0])
                for r in scan_results
            ]
            debug_details = [scan_dbg]
            state.regions["self_hand"] = RegionObservation(
                name="self_hand",
                rect=rect_dict(hand_region_rect),
                kind="tile_sequence",
                items=tile_items(hand_results, hand_slots),
                summary={
                    "segment_method": "scan_hand_strip",
                    "tile_count": len(hand_results),
                    "recognized_count": sum(1 for r in hand_results if r.tile_id),
                    "debug": scan_dbg,
                },
            )

            logger.info(
                "[Frame %d] 滑动窗口识别: %d 张牌 | %s",
                self._frame_index,
                len(scan_results),
                " | ".join(
                    f"{r.tile_id or '?'}({r.confidence:.2f})" for r in scan_results
                ),
            )

        should_save_recognition = (
            self._session is not None
            and (self._frame_index % self._recognition_save_interval == 0)
        )
        # 高频识别时不要每帧写 ROI/png/json，否则 100ms 模式会被磁盘 IO 拖住。
        if should_save_recognition and hand_rois:
            self._save_recognition_results(hand_rois, hand_results, debug_details)
        elif should_save_recognition and scan_results:
            # 滑动窗口模式下保存简要结果
            self._save_scan_results(scan_results, hand_strip, scan_dbg)

        # Debug: 保存完整诊断信息
        if self._debug_dir and self._frame_index % self._debug_save_interval == 0:
            # 1. 保存完整帧（带手牌区域标注）
            debug_frame = frame.copy()
            cv2.rectangle(debug_frame,
                          (hand_region_rect.x, hand_region_rect.y),
                          (hand_region_rect.x + hand_region_rect.w,
                           hand_region_rect.y + hand_region_rect.h),
                          (0, 255, 0), 2)
            frame_path = os.path.join(self._debug_dir, "frames", f"f{self._frame_index}.png")
            cv2.imwrite(frame_path, debug_frame)

            # 2. 保存手牌区域 strip
            if hand_strip is not None and hand_strip.size > 0:
                strip_path = os.path.join(self._debug_dir, "hand_strips", f"f{self._frame_index}.png")
                cv2.imwrite(strip_path, hand_strip)

            # 3. 保存每个 ROI 和详细匹配日志
            csv_path = os.path.join(self._debug_dir, "match_log.csv")
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for i, (roi, result, dbg) in enumerate(zip(hand_rois, hand_results, debug_details)):
                    roi_path = os.path.join(self._debug_dir, "hand_rois", f"f{self._frame_index}_s{i}.png")
                    cv2.imwrite(roi_path, roi)
                    roi_h, roi_w = roi.shape[:2]
                    top5 = dbg.get("top5_matches", [])
                    top5_str = "; ".join(
                        f"{m['tile_id']}:{m['confidence']}" for m in top5[:3]
                    ) if top5 else ""
                    note = "OK" if result.tile_id else "MISS"
                    writer.writerow([
                        self._frame_index, i,
                        result.tile_id or "None",
                        f"{result.confidence:.3f}",
                        roi_w, roi_h,
                        "1.00",
                        f"{note} | top3: {top5_str}"
                    ])

        # 区域3: 四家弃牌堆
        should_save_discard = (
            self._session is not None
            and (self._frame_index % self._recognition_save_interval == 0)
        )
        for player_idx in range(4):
            results, slot_rects = self._recognize_discard_player(frame, player_idx)

            # 遇到真正的空格才截断。若前几个格子切到了半张牌/识别失败，
            # 不要直接把整家弃牌判成 0 张。
            tiles: list[TileMatch] = []
            saw_occupied_slot = False
            for r in results:
                if r.method == "empty_slot":
                    if saw_occupied_slot:
                        break
                    continue
                saw_occupied_slot = True
                if r.tile_id is None:
                    continue
                tiles.append(TileMatch(r.tile_id, r.confidence))

            if player_idx == 0:
                state.self_player.discards = tiles
            else:
                state.opponents[player_idx - 1].discards = tiles

            region_name = {
                0: "discard.self",
                1: "discard.right",
                2: "discard.across",
                3: "discard.left",
            }[player_idx]
            discard_slots = self._layout.discard_slots(player_idx)
            active_rects = slot_rects if slot_rects else [(s.x, s.y, s.w, s.h) for s in discard_slots]
            if active_rects:
                x1 = min(r[0] for r in active_rects)
                y1 = min(r[1] for r in active_rects)
                x2 = max(r[0] + r[2] for r in active_rects)
                y2 = max(r[1] + r[3] for r in active_rects)
                region_rect = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
            else:
                region_rect = {"x": 0, "y": 0, "w": 0, "h": 0}
            observed_items = tile_items(results, slot_rects)
            state.regions[region_name] = RegionObservation(
                name=region_name,
                rect=region_rect,
                kind="discard_grid",
                items=observed_items,
                summary={
                    "seat": ["self", "right", "across", "left"][player_idx],
                    "grid_slots": len(discard_slots),
                    "visible_discards": len(tiles),
                    "recognized_count": sum(1 for t in tiles if t.tile_id),
                    "truncated_at_first_empty": True,
                    "recognizer": "discard_rec" if self._discard_rec else "tile_rec",
                },
            )

            # 弃牌 ROI 保存（间隔抽样）
            if should_save_discard and results:
                discard_rois = []
                for x, y, w, h in slot_rects[: len(results)]:
                    discard_rois.append(frame[y:y + h, x:x + w].copy())
                self._save_discard_recognition_results(player_idx, discard_rois, results)

        # 区域5: 剩余牌数（数字模板匹配）
        rt_region = self._layout.remaining_tiles_region()
        rt_roi = self._capture.grab_from_frame(frame, rt_region)
        state.remaining_tiles = self._read_remaining_tiles(rt_roi)
        state.regions["remaining_tiles"] = RegionObservation(
            name="remaining_tiles",
            rect=rect_dict(rt_region),
            kind="number",
            items=[],
            summary={
                "value": state.remaining_tiles,
                "status": "recognized" if state.remaining_tiles is not None else "unread",
            },
        )

        # 区域6: 决策按钮
        btn_region = self._layout.decision_buttons_region()
        btn_roi = self._capture.grab_from_frame(frame, btn_region)
        state.decision_prompt = self._btn_rec.detect_buttons(btn_roi)
        state.regions["decision_buttons"] = RegionObservation(
            name="decision_buttons",
            rect=rect_dict(btn_region),
            kind="buttons",
            items=[{"button": b, "visible": True} for b in state.decision_prompt],
            summary={
                "visible_buttons": state.decision_prompt,
                "count": len(state.decision_prompt),
            },
        )

        # 区域7: 游戏阶段覆盖层
        ov_region = self._layout.game_overlay_region()
        ov_roi = self._capture.grab_from_frame(frame, ov_region)
        overlay = self._btn_rec.detect_overlay(ov_roi)
        state.regions["game_overlay"] = RegionObservation(
            name="game_overlay",
            rect=rect_dict(ov_region),
            kind="overlay",
            items=[],
            summary={
                "overlay": overlay,
                "detected": overlay is not None,
            },
        )
        if overlay == "流局":
            state.game_phase = PHASE_LIUJU
        elif overlay == "胡牌":
            state.game_phase = PHASE_HUPAI
        elif state.remaining_tiles is not None and state.remaining_tiles <= SHENGJIA_THRESHOLD:
            state.game_phase = PHASE_SHENGJIA
        else:
            state.game_phase = PHASE_PLAYING

        # 最低置信度统计
        all_conf = [t.confidence for t in state.self_player.hand]
        for opp in state.opponents:
            all_conf += [t.confidence for t in opp.discards]
        state.raw_confidence_min = min(all_conf) if all_conf else 1.0

        # 帧间事件推断
        state.events = self._infer_events(self._prev_state, state)

        # 写入 session
        if self._session:
            self._session.append_frame(state)

        # 保存关键帧：每 10 帧保存一张带标注的完整截图 + 手牌识别文本到 session 目录
        if self._session and self._session.keyframes_dir and frame is not None:
            if self._frame_index % self._keyframe_interval == 0:
                self._save_keyframe(frame, state, hand_region_rect, hand_results)

        # Debug: 每帧结束后写诊断报告
        if self._debug_dir and self._frame_index % self._debug_save_interval == 0:
            self._write_frame_report(state, hand_region_rect, len(hand_rois))

        self._prev_state = state
        self._frame_index += 1

        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        # 将耗时附加到 dbg（通过 to_dict 已有 frame_ms 字段）
        state._frame_ms = elapsed_ms

        return state

    def _save_keyframe(self, frame: np.ndarray, state: GameState, hand_rect,
                        hand_results: list[MatchResult] | None = None) -> None:
        """保存带标注的关键帧 + 手牌识别文本到 session 的 keyframes/ 目录。"""
        if frame is None or not self._session:
            return
        try:
            # 复制帧并绘制标注
            vis = frame.copy()
            h, w = vis.shape[:2]

            # 1. 手牌区域（绿色框）
            cv2.rectangle(vis,
                          (hand_rect.x, hand_rect.y),
                          (hand_rect.x + hand_rect.w, hand_rect.y + hand_rect.h),
                          (0, 255, 0), 2)

            # 2. 弃牌区域（蓝色框）- 四家
            for player_idx in range(4):
                discard_slots = self._layout.discard_slots(player_idx)
                if discard_slots:
                    # 画整个弃牌区域的外框
                    xs = [s.x for s in discard_slots]
                    ys = [s.y for s in discard_slots]
                    x1, y1 = min(xs), min(ys)
                    x2, y2 = max(s.x + s.w for s in discard_slots), max(s.y + s.h for s in discard_slots)
                    colors = [(255, 0, 0), (0, 255, 255), (255, 255, 0), (255, 0, 255)]
                    cv2.rectangle(vis, (x1, y1), (x2, y2), colors[player_idx], 2)

            # 3. 剩余牌数区域（白色框）
            rt = self._layout.remaining_tiles_region()
            cv2.rectangle(vis, (rt.x, rt.y), (rt.x + rt.w, rt.y + rt.h), (255, 255, 255), 2)

            # 4. 决策按钮区域（橙色框）
            btn = self._layout.decision_buttons_region()
            cv2.rectangle(vis, (btn.x, btn.y), (btn.x + btn.w, btn.y + btn.h), (0, 165, 255), 2)

            # 5. 在左上角添加文字信息
            info_lines = [
                f"Frame: {state.frame_index}",
                f"Hand: {len(state.self_player.hand)} tiles",
                f"Phase: {state.game_phase}",
                f"Events: {', '.join(state.events) if state.events else 'none'}",
            ]
            for i, line in enumerate(info_lines):
                y = 25 + i * 25
                # 黑色背景
                cv2.putText(vis, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
                # 白色文字
                cv2.putText(vis, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            # 编码为 PNG bytes
            ok, buf = cv2.imencode(".png", vis)
            if ok and buf is not None:
                # 构建手牌识别信息（从 MatchResult 获取 method）
                hand_info = None
                if hand_results is not None:
                    hand_info = [
                        {
                            "tile_id": r.tile_id,
                            "confidence": round(r.confidence, 3),
                            "method": r.method,
                        }
                        for r in hand_results
                    ]
                self._session.save_keyframe(state.frame_index, buf.tobytes(), hand_info=hand_info)
                # 同步保存弃牌关键帧（复用同一张截图）
                if hasattr(self._session, 'save_discard_keyframe'):
                    discard_info = []
                    for pidx in range(4):
                        if pidx == 0:
                            d_tiles = state.self_player.discards
                        else:
                            d_tiles = state.opponents[pidx - 1].discards
                        discard_info.append({
                            "player_idx": pidx,
                            "seat": ["self", "right", "across", "left"][pidx],
                            "tiles": [
                                {"tile_id": t.tile_id, "confidence": round(t.confidence, 3)}
                                for t in d_tiles
                            ],
                        })
                    self._session.save_discard_keyframe(
                        state.frame_index, buf.tobytes(), discard_info
                    )
        except Exception as e:
            logger.warning("[Frame %d] 保存关键帧失败: %s", self._frame_index, e)

    def _write_frame_report(self, state: GameState, hand_rect, roi_count: int) -> None:
        """将当前帧的诊断信息写入 JSON 报告。"""
        report = {
            "frame_index": state.frame_index,
            "hand_region": {
                "x": hand_rect.x, "y": hand_rect.y,
                "w": hand_rect.w, "h": hand_rect.h,
            },
            "roi_count": roi_count,
            "hand_tiles": [
                {"tile_id": t.tile_id, "confidence": round(t.confidence, 3)}
                for t in state.self_player.hand
            ],
            "hand_tile_count": len(state.self_player.hand),
            "min_confidence": round(state.raw_confidence_min, 3),
            "game_phase": state.game_phase,
            "events": state.events,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        report_path = os.path.join(self._debug_dir, "frame_reports.jsonl")
        with open(report_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
        logger.info(
            "[Frame %d] 帧报告: %d ROIs, %d tiles, min_conf=%.3f, phase=%s",
            state.frame_index, roi_count,
            len(state.self_player.hand), state.raw_confidence_min,
            state.game_phase,
        )

    def _save_scan_results(
        self,
        scan_results: list[StripMatch],
        hand_strip: np.ndarray,
        debug_info: dict,
    ) -> None:
        """保存滑动窗口扫描结果到 session/recognition/frame_NNNN/ 目录。"""
        if not self._session:
            return
        base_dir = os.path.join(self._session.session_dir, "recognition")
        frame_dir = os.path.join(base_dir, f"frame_{self._frame_index:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        summary = {
            "frame_index": self._frame_index,
            "method": "scan_hand_strip",
            "hand_tile_count": len(scan_results),
            "tiles": [
                {"tile_id": r.tile_id, "confidence": round(r.confidence, 4), "x_center": r.x_center}
                for r in scan_results
            ],
            "debug": debug_info,
        }
        with open(os.path.join(frame_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # 保存条带图片
        if hand_strip is not None and hand_strip.size > 0:
            cv2.imwrite(os.path.join(frame_dir, "strip.png"), hand_strip)

    def _save_recognition_results(
        self,
        hand_rois: list[np.ndarray],
        hand_results: list[MatchResult],
        debug_details: list[dict],
    ) -> None:
        """保存每帧手牌识别结果到 session/recognition/frame_NNNN/ 目录。"""
        if not self._session:
            return
        base_dir = os.path.join(self._session.session_dir, "recognition")
        frame_dir = os.path.join(base_dir, f"frame_{self._frame_index:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        summary = {
            "frame_index": self._frame_index,
            "hand_tile_count": len(hand_results),
            "tiles": [],
        }

        for i, (roi, result, dbg) in enumerate(zip(hand_rois, hand_results, debug_details)):
            # 保存干净 ROI，避免调试文字污染后续复测/训练。
            cv2.imwrite(os.path.join(frame_dir, f"roi_{i}.png"), roi)

            # 另存带识别结果文字的调试 ROI。
            vis = roi.copy()
            if len(vis.shape) == 2:
                vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
            label = f"{result.tile_id or 'MISS'}:{result.confidence:.3f} ({result.method})"
            cv2.putText(vis, label, (2, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)
            cv2.imwrite(os.path.join(frame_dir, f"roi_{i}_annotated.png"), vis)

            # 单张结果 JSON — 包含所有策略的详细匹配信息
            roi_result = {
                "tile_id": result.tile_id,
                "confidence": round(result.confidence, 4),
                "method": result.method,
            }
            # 结构化匹配
            struct_top5 = dbg.get("struct_top5", [])
            if struct_top5:
                roi_result["struct_top5"] = struct_top5[:5]
            # HSV 直方图匹配
            hist_top5 = dbg.get("hist_top5", [])
            if hist_top5:
                roi_result["hist_top5"] = hist_top5[:5]
            # 灰度 NCC 匹配
            ncc_top5 = dbg.get("ncc_top5", [])
            if ncc_top5:
                roi_result["ncc_top5"] = ncc_top5[:5]
            # ORB 匹配
            orb_top5 = dbg.get("orb_top5", [])
            if orb_top5:
                roi_result["orb_top5"] = orb_top5[:5]
            # 融合信息
            fusion_votes = dbg.get("fusion_votes", {})
            if fusion_votes:
                roi_result["fusion_votes"] = fusion_votes
                roi_result["fusion_n_votes"] = dbg.get("fusion_n_votes", 0)
            with open(os.path.join(frame_dir, f"roi_{i}.json"), "w", encoding="utf-8") as f:
                json.dump(roi_result, f, ensure_ascii=False, indent=2)

            summary["tiles"].append({
                "tile_id": result.tile_id,
                "confidence": round(result.confidence, 4),
                "method": result.method,
            })

        # 保存汇总 JSON
        with open(os.path.join(frame_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info("[Frame %d] 识别结果已保存: %s", self._frame_index, frame_dir)

    def _recognize_discard_player(
        self,
        frame: np.ndarray,
        player_idx: int,
    ) -> tuple[list[MatchResult], list[tuple[int, int, int, int]]]:
        """识别单个玩家的弃牌区域。

        若已注入 DiscardAreaRecognizer，则使用其专属训练样本；
        否则 fallback 到 tile_rec + pipeline 缓存（向后兼容）。
        """
        if self._discard_rec is not None:
            return self._discard_rec.recognize_player(
                frame, self._layout, self._capture, player_idx
            )
        # fallback：原有内联逻辑
        discard_slots = self._layout.discard_slots(player_idx)
        results: list[MatchResult] = []
        for slot_idx, s in enumerate(discard_slots):
            roi = self._capture.grab_from_frame(frame, s)
            if not self._tile_rec.is_probably_tile_roi(roi):
                results.append(MatchResult(tile_id=None, confidence=0.0, method="empty_slot"))
                break
            results.append(self._cached_match_tile(f"discard:{player_idx}:{slot_idx}", roi))
        slot_rects = [(s.x, s.y, s.w, s.h) for s in discard_slots[: len(results)]]
        return results, slot_rects

    def _save_discard_recognition_results(
        self,
        player_idx: int,
        rois: list[np.ndarray],
        results: list[MatchResult],
    ) -> None:
        """保存弃牌区域 ROI 和识别摘要到 session/discard_recognition/frame_XXXX/。"""
        if not self._session:
            return
        seat = ["self", "right", "across", "left"][player_idx]
        base_dir = os.path.join(self._session.session_dir, "discard_recognition")
        frame_dir = os.path.join(base_dir, f"frame_{self._frame_index:04d}")
        os.makedirs(frame_dir, exist_ok=True)

        summary = {
            "frame_index": self._frame_index,
            "player_idx": player_idx,
            "seat": seat,
            "tile_count": len(results),
            "tiles": [],
        }
        for i, (roi, result) in enumerate(zip(rois, results)):
            if roi is None or roi.size == 0:
                continue
            # Keep the whole single-tile ROI here; training/review can do a
            # lighter cleanup later, but shrinking at save-time makes samples
            # look zoomed-in and loses border context.
            save_roi = roi
            cv2.imwrite(os.path.join(frame_dir, f"roi_{seat}_{i}.png"), save_roi)
            # 带标注的调试图
            vis = save_roi.copy()
            if len(vis.shape) == 2:
                vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
            label = f"{result.tile_id or 'MISS'}:{result.confidence:.3f}"
            cv2.putText(vis, label, (2, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
            cv2.imwrite(os.path.join(frame_dir, f"roi_{seat}_{i}_annotated.png"), vis)
            summary["tiles"].append({
                "tile_id": result.tile_id,
                "confidence": round(result.confidence, 4),
                "method": result.method,
            })

        with open(os.path.join(frame_dir, f"summary_{seat}.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def _segment_tiles_with_slots(self, strip: np.ndarray, expected_count: int = 13) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """分割手牌并返回 strip 内近似槽位。"""
        fallback: tuple[list[np.ndarray], list[tuple[int, int, int, int]]] | None = None
        for segmenter in (
            self._segment_tiles_by_face_components,
            self._segment_tiles_by_low_white_runs,
            self._segment_tiles_by_gap_runs,
            self._segment_tiles_by_face_valleys,
        ):
            rois, slots = segmenter(strip, expected_count)
            if not self._is_acceptable_hand_roi_count(len(rois), expected_count):
                continue
            if expected_count >= 14:
                if len(rois) == 14:
                    if self._slots_are_width_stable(slots):
                        return rois, slots
                    if fallback is None:
                        fallback = (rois, slots)
                    continue
                if fallback is None:
                    fallback = (rois, slots)
                continue
            return rois, slots
        if fallback is not None:
            # For a detected 14-tile hand, a 13-ROI result is usually worse
            # than a stable equal-split fallback because it means one visible
            # tile vanished entirely (common on dark-faced sou tiles).
            if expected_count >= 14 and len(fallback[0]) != expected_count:
                rois = self._segment_tiles_equal_n(strip, expected_count)
                slots = self._estimate_slots_from_rois(strip, rois)
                if len(rois) == expected_count:
                    return rois, slots
            return fallback
        rois = self._segment_tiles(strip, expected_count)
        return rois, self._estimate_slots_from_rois(strip, rois)

    def _segment_tiles_by_face_components(
        self,
        strip: np.ndarray,
        expected_count: int,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """Segment raised/uneven hand tiles by individual white face components."""
        if strip is None or strip.size == 0 or len(strip.shape) != 3:
            return [], []
        h, w = strip.shape[:2]
        if h < 60 or w < 80:
            return [], []

        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        white = ((hsv[:, :, 2] > 135) & (hsv[:, :, 1] < 135)).astype(np.uint8) * 255
        white = cv2.morphologyEx(
            white,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        white = cv2.morphologyEx(
            white,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
        )

        n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(white)
        min_area = max(180, int(h * w * 0.006))
        raw_boxes: list[tuple[int, int, int, int, int]] = []
        for label in range(1, n_labels):
            x, y, bw, bh, area = [int(v) for v in stats[label]]
            if area < min_area:
                continue
            if bw < max(26, int(w * 0.018)) or bh < max(48, int(h * 0.35)):
                continue
            ratio = bw / max(1, bh)
            if ratio < 0.30 or ratio > 0.92:
                continue
            if y + bh < h * 0.35:
                continue
            raw_boxes.append((x, y, bw, bh, area))

        if len(raw_boxes) < 8:
            return [], []

        raw_boxes.sort(key=lambda b: b[0])
        widths = [bw for _x, _y, bw, _bh, _area in raw_boxes]
        heights = [bh for _x, _y, _bw, bh, _area in raw_boxes]
        med_w = float(np.median(widths))
        med_h = float(np.median(heights))
        if med_w <= 0 or med_h <= 0:
            return [], []

        boxes: list[tuple[int, int, int, int]] = []
        for x, y, bw, bh, _area in raw_boxes:
            if bw < med_w * 0.45 or bw > med_w * 1.55:
                continue
            if bh < med_h * 0.55 or bh > med_h * 1.45:
                continue
            boxes.append((x, y, bw, bh))

        if not self._is_acceptable_hand_roi_count(len(boxes), expected_count):
            logger.info(
                "[Frame %d] 连通块切牌数量异常: raw=%d kept=%d expected=%d widths=%s",
                self._frame_index, len(raw_boxes), len(boxes), expected_count, widths,
            )
            return [], []

        centers = [x + bw / 2 for x, _y, bw, _bh in boxes]
        rois: list[np.ndarray] = []
        slots: list[tuple[int, int, int, int]] = []
        for i, (x, y, bw, bh) in enumerate(boxes):
            left_limit = 0 if i == 0 else int((centers[i - 1] + centers[i]) / 2)
            right_limit = w if i == len(boxes) - 1 else int((centers[i] + centers[i + 1]) / 2)
            pad_x = max(1, min(4, int(bw * 0.04)))
            pad_y = max(2, int(bh * 0.08))
            x1 = max(left_limit, x - pad_x)
            x2 = min(right_limit, x + bw + pad_x)
            y1 = max(0, y - pad_y)
            y2 = min(h, y + bh + pad_y)
            roi = strip[y1:y2, x1:x2]
            if not self._is_single_tile_roi(roi):
                logger.info(
                    "[Frame %d] 连通块切牌 ROI 质检失败: slot=%d x=%d y=%d w=%d h=%d",
                    self._frame_index, i, x1, y1, x2 - x1, y2 - y1,
                )
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))

        logger.info("[Frame %d] 连通块切牌: %d 个 ROI", self._frame_index, len(rois))
        return rois, slots

    def _segment_tiles_by_low_white_runs(
        self,
        strip: np.ndarray,
        expected_count: int,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """Split only real white-face runs, never synthesize a slot inside a green gap."""
        if strip is None or strip.size == 0 or len(strip.shape) != 3:
            return [], []
        h, w = strip.shape[:2]
        if h < 60 or w < 80:
            return [], []

        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        y_top = int(h * 0.18)
        y_bottom = int(h * 0.96)
        band = hsv[y_top:y_bottom]
        white = ((band[:, :, 2] > 135) & (band[:, :, 1] < 155)).astype(np.float32)
        col = cv2.GaussianBlur(white.mean(axis=0).reshape(1, -1), (1, 5), 0).reshape(-1)

        active = col > 0.10
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for i, v in enumerate(active):
            if v and start is None:
                start = i
            elif not v and start is not None:
                runs.append((start, i))
                start = None
        if start is not None:
            runs.append((start, w))
        runs = [(s, e) for s, e in runs if e - s >= 24]
        if len(runs) < 8:
            return [], []

        widths = [e - s for s, e in runs]
        narrow = [rw for rw in widths if rw <= np.percentile(widths, 55)]
        tile_w = float(np.median(narrow or widths))
        if tile_w <= 0:
            return [], []

        split_runs: list[tuple[int, int]] = []
        for s, e in runs:
            rw = e - s
            n_sub = max(1, int(round(rw / tile_w)))
            n_sub = min(4, n_sub)
            sub_w = rw / n_sub
            for j in range(n_sub):
                ss = int(round(s + j * sub_w))
                ee = int(round(s + (j + 1) * sub_w))
                if ee - ss >= max(24, int(tile_w * 0.45)):
                    split_runs.append((ss, ee))

        if not self._is_acceptable_hand_roi_count(len(split_runs), expected_count):
            logger.info(
                "[Frame %d] 低阈值白run切牌数量异常: runs=%d split=%d expected=%d widths=%s tile_w=%.1f",
                self._frame_index, len(runs), len(split_runs), expected_count, widths, tile_w,
            )
            return [], []

        rows = np.where(white[:, max(0, split_runs[0][0]):min(w, split_runs[-1][1])].mean(axis=1) > 0.08)[0]
        if len(rows) >= 10:
            y1 = max(0, y_top + int(rows[0]) - int(h * 0.06))
            y2 = min(h, y_top + int(rows[-1]) + 1 + int(h * 0.06))
        else:
            y1 = max(0, int(h * 0.02))
            y2 = min(h, int(h * 0.98))

        rois: list[np.ndarray] = []
        slots: list[tuple[int, int, int, int]] = []
        for s, e in split_runs:
            pad = max(1, min(3, int((e - s) * 0.02)))
            x1 = max(0, s + pad)
            x2 = min(w, e - pad)
            if x2 <= x1:
                return [], []
            roi = strip[y1:y2, x1:x2]
            if not self._is_single_tile_roi(roi):
                logger.info(
                    "[Frame %d] 低阈值白run ROI质检失败: x=%d w=%d",
                    self._frame_index, x1, x2 - x1,
                )
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))

        logger.info("[Frame %d] 低阈值白run切牌: %d 个 ROI", self._frame_index, len(rois))
        return rois, slots

    def _is_acceptable_hand_roi_count(self, count: int, expected_count: int) -> bool:
        if count <= 0:
            return False
        # With no self melds, a visible Mahjong hand should be 13 or 14.
        # Accepting 12 here silently drops the last tile, which is worse than
        # falling back to another segmentation strategy.
        if expected_count >= 13:
            return count in (13, 14)
        return 10 <= count <= 15 and abs(count - expected_count) <= 1

    @staticmethod
    def _slots_are_width_stable(slots: list[tuple[int, int, int, int]]) -> bool:
        if len(slots) < 8:
            return False
        widths = np.array([max(1, s[2]) for s in slots], dtype=np.float32)
        med = float(np.median(widths))
        if med <= 0:
            return False
        return bool(widths.min() >= med * 0.78 and widths.max() <= med * 1.28)

    def _estimate_slots_from_rois(self, strip: np.ndarray, rois: list[np.ndarray]) -> list[tuple[int, int, int, int]]:
        if strip is None or strip.size == 0 or not rois:
            return []
        h, w = strip.shape[:2]
        total_roi_w = sum(max(1, roi.shape[1]) for roi in rois)
        if total_roi_w <= 0:
            return []
        slots: list[tuple[int, int, int, int]] = []
        cursor = 0.0
        scale = w / total_roi_w
        for roi in rois:
            rw = max(1, int(round(roi.shape[1] * scale)))
            rh = min(h, max(1, roi.shape[0]))
            x = min(w - 1, int(round(cursor)))
            y = max(0, (h - rh) // 2)
            if x + rw > w:
                rw = max(1, w - x)
            slots.append((x, y, rw, rh))
            cursor += roi.shape[1] * scale
        return slots

    def _segment_tiles_by_gap_runs(
        self,
        strip: np.ndarray,
        expected_count: int,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """Segment by actual green gaps between adjacent white tile faces.

        This uses the visible fact the user pointed out: adjacent tiles have a
        narrow dark-green vertical gap. We first find high-white runs around
        tile bodies, then use low-white runs as boundaries. It does not depend
        on equal-width drift.
        """
        if strip is None or strip.size == 0 or expected_count <= 0:
            return [], []
        if len(strip.shape) != 3 or strip.shape[2] != 3:
            return [], []

        h, w = strip.shape[:2]
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        y_top = int(h * 0.20)
        y_bottom = int(h * 0.92)
        band = hsv[y_top:y_bottom]
        if band.size == 0:
            return [], []

        white = ((band[:, :, 2] > 140) & (band[:, :, 1] < 130)).astype(np.float32)
        col = white.mean(axis=0)
        col = cv2.GaussianBlur(col.reshape(1, -1), (1, 5), 0).reshape(-1)

        active = col > 0.20
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for i, v in enumerate(active):
            if v and start is None:
                start = i
            elif not v and start is not None:
                runs.append((start, i))
                start = None
        if start is not None:
            runs.append((start, w))

        # Keep even 2px gaps: in this game adjacent tiles often have only a
        # very narrow green seam, and merging those seams recreates cross-tile
        # ROIs. Glyph holes were already removed by the minimum run width.
        min_tile_w = max(28, int(w / 30))
        merged: list[tuple[int, int]] = []
        for s, e in runs:
            if e - s < min_tile_w:
                continue
            merged.append((s, e))

        if len(merged) < 8:
            logger.info(
                "[Frame %d] 缝隙分割失败: runs=%d expected=%d",
                self._frame_index, len(merged), expected_count,
            )
            return [], []

        widths = [e - s for s, e in merged]
        med_w = float(np.median([rw for rw in widths if rw <= np.percentile(widths, 65)] or widths))
        if med_w <= 0:
            return [], []

        split_runs: list[tuple[int, int]] = []
        for s, e in merged:
            rw = e - s
            if rw < med_w * 0.50:
                continue
            n_sub = 1
            if rw > med_w * 1.45:
                n_sub = max(1, min(3, int(round(rw / med_w))))
            sub_w = rw / n_sub
            for j in range(n_sub):
                ss = int(round(s + j * sub_w))
                ee = int(round(s + (j + 1) * sub_w))
                if ee - ss >= med_w * 0.50:
                    split_runs.append((ss, ee))

        if not (10 <= len(split_runs) <= 15 and abs(len(split_runs) - expected_count) <= 1):
            logger.info(
                "[Frame %d] 缝隙分割数量异常: runs=%d split=%d expected=%d widths=%s med=%.1f",
                self._frame_index, len(merged), len(split_runs), expected_count, widths, med_w,
            )
            return [], []
        merged = split_runs

        # Determine vertical crop from white pixels in all accepted runs.
        rows_mask = white[:, max(0, merged[0][0]):min(w, merged[-1][1])].mean(axis=1)
        rows = np.where(rows_mask > 0.10)[0]
        if len(rows) >= 10:
            y1 = max(0, y_top + int(rows[0]) - int(h * 0.06))
            y2 = min(h, y_top + int(rows[-1]) + 1 + int(h * 0.06))
        else:
            y1 = max(0, int(h * 0.02))
            y2 = min(h, int(h * 0.98))

        rois: list[np.ndarray] = []
        slots: list[tuple[int, int, int, int]] = []
        gaps = [max(1, merged[i + 1][0] - merged[i][1]) for i in range(len(merged) - 1)]
        gap_med = int(np.median(gaps)) if gaps else 4
        for s, e in merged:
            gap_left = gap_med
            pad = max(1, min(4, int(max(1, gap_left) * 0.35)))
            x1 = max(0, s - pad)
            x2 = min(w, e + pad)
            roi = strip[y1:y2, x1:x2]
            if not self._is_single_tile_roi(roi):
                logger.info("[Frame %d] 缝隙分割 ROI 质检失败: x=%d w=%d", self._frame_index, x1, x2 - x1)
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))

        if self._debug_dir:
            vis = strip.copy()
            for x, y, tw, th in slots:
                cv2.rectangle(vis, (x, y), (x + tw, y + th), (0, 180, 255), 2)
            cv2.imwrite(os.path.join(self._debug_dir, "hand_strips", f"f{self._frame_index}_gap_runs.png"), vis)
        logger.info("[Frame %d] 缝隙分割: %d 个 ROI", self._frame_index, len(rois))
        return rois, slots

    def _is_single_tile_roi(self, roi: np.ndarray) -> bool:
        """Reject ROIs that obviously contain two tile bodies or only a sliver."""
        if roi is None or roi.size == 0 or len(roi.shape) != 3:
            return False
        h, w = roi.shape[:2]
        if h < 50 or w < 25:
            return False
        ratio = w / max(1, h)
        if ratio < 0.32 or ratio > 0.92:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        band = hsv[int(h * 0.22):int(h * 0.92)]
        if band.size == 0:
            return False
        white = ((band[:, :, 2] > 132) & (band[:, :, 1] < 145)).astype(np.float32)
        col = white.mean(axis=0)
        if float(col.mean()) < 0.22:
            return False
        low = col < 0.08
        longest = 0
        cur = 0
        for v in low:
            cur = cur + 1 if v else 0
            longest = max(longest, cur)
        # A clear internal dark gap means the ROI still spans two tiles.
        return longest < max(4, int(w * 0.08))

    def _segment_tiles_by_face_valleys(
        self,
        strip: np.ndarray,
        expected_count: int,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """Segment hand tiles by face bounds and dark gaps.

        The previous component splitter could be shifted by stickers such as
        "财" attached to the first tile, then every equal split crossed tile
        borders. This method ignores the top decoration band and searches for
        dark valleys near each expected tile boundary.
        """
        if strip is None or strip.size == 0 or expected_count <= 0:
            return [], []
        if len(strip.shape) != 3 or strip.shape[2] != 3:
            return [], []

        h, w = strip.shape[:2]
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        y_top = int(h * 0.18)
        y_bottom = int(h * 0.96)
        band = hsv[y_top:y_bottom, :, :]
        if band.size == 0:
            return [], []

        white = ((band[:, :, 2] > 135) & (band[:, :, 1] < 135)).astype(np.float32)
        col = white.mean(axis=0)
        col = cv2.GaussianBlur(col.reshape(1, -1), (1, 5), 0).reshape(-1)
        active = np.where(col > 0.16)[0]
        if len(active) < max(50, expected_count * 20):
            return [], []

        x_left = int(active[0])
        x_right = int(active[-1]) + 1
        face_w = x_right - x_left
        if face_w < expected_count * 25:
            return [], []

        step = face_w / expected_count
        boundaries = [x_left]
        for i in range(1, expected_count):
            target = x_left + i * step
            radius = max(5, int(step * 0.28))
            lo = max(x_left + 1, int(target - radius))
            hi = min(x_right - 1, int(target + radius))
            if hi <= lo:
                boundaries.append(int(round(target)))
                continue
            # Prefer the darkest/least-white column near the expected border.
            region = col[lo:hi]
            min_val = float(region.min())
            candidates = np.where(region <= min_val + 0.015)[0]
            if len(candidates):
                # Pick the valley closest to the expected boundary.
                best_rel = min(candidates, key=lambda r: abs((lo + int(r)) - target))
                boundaries.append(lo + int(best_rel))
            else:
                boundaries.append(int(round(target)))
        boundaries.append(x_right)
        boundaries = sorted(boundaries)

        rois: list[np.ndarray] = []
        slots: list[tuple[int, int, int, int]] = []
        y1 = max(0, int(h * 0.02))
        y2 = min(h, int(h * 0.98))
        for i in range(len(boundaries) - 1):
            sx1, sx2 = boundaries[i], boundaries[i + 1]
            tw = sx2 - sx1
            if tw < max(24, int(step * 0.45)) or tw > int(step * 1.70):
                return [], []
            pad_x = max(1, int(tw * 0.025))
            x1 = max(0, sx1 + pad_x)
            x2 = min(w, sx2 - pad_x)
            if x2 <= x1:
                return [], []
            rois.append(strip[y1:y2, x1:x2])
            slots.append((x1, y1, x2 - x1, y2 - y1))

        if self._debug_dir:
            vis = strip.copy()
            for x, y, tw, th in slots:
                cv2.rectangle(vis, (x, y), (x + tw, y + th), (0, 255, 255), 2)
            vis_path = os.path.join(self._debug_dir, "hand_strips", f"f{self._frame_index}_face_valleys.png")
            cv2.imwrite(vis_path, vis)
        logger.info("[Frame %d] 牌面暗谷分割: %d 个 ROI", self._frame_index, len(rois))
        return rois, slots

    def _segment_tiles(self, strip: np.ndarray, expected_count: int = 13) -> list[np.ndarray]:
        """从手牌区域条带中分割每张牌。三层策略：白色块→梯度→等分。"""
        if strip is None or strip.size == 0:
            logger.warning("[Frame %d] 手牌 strip 为空", self._frame_index)
            return []

        h, w = strip.shape[:2]

        # ── 策略1: 白色块分割（最可靠，对绿色背景鲁棒）──────────────────────
        component_rois, component_slots = self._segment_tiles_by_white_components(strip)
        if len(component_rois) == expected_count:
            logger.info(
                "[Frame %d] 白色牌块分割: %d 个 ROI (strip=%dx%d)",
                self._frame_index, len(component_rois), w, h,
            )
            if self._debug_dir:
                vis = strip.copy()
                for x, y, tw, th in component_slots:
                    cv2.rectangle(vis, (x, y), (x + tw, y + th), (255, 0, 255), 2)
                vis_path = os.path.join(self._debug_dir, "hand_strips", f"f{self._frame_index}_ccseg.png")
                cv2.imwrite(vis_path, vis)
            return component_rois
        if len(component_rois) >= 10:
            logger.info(
                "[Frame %d] component segmentation mismatch: got=%d expected=%d",
                self._frame_index, len(component_rois), expected_count,
            )

        # ── 策略2: Sobel X 梯度分割（颜色无关，依赖垂直边缘）──────────────
        rois = self._segment_tiles_by_gradient(strip)
        if len(rois) == expected_count:
            logger.info("[Frame %d] 梯度分割: %d 个 ROI (strip=%dx%d)", self._frame_index, len(rois), w, h)
            return rois
        if len(rois) >= 10:
            logger.info(
                "[Frame %d] gradient segmentation mismatch: got=%d expected=%d",
                self._frame_index, len(rois), expected_count,
            )

        # ── 策略3: 已知牌数等分（最可靠兜底）──────────────────────────────
        rois = self._segment_tiles_equal_n(strip, expected_count)
        logger.info(
            "[Frame %d] 等分分割(%d张): %d 个 ROI (strip=%dx%d)",
            self._frame_index, expected_count, len(rois), w, h,
        )
        return rois

    def _segment_tiles_by_gradient(self, strip: np.ndarray) -> list[np.ndarray]:
        """Sobel X 梯度分割：颜色无关，靠垂直边缘检测牌与牌之间的边界。"""
        if strip is None or strip.size == 0:
            return []
        h, w = strip.shape[:2]

        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) if len(strip.shape) == 3 else strip.copy()

        # Sobel X：检测垂直方向的亮度跳变（牌缝处有明显跳变）
        sobel = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
        col_edge = np.abs(sobel).mean(axis=0)
        col_edge = cv2.GaussianBlur(col_edge.reshape(1, -1), (1, 7), 0).reshape(-1)

        # 先找牌区左右边界（支持白色/暗色牌面），仅在该区间内找分割点
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV) if len(strip.shape) == 3 else None
        if hsv is not None:
            v_mean = int(hsv[:, :, 2].mean())
            if v_mean > 120:
                # 亮色界面：白色牌面
                white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
                tile_pixels = np.where(white_col > 0.3)[0]
            else:
                # 暗色界面：找有内容的区域
                content_col = ((hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 40)).mean(axis=0)
                tile_pixels = np.where(content_col > 0.25)[0]
        else:
            tile_pixels = np.arange(w)
        if len(tile_pixels) < 60:
            return []
        x_left, x_right = int(tile_pixels[0]), int(tile_pixels[-1]) + 1
        tile_w = x_right - x_left

        # 估算单牌宽，设置最小峰间距
        est_tile_w = tile_w / 14  # 最多14张
        min_dist = max(int(est_tile_w * 0.55), 25)

        # 在牌区内找梯度局部极大值
        edge_region = col_edge[x_left:x_right]
        threshold = float(np.percentile(edge_region, 70))
        peaks = []
        last = -min_dist
        for i in range(1, len(edge_region) - 1):
            if edge_region[i] >= edge_region[i - 1] and edge_region[i] >= edge_region[i + 1]:
                if edge_region[i] > threshold:
                    rel = i + x_left
                    if rel - last >= min_dist:
                        peaks.append(rel)
                        last = rel
                    elif col_edge[rel] > col_edge[peaks[-1]]:
                        peaks[-1] = rel
                        last = rel

        boundaries = sorted(set([x_left] + peaks + [x_right]))
        min_rw = max(tile_w // 20, 25)
        max_rw = max(tile_w // 4, 200)

        # 计算各段宽度，用中位数检测宽段（2张合并）
        seg_widths = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)
                      if min_rw <= boundaries[i + 1] - boundaries[i] <= max_rw]
        med_w = float(np.median(seg_widths)) if seg_widths else est_tile_w

        rois = []
        pad_y = max(2, int(h * 0.06))
        for i in range(len(boundaries) - 1):
            rx1, rx2 = boundaries[i], boundaries[i + 1]
            rw = rx2 - rx1
            if rw < min_rw or rw > max_rw:
                continue
            n_sub = round(rw / med_w) if rw > med_w * 1.45 else 1
            n_sub = max(1, min(n_sub, 3))
            sub_w = rw / n_sub
            for j in range(n_sub):
                sx1 = int(rx1 + j * sub_w)
                sx2 = int(rx1 + (j + 1) * sub_w)
                pad_x = max(2, int((sx2 - sx1) * 0.04))
                roi = strip[pad_y:h - pad_y, sx1 + pad_x:sx2 - pad_x]
                if roi.size > 0:
                    rois.append(roi)

        logger.debug("[Frame %d] 梯度分割原始: peaks=%d segs=%d rois=%d", self._frame_index, len(peaks), len(boundaries) - 1, len(rois))
        return rois

    def _segment_tiles_equal_n(self, strip: np.ndarray, n: int) -> list[np.ndarray]:
        """把手牌区域等分为 n 张牌（最可靠的兜底方案）。

        先定位牌区左右边界（支持白色牌面和暗色牌面），再在该区间内等分。
        """
        if strip is None or strip.size == 0 or n <= 0:
            return []
        h, w = strip.shape[:2]

        # 找牌区边界：先尝试白色牌面，再尝试暗色牌面
        if len(strip.shape) == 3:
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            # 策略A：白色牌面（亮色界面）
            white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
            tile_pixels = np.where(white_col > 0.3)[0]
            if len(tile_pixels) >= 60:
                x_left = int(tile_pixels[0])
                x_right = int(tile_pixels[-1]) + 1
            else:
                # 策略B：暗色牌面（暗色界面）—— 找有内容的区域（非纯黑背景）
                content_col = ((hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 40)).mean(axis=0)
                content_pixels = np.where(content_col > 0.25)[0]
                if len(content_pixels) >= 60:
                    x_left = int(content_pixels[0])
                    x_right = int(content_pixels[-1]) + 1
                else:
                    x_left, x_right = 0, w
        else:
            tile_pixels = np.where(strip.mean(axis=0) > 40)[0]
            if len(tile_pixels) >= 60:
                x_left = int(tile_pixels[0])
                x_right = int(tile_pixels[-1]) + 1
            else:
                x_left, x_right = 0, w

        tile_w = x_right - x_left
        single_w = tile_w / n
        pad_x = max(2, int(single_w * 0.04))
        pad_y = max(2, int(h * 0.06))

        rois = []
        for i in range(n):
            sx1 = int(x_left + i * single_w)
            sx2 = int(x_left + (i + 1) * single_w)
            roi = strip[pad_y:h - pad_y, sx1 + pad_x:sx2 - pad_x]
            if roi.size > 0:
                rois.append(roi)
        return rois

    def _segment_tiles_by_white_components(self, strip: np.ndarray) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """Segment visible hand tiles from white or dark tile faces.

        Brightness valleys are fragile when tiles touch or when green glow/text
        sits on top of the hand. This detector first finds continuous tile
        blocks (white or dark), then splits wide blocks by the observed tile aspect ratio.
        """
        if strip is None or strip.size == 0:
            return [], []
        h, w = strip.shape[:2]
        if len(strip.shape) != 3 or strip.shape[2] != 3:
            return [], []

        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        v_mean = int(hsv[:, :, 2].mean())

        if v_mean > 120:
            # 亮色界面：白色牌面
            mask = ((hsv[:, :, 2] > 145) & (hsv[:, :, 1] < 90)).astype(np.uint8) * 255
        else:
            # 暗色界面：找有内容的区域（非纯黑背景）
            mask = ((hsv[:, :, 1] > 25) & (hsv[:, :, 2] > 35)).astype(np.uint8) * 255

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))

        n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
        clusters: list[tuple[int, int, int, int, int]] = []
        min_area = max(900, int(h * w * 0.002))
        for label in range(1, n_labels):
            x, y, bw, bh, area = [int(v) for v in stats[label]]
            if area < min_area:
                continue
            if bh < max(55, int(h * 0.45)) or bw < 30:
                continue
            if y < int(h * 0.03) and bh < int(h * 0.55):
                continue
            clusters.append((x, y, bw, bh, area))

        clusters.sort(key=lambda b: b[0])
        rois: list[np.ndarray] = []
        slots: list[tuple[int, int, int, int]] = []

        for x, y, bw, bh, _area in clusters:
            # 手牌 ROI 实测宽高比约 0.70，过大会把切口落在两张牌中间。
            est_tile_w = max(40.0, bh * 0.70)
            n_tiles = max(1, int(round(bw / est_tile_w)))
            if n_tiles > 15:
                continue
            tile_w = bw / n_tiles
            for i in range(n_tiles):
                sx1 = int(round(x + i * tile_w))
                sx2 = int(round(x + (i + 1) * tile_w))
                if sx2 - sx1 < max(30, int(est_tile_w * 0.45)):
                    continue
                pad_x = max(1, int((sx2 - sx1) * 0.02))
                pad_y = max(2, int(bh * 0.04))
                x1 = max(0, sx1 + pad_x)
                x2 = min(w, sx2 - pad_x)
                y1 = max(0, y - pad_y)
                y2 = min(h, y + bh + pad_y)
                if x2 <= x1 or y2 <= y1:
                    continue
                rois.append(strip[y1:y2, x1:x2])
                slots.append((x1, y1, x2 - x1, y2 - y1))

        return rois, slots

    def _segment_tiles_equal(self, strip: np.ndarray) -> tuple[list[np.ndarray], list[tuple]]:
        """等分切割回退方案：将 strip 横向等分为 N 张牌。

        用于亮度投影分割失败时（牌面与背景亮度差异太小、暗色界面等场景）。
        通过 HSV V 通道大窗口平滑检测牌面区域范围，然后在范围内等分。
        """
        h, w = strip.shape[:2]

        # 使用 V 通道做列投影
        if len(strip.shape) == 3 and strip.shape[2] == 3:
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            col_v = hsv[:, :, 2].astype(np.float32).mean(axis=0)
        else:
            col_v = strip.astype(np.float32).mean(axis=0)

        # 大窗口平滑，找到牌面整体区域（亮区 + 暗手牌区都是"有内容"的区域）
        col_smooth = cv2.GaussianBlur(col_v.reshape(1, -1), (1, min(w // 4, 81) | 1), 0).reshape(-1)

        # 找牌面区域：平滑后亮度高于"纯背景"的连续段
        # 纯背景 = 整条 strip 中最低的10%亮度的均值
        sorted_v = np.sort(col_smooth)
        bg_level = sorted_v[:max(len(sorted_v) // 10, 1)].mean()
        zone_threshold = bg_level * 1.5 + 5  # 背景的1.5倍+5作为阈值

        tile_zones = []
        in_zone = False
        zone_start = 0
        for i, v in enumerate(col_smooth):
            if v >= zone_threshold:
                if not in_zone:
                    zone_start = i
                    in_zone = True
            else:
                if in_zone:
                    tile_zones.append((zone_start, i))
                    in_zone = False
        if in_zone:
            tile_zones.append((zone_start, w))

        # 合并相近的 zone（间距小于一张牌宽度的合并）
        est_tile_w = max(w // 14, 30)
        if tile_zones:
            merged = [tile_zones[0]]
            for s, e in tile_zones[1:]:
                prev_s, prev_e = merged[-1]
                if s - prev_e < est_tile_w:
                    merged[-1] = (prev_s, e)
                else:
                    merged.append((s, e))
            tile_zones = merged

        logger.info(
            "[Frame %d] 等分切割: bg_level=%.1f, zone_threshold=%.1f, zones=%d",
            self._frame_index, bg_level, zone_threshold, len(tile_zones),
        )

        # 在每个 zone 内等分切牌
        rois = []
        slot_info = []
        top_crop = max(3, int(h * 0.08))
        bottom_crop = max(3, int(h * 0.06))

        for zs, ze in tile_zones:
            zone_w = ze - zs
            if zone_w < est_tile_w * 0.8:
                continue  # 太窄，跳过

            n_tiles = max(1, round(zone_w / est_tile_w))
            tile_w = zone_w / n_tiles

            # 在 zone 内的细粒度亮度投影，微调每张牌的边界
            zone_col = col_v[zs:ze]
            zone_col_smooth = cv2.GaussianBlur(
                zone_col.reshape(1, -1), (1, 9), 0
            ).reshape(-1)

            for ti in range(n_tiles):
                eq_start = int(ti * tile_w)
                eq_end = int((ti + 1) * tile_w)

                # 在等分边界附近找亮度谷值微调
                search = max(int(tile_w * 0.15), 3)

                # 左边界微调
                ls = max(0, eq_start - search)
                le = min(len(zone_col_smooth), eq_start + search)
                if le > ls:
                    left_adj = ls + int(np.argmin(zone_col_smooth[ls:le]))
                else:
                    left_adj = eq_start

                # 右边界微调
                rs = max(0, eq_end - search)
                re = min(len(zone_col_smooth), eq_end + search)
                if re > rs:
                    right_adj = rs + int(np.argmin(zone_col_smooth[rs:re]))
                else:
                    right_adj = eq_end

                abs_left = zs + left_adj
                abs_right = zs + right_adj
                tw = abs_right - abs_left
                if tw < est_tile_w * 0.5:
                    continue  # 太窄

                # 水平裁剪（去除边缘）
                left_crop = max(2, int(tw * 0.04))
                right_crop = max(2, int(tw * 0.04))
                x1c = abs_left + left_crop
                x2c = abs_right - right_crop
                y1 = top_crop
                y2 = h - bottom_crop

                if x2c > x1c and y2 > y1:
                    rois.append(strip[y1:y2, x1c:x2c])
                    slot_info.append((x1c, y1, x2c - x1c, y2 - y1))

        logger.info(
            "[Frame %d] 等分切割结果: zones=%d, ROIs=%d",
            self._frame_index, len(tile_zones), len(rois),
        )

        # Debug 可视化
        if self._debug_dir:
            vis = strip.copy()
            for x1c, y1c, tw, th in slot_info:
                cv2.rectangle(vis, (x1c, y1c), (x1c + tw, y1c + th), (0, 255, 255), 2)
            vis_path = os.path.join(self._debug_dir, "hand_strips", f"f{self._frame_index}_eqseg.png")
            cv2.imwrite(vis_path, vis)

        return rois, slot_info

    def _detect_tile_count(self, frame: np.ndarray, meld_count: int) -> int:
        """横向亮度投影谷值法检测手牌数（13 或 14）。"""
        region = self._layout.hand_region(meld_count)
        roi = self._capture.grab_from_frame(frame, region)
        if roi.size == 0:
            return 13

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        # 按列求平均亮度
        col_mean = gray.mean(axis=0).astype(np.float32)
        # 高斯平滑
        col_mean = cv2.GaussianBlur(col_mean.reshape(1, -1), (1, 15), 0).reshape(-1)

        # 简单极小值检测：找低于局部均值的下凹点
        threshold = col_mean.mean() * 0.92
        valleys = 0
        min_slot_width = max(roi.shape[1] // 16, 5)
        last_valley = -min_slot_width
        in_valley = False

        for i, v in enumerate(col_mean):
            if v < threshold:
                if not in_valley and (i - last_valley) >= min_slot_width:
                    valleys += 1
                    last_valley = i
                    in_valley = True
            else:
                in_valley = False

        tile_count = valleys + 1
        # 限制在合理范围
        return max(13, min(14, tile_count))

    def _read_remaining_tiles(self, roi: np.ndarray) -> Optional[int]:
        """从剩余牌数区域读取数字（简单 OCR：找连通区域+比对数字模板）。"""
        if roi is None or roi.size == 0:
            return None
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        # 二值化
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # 读取白色像素比例估算数字（粗略方案，后续可替换为数字模板匹配）
        # 这里用简单方法：OCR 用 pytesseract 或数字模板
        # 暂时返回 None，等数字模板标定完成后替换
        return self._ocr_digits(gray)

    def _ocr_digits(self, gray_roi: np.ndarray) -> Optional[int]:
        """简单数字读取：数字模板匹配（0-9），两位数。"""
        # 数字模板目录（由标定工具在 buttons/ 下单独存放 digit_0.png ... digit_9.png）
        # 如果未标定，返回 None
        digit_templates = getattr(self, "_digit_templates", None)
        if digit_templates is None:
            return None
        # TODO: 实现数字模板匹配，当前返回 None
        return None

    def _infer_events(
        self,
        prev: Optional[GameState],
        curr: GameState,
    ) -> list[str]:
        """通过比对两帧状态推断发生的事件。"""
        if prev is None:
            return ["game_start"]

        events: list[str] = []
        ph = curr.hand_count if hasattr(curr, "hand_count") else len(curr.self_player.hand)
        pp = len(prev.self_player.hand)

        # 摸牌
        if ph == 14 and pp == 13:
            events.append("draw")
        # 出牌
        elif ph == 13 and pp == 14:
            events.append("discard")

        # 四家弃牌增长。格式保留座位和牌种，方便后续牌谱/防守逻辑读取。
        seat_discards = [
            ("self", curr.self_player.discards, prev.self_player.discards),
            ("right", curr.opponents[0].discards, prev.opponents[0].discards),
            ("across", curr.opponents[1].discards, prev.opponents[1].discards),
            ("left", curr.opponents[2].discards, prev.opponents[2].discards),
        ]
        for seat, curr_discards, prev_discards in seat_discards:
            if len(curr_discards) > len(prev_discards):
                new_tile = curr_discards[-1]
                events.append(f"{seat}_discard:{new_tile.tile_id or 'unknown'}")

        # 自家副露增加
        curr_meld_count = len(curr.self_player.melds)
        prev_meld_count = len(prev.self_player.melds)
        if curr_meld_count > prev_meld_count:
            new_meld = curr.self_player.melds[-1] if curr.self_player.melds else None
            if new_meld:
                events.append(new_meld.meld_type)  # "pon"/"chi"/"kan_open" etc.

        # 对手副露增加
        for i, (c_opp, p_opp) in enumerate(zip(curr.opponents, prev.opponents)):
            if len(c_opp.melds) > len(p_opp.melds):
                seat = c_opp.seat
                new_meld = c_opp.melds[-1] if c_opp.melds else None
                mtype = new_meld.meld_type if new_meld else "unknown"
                events.append(f"opp_{seat}_{mtype}")

        # 游戏阶段变化
        if curr.remaining_tiles != prev.remaining_tiles:
            events.append(f"remaining_changed:{prev.remaining_tiles}->{curr.remaining_tiles}")
        if curr.game_phase == PHASE_SHENGJIA and prev.game_phase == PHASE_PLAYING:
            events.append("shengjia_start")
        if curr.game_phase == PHASE_LIUJU and prev.game_phase != PHASE_LIUJU:
            events.append("round_end_draw")
        if curr.game_phase == PHASE_HUPAI and prev.game_phase != PHASE_HUPAI:
            events.append("round_end_win")

        # 决策按钮变化
        if curr.decision_prompt and not prev.decision_prompt:
            events.append("decision_prompt:" + ",".join(curr.decision_prompt))
        elif not curr.decision_prompt and prev.decision_prompt:
            # 区分"过"和"执行了动作"：按钮消失但没有副露增加也没有胡牌 → 过
            meld_added = len(curr.self_player.melds) > len(prev.self_player.melds)
            won = curr.game_phase == PHASE_HUPAI and prev.game_phase != PHASE_HUPAI
            if not meld_added and not won:
                events.append("pass")
            events.append("decision_prompt_cleared")
        elif curr.decision_prompt != prev.decision_prompt:
            events.append("decision_prompt_changed:" + ",".join(curr.decision_prompt))

        return events
