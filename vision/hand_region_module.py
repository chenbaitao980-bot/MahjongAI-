from __future__ import annotations

import json
import logging
import os

import cv2
import numpy as np

from game.session import GameSession

logger = logging.getLogger("mahjongai.hand_region")


def read_image(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return cv2.imread(path)


def prepare_trainable_hand_roi_image(img: np.ndarray) -> tuple[bool, np.ndarray | None, str]:
    if img is None or img.size == 0:
        return False, None, "empty"
    h, w = img.shape[:2]
    if h < 70 or w < 45:
        return False, None, f"too_small:{w}x{h}"
    ratio = w / max(1, h)
    if ratio < 0.42 or ratio > 0.92:
        return False, None, f"bad_ratio:{ratio:.2f}"

    bgr = img if len(img.shape) == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 2] > 135) & (hsv[:, :, 1] < 125)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    if float((white > 0).mean()) < 0.18:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        shadow = ((gray > 45) & (gray < 190) & (hsv[:, :, 1] < 170)).astype(np.uint8) * 255
        shadow = cv2.morphologyEx(shadow, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        shadow = cv2.morphologyEx(shadow, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
        if float((shadow > 0).mean()) > float((white > 0).mean()):
            white = shadow

    mid_band = white[int(h * 0.18):int(h * 0.92), :]
    if mid_band.size:
        col = (mid_band > 0).mean(axis=0)
        low = col < 0.08
        lo = int(w * 0.20)
        hi = int(w * 0.80)
        longest = 0
        cur = 0
        for v in low[lo:hi]:
            cur = cur + 1 if v else 0
            longest = max(longest, cur)
        if longest >= max(4, int(w * 0.06)):
            return False, None, f"internal_gap:{longest}px"

    n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(white)
    large: list[tuple[int, int, int, int, int]] = []
    for label in range(1, n_labels):
        x, y, bw, bh, area = [int(v) for v in stats[label]]
        if area < h * w * 0.12:
            continue
        if bh < h * 0.55 or bw < w * 0.25:
            continue
        large.append((x, y, bw, bh, area))

    if not large:
        return False, None, "no_tile_face"
    large.sort(key=lambda item: item[4], reverse=True)
    x, y, bw, bh, area = large[0]
    if len(large) >= 2 and large[1][4] > area * 0.55:
        return False, None, f"multiple_tile_faces:{len(large)}"
    if bw < w * 0.48 or bh < h * 0.66:
        return False, None, f"incomplete_face:{bw}x{bh}"
    cx = x + bw / 2
    if cx < w * 0.30 or cx > w * 0.70:
        return False, None, f"off_center:{cx / w:.2f}"
    pad_x = max(1, int(bw * 0.03))
    pad_y = max(1, int(bh * 0.03))
    x1 = max(0, x - pad_x)
    x2 = min(w, x + bw + pad_x)
    y1 = max(0, y - pad_y)
    y2 = min(h, y + bh + pad_y)
    crop = bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return False, None, "empty_crop"
    return True, crop, "ok"


class HandRegionModule:
    def detect_tile_count(self, frame: np.ndarray, meld_count: int, layout, capture) -> int:
        region = layout.hand_region(meld_count)
        roi = capture.grab_from_frame(frame, region)
        if roi.size == 0:
            return 13
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        col_mean = gray.mean(axis=0).astype(np.float32)
        col_mean = cv2.GaussianBlur(col_mean.reshape(1, -1), (1, 15), 0).reshape(-1)
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
        return max(13, min(14, tile_count))

    def segment_tiles_with_slots(
        self,
        strip: np.ndarray,
        expected_count: int = 13,
        frame_index: int = 0,
        debug_dir: str | None = None,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        fallback: tuple[list[np.ndarray], list[tuple[int, int, int, int]]] | None = None
        for segmenter in (
            self._segment_tiles_by_face_components,
            self._segment_tiles_by_low_white_runs,
            self._segment_tiles_by_gap_runs,
            self._segment_tiles_by_face_valleys,
        ):
            rois, slots = segmenter(strip, expected_count, frame_index, debug_dir)
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
            if expected_count >= 14 and len(fallback[0]) != expected_count:
                rois = self._segment_tiles_equal_n(strip, expected_count)
                slots = self._estimate_slots_from_rois(strip, rois)
                if len(rois) == expected_count:
                    return rois, slots
            return fallback
        rois = self._segment_tiles(strip, expected_count, frame_index, debug_dir)
        return rois, self._estimate_slots_from_rois(strip, rois)

    def collect_training_roi_paths(
        self,
        data_root: str,
        capture_interval: int,
        layout,
        capture,
    ) -> list[str]:
        pool_dir = os.path.join(data_root, "training_roi_pool")
        os.makedirs(pool_dir, exist_ok=True)
        processed_path = os.path.join(pool_dir, "processed_sources.json")
        try:
            with open(processed_path, "r", encoding="utf-8") as f:
                processed_sources = set(json.load(f))
        except (OSError, ValueError, TypeError):
            processed_sources = set()

        for name in os.listdir(pool_dir):
            path = os.path.join(pool_dir, name)
            if os.path.isfile(path) and name.endswith(".png") and name.startswith("roi_"):
                try:
                    os.remove(path)
                except OSError:
                    pass

        frames_per_batch = max(1, int(round(10000 / max(1, capture_interval))))
        copied: list[str] = []
        sessions = GameSession.list_sessions(data_root)
        if not sessions:
            return []

        for session_name in sessions[:1]:
            key_dir = os.path.join(data_root, session_name, "keyframes")
            if os.path.isdir(key_dir):
                keyframes = [
                    name for name in sorted(os.listdir(key_dir))
                    if name.startswith("frame_") and name.endswith(".png")
                ]
                for kname in keyframes:
                    try:
                        frame_index = int(os.path.splitext(kname)[0].split("_", 1)[1])
                    except (IndexError, ValueError):
                        frame_index = 0
                    source_key = f"{session_name}:{os.path.splitext(kname)[0]}"
                    if source_key in processed_sources:
                        continue
                    if frame_index % frames_per_batch != 0 and copied:
                        continue
                    frame = read_image(os.path.join(key_dir, kname))
                    if frame is None:
                        continue
                    hand_rect = layout.hand_region(0)
                    strip = capture.grab_from_frame(frame, hand_rect)
                    rois, _slots = self.segment_tiles_with_slots(strip, 14)
                    for idx, roi in enumerate(rois):
                        ok, clean_img, _reason = prepare_trainable_hand_roi_image(roi)
                        if not ok or clean_img is None:
                            continue
                        dst = os.path.join(
                            pool_dir,
                            f"roi_{session_name}_{os.path.splitext(kname)[0]}_recut_{idx}.png",
                        )
                        if cv2.imwrite(dst, clean_img):
                            copied.append(dst)
                if copied:
                    return sorted(copied)

            rec_dir = os.path.join(data_root, session_name, "recognition")
            if not os.path.isdir(rec_dir):
                continue
            frame_names = [
                name for name in sorted(os.listdir(rec_dir))
                if name.startswith("frame_") and os.path.isdir(os.path.join(rec_dir, name))
            ]
            selected_frames = []
            for name in frame_names:
                try:
                    frame_index = int(name.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                if frame_index % frames_per_batch == 0:
                    selected_frames.append(name)
            if not selected_frames and frame_names:
                selected_frames = [frame_names[0]]

            for frame_name in selected_frames:
                source_key = f"{session_name}:{frame_name}"
                if source_key in processed_sources:
                    continue
                frame_dir = os.path.join(rec_dir, frame_name)
                for fname in sorted(os.listdir(frame_dir)):
                    if not fname.startswith("roi_") or not fname.endswith(".png"):
                        continue
                    if fname.endswith("_annotated.png"):
                        continue
                    src = os.path.join(frame_dir, fname)
                    img = cv2.imread(src)
                    ok, clean_img, _reason = prepare_trainable_hand_roi_image(img)
                    if not ok or clean_img is None:
                        continue
                    dst = os.path.join(pool_dir, f"roi_{session_name}_{frame_name}_{fname}")
                    if not os.path.exists(dst):
                        try:
                            cv2.imwrite(dst, clean_img)
                        except Exception:
                            continue
                    copied.append(dst)
        return sorted(copied)

    def _is_acceptable_hand_roi_count(self, count: int, expected_count: int) -> bool:
        if count <= 0:
            return False
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

    def _segment_tiles_by_face_components(self, strip: np.ndarray, expected_count: int, frame_index: int, debug_dir: str | None) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        if strip is None or strip.size == 0 or len(strip.shape) != 3:
            return [], []
        h, w = strip.shape[:2]
        if h < 60 or w < 80:
            return [], []
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        white = ((hsv[:, :, 2] > 135) & (hsv[:, :, 1] < 135)).astype(np.uint8) * 255
        white = cv2.morphologyEx(white, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(white)
        min_area = max(180, int(h * w * 0.006))
        raw_boxes: list[tuple[int, int, int, int, int]] = []
        for label in range(1, n_labels):
            x, y, bw, bh, area = [int(v) for v in stats[label]]
            if area < min_area or bw < max(26, int(w * 0.018)) or bh < max(48, int(h * 0.35)):
                continue
            ratio = bw / max(1, bh)
            if ratio < 0.30 or ratio > 0.92 or y + bh < h * 0.35:
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
            if bw < med_w * 0.45 or bw > med_w * 1.55 or bh < med_h * 0.55 or bh > med_h * 1.45:
                continue
            boxes.append((x, y, bw, bh))
        if not self._is_acceptable_hand_roi_count(len(boxes), expected_count):
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
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))
        return rois, slots

    def _segment_tiles_by_low_white_runs(self, strip: np.ndarray, expected_count: int, frame_index: int, debug_dir: str | None) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
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
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))
        return rois, slots

    def _segment_tiles_by_gap_runs(self, strip: np.ndarray, expected_count: int, frame_index: int, debug_dir: str | None) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
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
        col = cv2.GaussianBlur(white.mean(axis=0).reshape(1, -1), (1, 5), 0).reshape(-1)
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
        min_tile_w = max(28, int(w / 30))
        merged = [(s, e) for s, e in runs if e - s >= min_tile_w]
        if len(merged) < 8:
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
            return [], []
        merged = split_runs
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
            pad = max(1, min(4, int(max(1, gap_med) * 0.35)))
            x1 = max(0, s - pad)
            x2 = min(w, e + pad)
            roi = strip[y1:y2, x1:x2]
            if not self._is_single_tile_roi(roi):
                return [], []
            rois.append(roi)
            slots.append((x1, y1, x2 - x1, y2 - y1))
        return rois, slots

    def _segment_tiles_by_face_valleys(self, strip: np.ndarray, expected_count: int, frame_index: int, debug_dir: str | None) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
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
        col = cv2.GaussianBlur(white.mean(axis=0).reshape(1, -1), (1, 5), 0).reshape(-1)
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
            region = col[lo:hi]
            min_val = float(region.min())
            candidates = np.where(region <= min_val + 0.015)[0]
            if len(candidates):
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
        return rois, slots

    def _segment_tiles(self, strip: np.ndarray, expected_count: int = 13, frame_index: int = 0, debug_dir: str | None = None) -> list[np.ndarray]:
        if strip is None or strip.size == 0:
            return []
        h, w = strip.shape[:2]
        component_rois, _component_slots = self._segment_tiles_by_white_components(strip, expected_count, frame_index, debug_dir)
        if len(component_rois) == expected_count:
            return component_rois
        rois = self._segment_tiles_by_gradient(strip)
        if len(rois) == expected_count:
            return rois
        rois = self._segment_tiles_equal_n(strip, expected_count)
        logger.info("[Frame %d] hand equal split fallback(%d): %d rois (strip=%dx%d)", frame_index, expected_count, len(rois), w, h)
        return rois

    def _segment_tiles_by_gradient(self, strip: np.ndarray) -> list[np.ndarray]:
        if strip is None or strip.size == 0:
            return []
        h, w = strip.shape[:2]
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) if len(strip.shape) == 3 else strip.copy()
        sobel = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
        col_edge = cv2.GaussianBlur(np.abs(sobel).mean(axis=0).reshape(1, -1), (1, 7), 0).reshape(-1)
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV) if len(strip.shape) == 3 else None
        if hsv is not None:
            v_mean = int(hsv[:, :, 2].mean())
            if v_mean > 120:
                white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
                tile_pixels = np.where(white_col > 0.3)[0]
            else:
                content_col = ((hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 40)).mean(axis=0)
                tile_pixels = np.where(content_col > 0.25)[0]
        else:
            tile_pixels = np.arange(w)
        if len(tile_pixels) < 60:
            return []
        x_left, x_right = int(tile_pixels[0]), int(tile_pixels[-1]) + 1
        tile_w = x_right - x_left
        est_tile_w = tile_w / 14
        min_dist = max(int(est_tile_w * 0.55), 25)
        edge_region = col_edge[x_left:x_right]
        threshold = float(np.percentile(edge_region, 70))
        peaks = []
        last = -min_dist
        for i in range(1, len(edge_region) - 1):
            if edge_region[i] >= edge_region[i - 1] and edge_region[i] >= edge_region[i + 1] and edge_region[i] > threshold:
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
        seg_widths = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1) if min_rw <= boundaries[i + 1] - boundaries[i] <= max_rw]
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
        return rois

    def _segment_tiles_equal_n(self, strip: np.ndarray, n: int) -> list[np.ndarray]:
        if strip is None or strip.size == 0 or n <= 0:
            return []
        h, w = strip.shape[:2]
        if len(strip.shape) == 3:
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
            tile_pixels = np.where(white_col > 0.3)[0]
            if len(tile_pixels) >= 60:
                x_left = int(tile_pixels[0]); x_right = int(tile_pixels[-1]) + 1
            else:
                content_col = ((hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 40)).mean(axis=0)
                content_pixels = np.where(content_col > 0.25)[0]
                if len(content_pixels) >= 60:
                    x_left = int(content_pixels[0]); x_right = int(content_pixels[-1]) + 1
                else:
                    x_left, x_right = 0, w
        else:
            tile_pixels = np.where(strip.mean(axis=0) > 40)[0]
            if len(tile_pixels) >= 60:
                x_left = int(tile_pixels[0]); x_right = int(tile_pixels[-1]) + 1
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

    def _is_single_tile_roi(self, roi: np.ndarray) -> bool:
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
        return longest < max(4, int(w * 0.08))
