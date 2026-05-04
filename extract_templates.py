"""
从对局视频中提取麻将牌模板和按钮模板。
运行方式: python extract_templates.py
"""
import cv2
import numpy as np
import os
import json
from pathlib import Path

VIDEO_PATH = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
TILE_OUT_DIR = r"C:\MahjongAI\templates\tiles"
BTN_OUT_DIR = r"C:\MahjongAI\templates\buttons"

TILE_SIZE = (48, 64)   # width x height
HAND_Y1, HAND_Y2 = 462, 590   # 手牌区纵向范围

# 34 种牌 ID
ALL_TILES = (
    [f"{i}m" for i in range(1, 10)] +
    [f"{i}p" for i in range(1, 10)] +
    [f"{i}s" for i in range(1, 10)] +
    [f"{i}z" for i in range(1, 8)]
)

os.makedirs(TILE_OUT_DIR, exist_ok=True)
os.makedirs(BTN_OUT_DIR, exist_ok=True)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def dhash(img: np.ndarray, size: int = 8) -> int:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size))
    diff = small[:, 1:] > small[:, :-1]
    return sum(bool(b) << i for i, b in enumerate(diff.flatten()))


def hamming(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count('1')


def preprocess_tile(roi: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    return clahe.apply(gray)


def resize_tile(roi: np.ndarray) -> np.ndarray:
    return cv2.resize(roi, TILE_SIZE, interpolation=cv2.INTER_AREA)


# ── 手牌分割 ──────────────────────────────────────────────────────────────────

def detect_hand_tiles(frame: np.ndarray) -> list[np.ndarray]:
    """从手牌条带中分割出各个牌的 ROI。"""
    strip = frame[HAND_Y1:HAND_Y2, :]
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)

    # 白色牌面掩码 (高亮度、低饱和度)
    mask = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 70, 255]))
    # 闭运算合并相邻区域
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # 寻找连通域
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    rois = []
    for i in range(1, n_labels):
        x, y, w, h, area = stats[i]
        aspect = w / h if h > 0 else 0
        # 牌的大致尺寸：宽 45-120px，高 70-130px，比例 0.4-0.9
        if area < 2000:
            continue
        if not (40 <= w <= 130 and 60 <= h <= 140):
            continue
        if not (0.35 <= aspect <= 1.1):
            continue
        roi_bgr = strip[y:y+h, x:x+w]
        rois.append(roi_bgr)

    return rois


# ── 牌种分类 ──────────────────────────────────────────────────────────────────

def green_ratio(roi: np.ndarray) -> float:
    """绿色像素占比（条牌特征）。"""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([90, 255, 255]))
    return mask.sum() / (roi.shape[0] * roi.shape[1] * 255 + 1e-6)


def circle_count(roi: np.ndarray) -> int:
    """Hough圆检测（筒牌特征）。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    h, w = gray.shape
    min_r = max(4, w // 12)
    max_r = max(8, w // 4)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=min_r * 2,
        param1=60, param2=18,
        minRadius=min_r, maxRadius=max_r,
    )
    return 0 if circles is None else len(circles[0])


def count_bamboo_sticks(roi: np.ndarray) -> int:
    """列亮度投影谷值法数竹节数量（条牌数字）。"""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([90, 255, 255]))
    col_proj = green_mask.sum(axis=0).astype(float)
    if col_proj.max() == 0:
        return 0
    col_proj /= col_proj.max()
    threshold = 0.25
    in_peak = False
    count = 0
    for val in col_proj:
        if not in_peak and val > threshold:
            in_peak = True
            count += 1
        elif in_peak and val <= threshold:
            in_peak = False
    return count


def is_fapat(roi: np.ndarray) -> bool:
    """检测发牌（紧凑绿色块，无竹节）。"""
    gr = green_ratio(roi)
    sticks = count_bamboo_sticks(roi)
    # 发：大面积绿色但不是竹节结构
    return gr > 0.15 and sticks <= 2


def classify_tile(roi: np.ndarray) -> str | None:
    """
    返回猜测的牌 ID，或 None（无法分类）。
    """
    gr = green_ratio(roi)
    cc = circle_count(roi)

    # ── 筒牌 ──
    if cc >= 1:
        # 筒数 = 圆圈数（1-9）
        n = min(max(cc, 1), 9)
        return f"{n}p"

    # ── 条牌（绿色比例高）──
    if gr > 0.06:
        # 先检测是否是发
        if is_fapat(roi):
            return "6z"
        sticks = count_bamboo_sticks(roi)
        if 1 <= sticks <= 9:
            return f"{sticks}s"
        # 竹节数不明确时按绿色比例粗分
        return None

    # ── 万/字牌（红色/黑色文字，低绿色）──
    # 这里只能留作人工标注，返回 None
    return None


# ── 主提取流程 ────────────────────────────────────────────────────────────────

def extract_templates():
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开视频: {VIDEO_PATH}")
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"视频: {total_frames}帧 @ {fps:.1f}fps, {w}×{h}")

    # 去重：tile_id -> list of (hash, path)
    saved: dict[str, list[tuple[int, str]]] = {}
    # 未分类：list of (hash, roi_bgr)
    unclassified: list[tuple[int, np.ndarray]] = []
    unclassified_hashes: list[int] = []

    STEP = 6   # 每隔6帧取一帧
    HASH_TOL = 5   # Hamming距离阈值

    processed = 0
    for frame_idx in range(0, total_frames, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        processed += 1

        rois = detect_hand_tiles(frame)
        for roi in rois:
            h_val = dhash(roi)

            tile_id = classify_tile(roi)

            if tile_id is not None:
                # 检查是否已有相似模板
                bucket = saved.setdefault(tile_id, [])
                is_dup = any(hamming(h_val, h2) <= HASH_TOL for h2, _ in bucket)
                if not is_dup:
                    # 最多为同一牌保存3个变体（取最清晰的）
                    if len(bucket) < 3:
                        proc = preprocess_tile(roi)
                        resized = resize_tile(proc)
                        path = os.path.join(TILE_OUT_DIR, f"{tile_id}.png")
                        # 如果已存在，选置信度更高的（这里用均值亮度作为清晰度代理）
                        if not os.path.exists(path) or resized.mean() > cv2.imread(path, cv2.IMREAD_GRAYSCALE).mean():
                            cv2.imwrite(path, resized)
                            print(f"  [保存] {tile_id} (frame {frame_idx})")
                        bucket.append((h_val, path))
            else:
                # 未分类：去重后存入待检列表
                is_dup = any(hamming(h_val, h2) <= HASH_TOL for h2 in unclassified_hashes)
                if not is_dup:
                    unclassified.append((h_val, roi.copy()))
                    unclassified_hashes.append(h_val)

    cap.release()

    print(f"\n处理了 {processed} 帧 (总{total_frames}帧, 间隔{STEP})")
    print(f"已分类保存: {len(saved)} 种牌")
    print(f"未分类牌面: {len(unclassified)} 个独立图案")

    # 保存未分类到 debug 目录供人工查看
    debug_dir = r"C:\MahjongAI\templates\debug_unclassified"
    os.makedirs(debug_dir, exist_ok=True)
    for i, (h_val, roi) in enumerate(unclassified):
        proc = preprocess_tile(roi)
        resized = resize_tile(proc)
        cv2.imwrite(os.path.join(debug_dir, f"unk_{i:03d}.png"), resized)

    # ── 提取按钮模板（第6秒附近帧）──
    extract_buttons()

    # ── 汇总报告 ──
    print_report(saved)


def extract_buttons():
    """从第6秒帧提取 吃 和 过 按钮模板。"""
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    # 尝试几个时间点找到有按钮的帧
    for sec in [6, 7, 8, 5]:
        frame_idx = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        # 按钮区域（视频中在手牌上方，中央附近）
        # 根据之前观察：按钮出现在 y≈380-460, x≈320-960
        btn_region = frame[370:465, 300:980]

        # 检测金色/黄色按钮圆形区域
        hsv = cv2.cvtColor(btn_region, cv2.COLOR_BGR2HSV)
        # 金黄色 hue ≈ 15-35
        gold_mask = cv2.inRange(hsv, np.array([10, 100, 150]), np.array([40, 255, 255]))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        gold_mask = cv2.morphologyEx(gold_mask, cv2.MORPH_CLOSE, kernel)

        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(gold_mask, connectivity=8)
        buttons_found = []
        for i in range(1, n_labels):
            x, y, w, h, area = stats[i]
            if area < 800:
                continue
            aspect = w / h if h > 0 else 0
            if not (0.5 <= aspect <= 2.5):
                continue
            if w < 30 or h < 25:
                continue
            buttons_found.append((x, y, w, h, area))

        buttons_found.sort(key=lambda b: b[0])   # 按X排序
        print(f"\n  [按钮] sec={sec}, frame={frame_idx}: 检测到 {len(buttons_found)} 个金色区域")

        if len(buttons_found) >= 2:
            # 保存所有检测到的按钮（先作为通用 btn_unk)
            btn_names = ["吃", "过"]  # 在sec=6通常只有这两个
            for j, (x, y, w, h, area) in enumerate(buttons_found):
                roi = btn_region[y:y+h, x:x+w]
                name = btn_names[j] if j < len(btn_names) else f"btn_{j}"
                path = os.path.join(BTN_OUT_DIR, f"btn_{name}.png")
                cv2.imwrite(path, roi)
                print(f"    保存按钮: btn_{name}.png ({w}x{h}, area={area})")
            break

    cap.release()


def print_report(saved: dict):
    print("\n" + "=" * 60)
    print("牌模板提取报告")
    print("=" * 60)
    found = set(saved.keys())
    missing = [t for t in ALL_TILES if t not in found]

    # 按花色分组显示
    groups = [
        ("万", [f"{i}m" for i in range(1, 10)]),
        ("筒", [f"{i}p" for i in range(1, 10)]),
        ("条", [f"{i}s" for i in range(1, 10)]),
        ("字", [f"{i}z" for i in range(1, 8)]),
    ]
    for name, ids in groups:
        row = ""
        for tid in ids:
            row += f"[{tid}]" if tid in found else f" {tid} "
        print(f"{name}: {row}")

    print(f"\n已保存: {len(found)}/34 种")
    print(f"缺失: {missing}")
    print(f"未分类图案已保存到: C:\\MahjongAI\\templates\\debug_unclassified\\")


if __name__ == "__main__":
    extract_templates()
