from __future__ import annotations

import cv2
import numpy as np


def _ensure_bgr(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 3:
        return img
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _build_tile_face_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    bright = ((hsv[:, :, 2] > 120) & (hsv[:, :, 1] < 105)).astype(np.uint8) * 255
    shadow = ((gray > 65) & (gray < 215) & (hsv[:, :, 1] < 95)).astype(np.uint8) * 255
    local = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    local = cv2.bitwise_and(local, ((hsv[:, :, 1] < 120).astype(np.uint8) * 255))

    bright = cv2.morphologyEx(
        bright, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )
    bright = cv2.morphologyEx(
        bright, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )
    shadow = cv2.morphologyEx(
        shadow, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )
    shadow = cv2.morphologyEx(
        shadow, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    )
    local = cv2.morphologyEx(
        local, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    )
    local = cv2.morphologyEx(
        local, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )

    candidates = [bright, shadow, local]
    coverage = [float((mask > 0).mean()) for mask in candidates]
    best = candidates[int(np.argmax(coverage))]
    if max(coverage) < 0.10:
        best = cv2.bitwise_or(bright, shadow)
        best = cv2.bitwise_or(best, local)
    return best


def _build_white_face_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    white = (
        (hsv[:, :, 2] > 135)
        & (hsv[:, :, 1] < 130)
        & (gray > 110)
    ).astype(np.uint8) * 255
    white = cv2.morphologyEx(
        white, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    )
    white = cv2.morphologyEx(
        white, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )
    return white


def _find_face_box_by_projection(
    bgr: np.ndarray,
) -> tuple[int, int, int, int] | None:
    h, w = bgr.shape[:2]
    if h < 18 or w < 12:
        return None

    white = _build_white_face_mask(bgr)
    y_top = max(0, int(h * 0.08))
    y_bottom = min(h, int(h * 0.96))
    band = white[y_top:y_bottom]
    if band.size == 0:
        return None

    col_score = cv2.GaussianBlur(
        band.mean(axis=0).reshape(1, -1), (1, 7), 0
    ).reshape(-1)
    peak = float(col_score.max()) if col_score.size else 0.0
    if peak < 10.0:
        return None

    active_threshold = max(22.0, min(peak * 0.52, 120.0))
    active = col_score >= active_threshold
    min_run_w = max(8, int(w * 0.12))

    runs: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(active):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_run_w:
                runs.append((start, i))
            start = None
    if start is not None and len(active) - start >= min_run_w:
        runs.append((start, len(active)))
    if not runs:
        return None

    best_box: tuple[int, int, int, int] | None = None
    best_score = -1.0
    for left, right in runs:
        sub = white[:, left:right]
        if sub.size == 0:
            continue
        row_score = cv2.GaussianBlur(
            sub.mean(axis=1).reshape(-1, 1), (1, 7), 0
        ).reshape(-1)
        row_peak = float(row_score.max()) if row_score.size else 0.0
        if row_peak < 10.0:
            continue
        row_threshold = max(18.0, min(row_peak * 0.45, 105.0))
        rows = np.where(row_score >= row_threshold)[0]
        if len(rows) < 6:
            continue

        x1 = int(left)
        x2 = int(right)
        y1 = int(rows[0])
        y2 = int(rows[-1]) + 1
        bw = x2 - x1
        bh = y2 - y1
        if bw < max(8, int(w * 0.10)) or bh < max(16, int(h * 0.38)):
            continue

        ratio = bw / max(1.0, float(bh))
        ratio_score = max(0.0, 1.0 - abs(ratio - 0.63) / 0.38)
        fill = float((white[y1:y2, x1:x2] > 0).mean())
        center = (x1 + x2) / 2.0 / max(1.0, float(w))
        center_score = max(0.0, 1.0 - abs(center - 0.5) * 1.4)
        area_score = min(1.0, (bw * bh) / max(1.0, w * h * 0.40))
        score = ratio_score * 2.4 + fill * 1.4 + center_score * 0.8 + area_score * 0.6
        if score > best_score:
            best_score = score
            best_box = (x1, y1, x2, y2)

    if best_box is None:
        return None

    x1, y1, x2, y2 = best_box
    pad_x = max(1, min(4, int((x2 - x1) * 0.04)))
    pad_y = max(1, min(4, int((y2 - y1) * 0.04)))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)
    if x2 - x1 < 8 or y2 - y1 < 16:
        return None
    return x1, y1, x2, y2


def _expand_face_box_to_tile(
    frame_w: int,
    frame_h: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> tuple[int, int, int, int]:
    face_w = max(1, x2 - x1)
    face_h = max(1, y2 - y1)

    # Approximate full tile from inner white face.
    pad_left = max(2, int(round(face_w * 0.16)))
    pad_right = max(2, int(round(face_w * 0.12)))
    pad_top = max(2, int(round(face_h * 0.10)))
    pad_bottom = max(2, int(round(face_h * 0.08)))

    tx1 = max(0, x1 - pad_left)
    tx2 = min(frame_w, x2 + pad_right)
    ty1 = max(0, y1 - pad_top)
    ty2 = min(frame_h, y2 + pad_bottom)

    tile_w = tx2 - tx1
    tile_h = ty2 - ty1
    ratio = tile_w / max(1.0, float(tile_h))
    target_ratio = 0.64

    if ratio < 0.42:
        grow = int(round((target_ratio * tile_h - tile_w) / 2.0))
        tx1 = max(0, tx1 - grow)
        tx2 = min(frame_w, tx2 + grow)
    elif ratio > 0.82:
        extra_h = int(round((tile_w / target_ratio - tile_h) / 2.0))
        ty1 = max(0, ty1 - extra_h)
        ty2 = min(frame_h, ty2 + extra_h)

    return tx1, ty1, tx2, ty2


def _tighten_box_to_mask(
    mask: np.ndarray,
    box: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int]:
    x, y, bw, bh, area = box
    sub = mask[y : y + bh, x : x + bw]
    if sub.size == 0:
        return box

    rows = (sub > 0).mean(axis=1)
    cols = (sub > 0).mean(axis=0)
    row_idx = np.where(rows > 0.10)[0]
    col_idx = np.where(cols > 0.10)[0]
    if len(row_idx) < 3 or len(col_idx) < 3:
        return box

    y1 = y + int(row_idx[0])
    y2 = y + int(row_idx[-1]) + 1
    x1 = x + int(col_idx[0])
    x2 = x + int(col_idx[-1]) + 1
    if x2 <= x1 or y2 <= y1:
        return box
    tight = mask[y1:y2, x1:x2]
    return x1, y1, x2 - x1, y2 - y1, int((tight > 0).sum())


def _component_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    h, w = mask.shape[:2]
    n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes: list[tuple[int, int, int, int, int]] = []
    min_area = max(60, int(h * w * 0.05))
    min_w = max(8, int(w * 0.10))
    min_h = max(16, int(h * 0.35))

    for label in range(1, n_labels):
        x, y, bw, bh, area = [int(v) for v in stats[label]]
        if area < min_area or bw < min_w or bh < min_h:
            continue
        boxes.append((x, y, bw, bh, area))
    return boxes


def _split_wide_box(mask: np.ndarray, box: tuple[int, int, int, int, int]) -> list[tuple[int, int, int, int, int]]:
    x, y, bw, bh, area = box
    ratio = bw / max(1.0, float(bh))
    if ratio < 1.05:
        return [_tighten_box_to_mask(mask, box)]

    sub = mask[y : y + bh, x : x + bw]
    if sub.size == 0:
        return [box]
    col = (sub > 0).mean(axis=0)

    runs: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(col > 0.28):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(col)))

    parts: list[tuple[int, int, int, int, int]] = []
    for left, right in runs:
        pw = right - left
        if pw < max(8, int(bw * 0.12)):
            continue
        part = sub[:, left:right]
        density = float((part > 0).mean())
        if density < 0.12:
            continue
        area_part = int((part > 0).sum())
        parts.append(_tighten_box_to_mask(mask, (x + left, y, pw, bh, area_part)))
    if parts and not (len(parts) == 1 and parts[0][2] >= int(bw * 0.90)):
        return parts

    low = col < 0.10
    valleys: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(low):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            valleys.append((start, i))
            start = None
    if start is not None:
        valleys.append((start, len(low)))

    separators = [
        (a + b) // 2
        for a, b in valleys
        if (b - a) >= max(2, int(bw * 0.04))
        and a > int(bw * 0.12)
        and b < int(bw * 0.88)
    ]
    valley_parts: list[tuple[int, int, int, int, int]] = []
    if separators:
        boundaries = [0] + separators + [bw]
        for left, right in zip(boundaries, boundaries[1:]):
            pw = right - left
            if pw < max(8, int(bw * 0.18)):
                continue
            part = sub[:, left:right]
            if float((part > 0).mean()) < 0.12:
                continue
            area_part = int((part > 0).sum())
            valley_parts.append(_tighten_box_to_mask(mask, (x + left, y, pw, bh, area_part)))
    if valley_parts and not (len(valley_parts) == 1 and valley_parts[0][2] >= int(bw * 0.90)):
        return valley_parts

    return [_tighten_box_to_mask(mask, box)]


def _score_box(box: tuple[int, int, int, int, int], frame_w: int, frame_h: int) -> float:
    x, y, bw, bh, area = box
    ratio = bw / max(1.0, float(bh))
    aspect_score = max(0.0, 1.0 - abs(ratio - 0.66) / 0.42)
    cx = (x + bw / 2) / max(1.0, float(frame_w))
    cy = (y + bh / 2) / max(1.0, float(frame_h))
    center_score = max(0.0, 1.0 - abs(cx - 0.5) * 1.4) + max(0.0, 1.0 - abs(cy - 0.55) * 0.7)
    area_score = min(1.0, area / max(1.0, frame_w * frame_h * 0.20))
    return aspect_score * 2.0 + center_score + area_score


def _content_window_crop(crop: np.ndarray) -> tuple[bool, np.ndarray | None, str]:
    bgr = _ensure_bgr(crop)
    h, w = bgr.shape[:2]
    if h < 20 or w < 14:
        return False, None, f"too_small:{w}x{h}"

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    dark = ((gray < 205) | (hsv[:, :, 1] > 70)).astype(np.uint8)
    band = dark[int(h * 0.10):int(h * 0.92), :]
    if band.size == 0 or float(band.mean()) < 0.02:
        return False, None, "no_content"

    col_score = cv2.GaussianBlur(band.mean(axis=0).reshape(1, -1), (1, 7), 0).reshape(-1)
    target_w = int(round(h * 0.72))
    target_w = max(16, min(w, target_w))
    if target_w >= w:
        return True, bgr, "full_width"

    best_start = 0
    best_score = -1.0
    for start in range(0, w - target_w + 1):
        end = start + target_w
        score = float(col_score[start:end].mean())
        center = (start + end) / 2.0
        center_bias = 1.0 - abs(center / max(1.0, float(w)) - 0.5)
        score += center_bias * 0.08
        if score > best_score:
            best_score = score
            best_start = start

    x1 = max(0, best_start - 1)
    x2 = min(w, best_start + target_w + 1)
    focus = dark[:, x1:x2]
    row_score = focus.mean(axis=1)
    row_idx = np.where(row_score > 0.05)[0]
    if len(row_idx) >= 4:
        y1 = max(0, int(row_idx[0]) - 1)
        y2 = min(h, int(row_idx[-1]) + 2)
    else:
        y1 = 0
        y2 = h
    out = bgr[y1:y2, x1:x2]
    if out.size == 0:
        return False, None, "empty_crop"
    return True, out, "ok"


def _prepare_full_tile_crop(crop: np.ndarray) -> tuple[bool, np.ndarray | None, str]:
    bgr = _ensure_bgr(crop)
    h, w = bgr.shape[:2]
    if h < 18 or w < 10:
        return False, None, f"too_small:{w}x{h}"

    projection_box = _find_face_box_by_projection(bgr)
    if projection_box is None:
        return False, None, "no_tile_face"

    px1, py1, px2, py2 = projection_box
    tx1, ty1, tx2, ty2 = _expand_face_box_to_tile(w, h, px1, py1, px2, py2)

    # For training and ROI review we want the whole tile, not just the face,
    # so keep a bit more outer border than the runtime recognizer crop.
    extra_x = max(2, int(round((tx2 - tx1) * 0.08)))
    extra_y_top = max(2, int(round((ty2 - ty1) * 0.14)))
    extra_y_bottom = max(2, int(round((ty2 - ty1) * 0.10)))
    tx1 = max(0, tx1 - extra_x)
    tx2 = min(w, tx2 + extra_x)
    ty1 = max(0, ty1 - extra_y_top)
    ty2 = min(h, ty2 + extra_y_bottom)

    out = bgr[ty1:ty2, tx1:tx2]
    if out.size == 0:
        return False, None, "empty_crop"

    oh, ow = out.shape[:2]
    ratio = ow / max(1.0, float(oh))
    if ratio > 0.78:
        grow_h = int(round((ow / 0.64 - oh) / 2.0))
        ty1 = max(0, ty1 - grow_h)
        ty2 = min(h, ty2 + grow_h)
        out = bgr[ty1:ty2, tx1:tx2]
        oh, ow = out.shape[:2]
        ratio = ow / max(1.0, float(oh))
    if ratio < 0.24 or ratio > 0.95:
        return False, None, f"bad_ratio:{ratio:.2f}"
    return True, out, "ok"


def _refine_crop_to_tile_face(crop: np.ndarray) -> tuple[bool, np.ndarray | None, str]:
    bgr = _ensure_bgr(crop)
    h, w = bgr.shape[:2]
    if h < 18 or w < 10:
        return False, None, f"too_small:{w}x{h}"

    projection_box = _find_face_box_by_projection(bgr)
    if projection_box is not None:
        px1, py1, px2, py2 = projection_box
        tx1, ty1, tx2, ty2 = _expand_face_box_to_tile(w, h, px1, py1, px2, py2)
        projected = bgr[ty1:ty2, tx1:tx2]
        if projected.size > 0:
            bgr = projected
            h, w = bgr.shape[:2]

    mask = _build_tile_face_mask(bgr)
    boxes = _component_boxes(mask)
    if not boxes:
        if projection_box is not None:
            ratio = w / max(1.0, float(h))
            if 0.24 <= ratio <= 0.95:
                return True, bgr, "projection_only"
        return False, None, "no_tile_face"

    boxes = [_tighten_box_to_mask(mask, box) for box in boxes]
    boxes.sort(key=lambda box: _score_box(box, w, h), reverse=True)
    x, y, bw, bh, area = boxes[0]
    if bw < max(12, int(w * 0.20)) or bh < max(20, int(h * 0.45)):
        return False, None, f"incomplete_face:{bw}x{bh}"

    ratio = bw / max(1.0, float(bh))
    if ratio > 0.95:
        ok, content_crop, _content_reason = _content_window_crop(bgr[y : y + bh, x : x + bw])
        if ok and content_crop is not None:
            bgr = content_crop
            h, w = bgr.shape[:2]
            mask = _build_tile_face_mask(bgr)
            boxes = _component_boxes(mask)
            if boxes:
                boxes = [_tighten_box_to_mask(mask, box) for box in boxes]
                boxes.sort(key=lambda box: _score_box(box, w, h), reverse=True)
                x, y, bw, bh, area = boxes[0]
                ratio = bw / max(1.0, float(bh))
            else:
                x, y, bw, bh = 0, 0, w, h
                ratio = w / max(1.0, float(h))
    if ratio < 0.24 or ratio > 0.95:
        if projection_box is not None:
            ratio = w / max(1.0, float(h))
        ok, content_crop, _content_reason = _content_window_crop(bgr)
        if ok and content_crop is not None:
            bgr = content_crop
            h, w = bgr.shape[:2]
            x, y, bw, bh = 0, 0, w, h
            ratio = w / max(1.0, float(h))
    if ratio < 0.24 or ratio > 0.95:
        return False, None, f"bad_ratio:{ratio:.2f}"

    pad_x = max(1, min(3, int(bw * 0.03)))
    pad_y = max(1, min(3, int(bh * 0.03)))
    x1 = max(0, x - pad_x)
    x2 = min(w, x + bw + pad_x)
    y1 = max(0, y - pad_y)
    y2 = min(h, y + bh + pad_y)
    out = bgr[y1:y2, x1:x2]
    if out.size == 0:
        return False, None, "empty_crop"
    return True, out, "ok"


def extract_discard_tile_candidates(
    img: np.ndarray,
    max_tiles: int = 3,
) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]], str]:
    if img is None or img.size == 0:
        return [], [], "empty"
    bgr = _ensure_bgr(img)
    h, w = bgr.shape[:2]
    if h < 16 or w < 12:
        return [], [], f"too_small:{w}x{h}"

    projection_box = _find_face_box_by_projection(bgr)
    mask = _build_tile_face_mask(bgr)
    boxes = _component_boxes(mask)
    if projection_box is not None:
        px1, py1, px2, py2 = projection_box
        tx1, ty1, tx2, ty2 = _expand_face_box_to_tile(w, h, px1, py1, px2, py2)
        pbox = (tx1, ty1, tx2 - tx1, ty2 - ty1, (tx2 - tx1) * (ty2 - ty1))
        boxes = [pbox] + boxes
    if not boxes:
        return [], [], "no_tile_face"

    refined: list[tuple[int, int, int, int, int]] = []
    for box in boxes:
        refined.extend(_split_wide_box(mask, box))
    if not refined:
        return [], [], "no_tile_face"

    refined = sorted(
        refined,
        key=lambda box: (-_score_box(box, w, h), box[0]),
    )[: max_tiles * 2]
    refined = sorted(refined, key=lambda box: box[0])

    crops: list[np.ndarray] = []
    rects: list[tuple[int, int, int, int]] = []
    min_crop_h = max(20, int(h * 0.40))
    min_crop_w = max(12, int(w * 0.12))

    for x, y, bw, bh, _area in refined:
        if bw < min_crop_w or bh < min_crop_h:
            continue
        pad_x = max(1, min(4, int(bw * 0.03)))
        pad_y = max(1, min(4, int(bh * 0.03)))
        x1 = max(0, x - pad_x)
        x2 = min(w, x + bw + pad_x)
        y1 = max(0, y - pad_y)
        y2 = min(h, y + bh + pad_y)
        crop = bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        ok, clean_crop, _reason = _refine_crop_to_tile_face(crop)
        if ok and clean_crop is not None:
            crop = clean_crop
        crops.append(crop)
        rects.append((x1, y1, x2 - x1, y2 - y1))

    if not crops:
        return [], [], "empty_crop"

    # Deduplicate highly overlapping candidates.
    dedup_crops: list[np.ndarray] = []
    dedup_rects: list[tuple[int, int, int, int]] = []
    for crop, rect in zip(crops, rects):
        x, y, bw, bh = rect
        keep = True
        for ox, oy, ow, oh in dedup_rects:
            ix1 = max(x, ox)
            iy1 = max(y, oy)
            ix2 = min(x + bw, ox + ow)
            iy2 = min(y + bh, oy + oh)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = bw * bh + ow * oh - inter
            if union > 0 and inter / union > 0.70:
                keep = False
                break
        if keep:
            dedup_crops.append(crop)
            dedup_rects.append(rect)
        if len(dedup_crops) >= max_tiles:
            break

    return dedup_crops, dedup_rects, "ok"


def extract_primary_discard_tile(
    img: np.ndarray,
) -> tuple[bool, np.ndarray | None, str]:
    crops, _rects, reason = extract_discard_tile_candidates(img, max_tiles=1)
    if not crops:
        return False, None, reason
    return True, crops[0], "ok"


def prepare_trainable_discard_roi_image(
    img: np.ndarray,
) -> tuple[bool, np.ndarray | None, str]:
    if img is None or img.size == 0:
        return False, None, "empty"

    ok, refined, reason = _prepare_full_tile_crop(img)
    if not ok or refined is None:
        ok, crop, reason = extract_primary_discard_tile(img)
        if not ok or crop is None:
            return False, None, reason
        ok, refined, reason = _prepare_full_tile_crop(crop)
        if not ok or refined is None:
            return False, None, reason

    h, w = refined.shape[:2]
    if h < 24 or w < 12:
        return False, None, f"too_small:{w}x{h}"
    ratio = w / max(1.0, float(h))
    if ratio < 0.24 or ratio > 0.95:
        return False, None, f"bad_ratio:{ratio:.2f}"
    return True, refined, "ok"
