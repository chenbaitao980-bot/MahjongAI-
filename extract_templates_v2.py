"""
v2: 改进版模板提取脚本
- 用牌面绿色边框精准切割每张牌
- 条牌：垂直边缘密度法（不依赖绿色比例）
- 万牌：检测红色数字区域
- 字牌：排除法 + 特征匹配
- 筒牌：HoughCircles
"""
import cv2
import numpy as np
import os

VIDEO = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
TILE_DIR   = r"C:\MahjongAI\templates\tiles"
DEBUG_DIR  = r"C:\MahjongAI\templates\debug_crops"
BTN_DIR    = r"C:\MahjongAI\templates\buttons"

TILE_SIZE = (48, 64)
HAND_Y1, HAND_Y2 = 462, 590   # 手牌条带（原始帧坐标）

os.makedirs(TILE_DIR,  exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)
os.makedirs(BTN_DIR,   exist_ok=True)

ALL_TILES = (
    [f"{i}m" for i in range(1, 10)] +
    [f"{i}p" for i in range(1, 10)] +
    [f"{i}s" for i in range(1, 10)] +
    [f"{i}z" for i in range(1, 8)]
)

# ── 工具 ─────────────────────────────────────────────────────────────────────

def dhash(img: np.ndarray, size=8) -> int:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size))
    diff = small[:, 1:] > small[:, :-1]
    return sum(bool(b) << i for i, b in enumerate(diff.flatten()))

def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count('1')

def preprocess(roi: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    return clahe.apply(gray)

# ── 牌格切割（绿色边框法）────────────────────────────────────────────────────

def segment_tiles_from_strip(strip_bgr: np.ndarray) -> list[np.ndarray]:
    """
    利用绿色外框分割手牌。返回各牌 BGR ROI 列表（已按X坐标排序）。
    """
    hsv = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2HSV)
    # 牌面绿色边框：鲜艳中绿
    green_mask = cv2.inRange(hsv, np.array([40, 80, 80]), np.array([90, 255, 255]))

    # 列投影：有绿色边框的列会出现峰值
    col_proj = green_mask.sum(axis=0).astype(float)
    col_max = col_proj.max()
    if col_max < 10:
        return []
    col_proj /= col_max

    # 找连续绿色列段作为边框位置
    threshold = 0.15
    borders = []      # 每段绿色柱的中心 x
    in_seg = False
    seg_start = 0
    for x, v in enumerate(col_proj):
        if not in_seg and v >= threshold:
            in_seg = True
            seg_start = x
        elif in_seg and v < threshold:
            in_seg = False
            borders.append((seg_start + x) // 2)
    if in_seg:
        borders.append((seg_start + len(col_proj)) // 2)

    if len(borders) < 2:
        return []

    rois = []
    for i in range(len(borders) - 1):
        x1, x2 = borders[i], borders[i + 1]
        w = x2 - x1
        # 过滤：牌宽 50~120px
        if not (45 <= w <= 130):
            continue
        roi = strip_bgr[:, x1:x2]
        h = roi.shape[0]
        if h < 50:
            continue
        rois.append(roi)
    return rois

# ── 分类逻辑 ──────────────────────────────────────────────────────────────────

def circle_count(roi: np.ndarray) -> int:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.5)
    h, w = gray.shape
    min_r = max(4, w // 14)
    max_r = max(10, w // 3)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=min_r * 1.8,
        param1=50, param2=15,
        minRadius=min_r, maxRadius=max_r,
    )
    return 0 if circles is None else len(circles[0])

def bamboo_stick_count(roi: np.ndarray) -> int:
    """
    垂直边缘密度法数竹节数量。
    竹条牌每根竹子在列投影上产生明显双边缘峰。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    # 只看中间2/3行（去掉顶部数字区域）
    h, w = gray.shape
    crop = gray[h//5 : h*4//5, :]
    # Sobel垂直边缘
    sobel_x = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=3)
    edge_proj = np.abs(sobel_x).sum(axis=0)
    if edge_proj.max() == 0:
        return 0
    edge_proj /= edge_proj.max()

    # 找峰值（超过0.4的列段）
    threshold = 0.35
    in_peak, count = False, 0
    for v in edge_proj:
        if not in_peak and v >= threshold:
            in_peak = True
            count += 1
        elif in_peak and v < threshold:
            in_peak = False
    # 每根竹产生2个边缘峰，除以2
    sticks = max(1, round(count / 2))
    return min(sticks, 9)

def has_vertical_bamboo(roi: np.ndarray) -> bool:
    """检测是否有竹节结构（区分条牌 vs 其它）。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    crop = gray[h//5 : h*4//5, :]
    sobel_x = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=3)
    edge_proj = np.abs(sobel_x).sum(axis=0)
    if edge_proj.max() == 0:
        return False
    edge_proj /= edge_proj.max()
    # 条牌应该有 ≥4 个峰（2根竹以上）
    threshold = 0.35
    in_peak, count = False, 0
    for v in edge_proj:
        if not in_peak and v >= threshold:
            in_peak = True; count += 1
        elif in_peak and v < threshold:
            in_peak = False
    return count >= 4

def red_ratio(roi: np.ndarray) -> float:
    """红色像素占比（万牌数字特征）。"""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0,   80, 80]), np.array([10,  255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 80, 80]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)
    return mask.sum() / (roi.shape[0] * roi.shape[1] * 255 + 1e-6)

def green_ratio(roi: np.ndarray) -> float:
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([40, 60, 60]), np.array([90, 255, 255]))
    return mask.sum() / (roi.shape[0] * roi.shape[1] * 255 + 1e-6)

def has_wan_character(roi: np.ndarray) -> bool:
    """
    万牌中央偏下有"万"字（M/W形状），检测该区域是否有特征水平线。
    万字底部有一条横划，用行投影检测。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    # 取中央区域
    center = gray[h//3 : h*2//3, w//6 : w*5//6]
    _, bw = cv2.threshold(center, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    row_proj = bw.sum(axis=1).astype(float)
    if row_proj.max() == 0:
        return False
    row_proj /= row_proj.max()
    # 万字竖划在列方向产生2个明显峰（左竖、右竖）
    col_proj = bw.sum(axis=0).astype(float)
    if col_proj.max() == 0:
        return False
    col_proj /= col_proj.max()
    peaks = sum(1 for v in col_proj if v > 0.4)
    return peaks >= 3   # 万字约有3-4个暗区分布

def count_wan_number(roi: np.ndarray) -> int:
    """
    估算万牌数字（1-9）：取牌面顶部数字区域，用列投影数竖划。
    万牌顶部有汉字数字（一二三...九），笔划数从左到右增加。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    # 顶部数字区（约占上1/3）
    top = gray[2 : h//3, w//6 : w*5//6]
    _, bw = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    col_proj = bw.sum(axis=0).astype(float)
    if col_proj.max() == 0:
        return 0
    col_proj /= col_proj.max()
    threshold = 0.3
    in_peak, count = False, 0
    for v in col_proj:
        if not in_peak and v >= threshold:
            in_peak = True; count += 1
        elif in_peak and v < threshold:
            in_peak = False
    # 汉字笔划峰数对应关系（近似）
    mapping = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
    return mapping.get(count, count) if 1 <= count <= 9 else 0

def classify_tile(roi: np.ndarray) -> str | None:
    """
    返回猜测的牌 ID（如 '3m'、'7p'、'1s'）或 None。
    分类顺序：筒 → 条 → 万 → 字(None)
    """
    cc = circle_count(roi)
    gr = green_ratio(roi)
    rr = red_ratio(roi)

    # ── 筒牌（圆圈最强信号）──────────────────
    if cc >= 1:
        return f"{min(cc, 9)}p"

    # ── 条牌（竹节结构）──────────────────────
    if has_vertical_bamboo(roi):
        # 发牌(6z)：大面积纯绿，无竹节
        if gr > 0.20:
            return "6z"
        sticks = bamboo_stick_count(roi)
        if 1 <= sticks <= 9:
            return f"{sticks}s"
        return "1s"   # fallback

    # ── 万牌（红色数字 + 万字）───────────────
    if rr > 0.03:
        n = count_wan_number(roi)
        if 1 <= n <= 9:
            return f"{n}m"
        # 数字估不出来：暂存为 unknown_m
        return None

    # ── 字牌 / 其他 ──────────────────────────
    return None


# ── 主流程 ────────────────────────────────────────────────────────────────────

def extract():
    cap = cv2.VideoCapture(VIDEO)
    assert cap.isOpened(), f"无法打开: {VIDEO}"

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"视频: {total}帧 @ {fps:.1f}fps, {W}×{H}")

    # 已保存集合: tile_id -> [(hash, path)]
    saved: dict[str, list[tuple[int, str]]] = {}
    # 未分类: [(hash, bgr_roi)]
    unclassified: list[tuple[int, np.ndarray]] = []
    unc_hashes: list[int] = []

    STEP = 3       # 每3帧采样一次（85秒×24fps=2043帧，共681次）
    TOL  = 6       # dHash Hamming容差

    processed = 0
    for fi in range(0, total, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        processed += 1

        strip = frame[HAND_Y1:HAND_Y2, :]
        rois = segment_tiles_from_strip(strip)

        for roi in rois:
            if roi.shape[1] < 30 or roi.shape[0] < 40:
                continue
            h_val = dhash(roi)
            tile_id = classify_tile(roi)

            if tile_id is not None:
                bucket = saved.setdefault(tile_id, [])
                if any(hamming(h_val, h2) <= TOL for h2, _ in bucket):
                    continue
                path = os.path.join(TILE_DIR, f"{tile_id}.png")
                proc = preprocess(roi)
                resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
                # 保留较清晰的（均值亮度作为代理）
                existing = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if os.path.exists(path) else None
                if existing is None or resized.mean() > existing.mean():
                    cv2.imwrite(path, resized)
                    print(f"  [保存] {tile_id} frame={fi}")
                bucket.append((h_val, path))
            else:
                if any(hamming(h_val, h2) <= TOL for h2 in unc_hashes):
                    continue
                unclassified.append((h_val, roi.copy()))
                unc_hashes.append(h_val)

    cap.release()

    # 保存未分类供人工查看
    for i, (_, roi) in enumerate(unclassified):
        proc = preprocess(roi)
        resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(DEBUG_DIR, f"unk_{i:03d}.png"), resized)

    print(f"\n处理 {processed} 帧，已保存 {len(saved)} 种牌，未分类 {len(unclassified)} 个")

    # ── 按钮提取 ──
    extract_buttons(fps)

    # ── 报告 ──
    print_report(saved)


def extract_buttons(fps: float):
    """扫描前20秒，寻找金色/彩色圆形按钮区域。"""
    cap = cv2.VideoCapture(VIDEO)
    if not cap.isOpened():
        return

    found_any = False
    for sec in range(0, 20):
        fi = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue

        # 按钮可能出现在手牌上方区域
        btn_strip = frame[350:462, 200:1080]
        hsv = cv2.cvtColor(btn_strip, cv2.COLOR_BGR2HSV)

        # 金黄色（胡/碰/吃）
        gold = cv2.inRange(hsv, np.array([10, 100, 150]), np.array([35, 255, 255]))
        # 或白色大按钮背景
        white = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 30, 255]))
        combined = cv2.bitwise_or(gold, white)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (8, 8))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

        n, _, stats, _ = cv2.connectedComponentsWithStats(combined, 8)
        btns = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 1500 or w < 40 or h < 25:
                continue
            aspect = w / h
            if not (0.4 <= aspect <= 4.0):
                continue
            btns.append((x, y, w, h))

        btns.sort(key=lambda b: b[0])
        if len(btns) >= 2:
            print(f"\n[按钮] sec={sec}: 检测到 {len(btns)} 个按钮区域")
            btn_names = ["过", "吃", "碰", "杠", "胡"]
            for j, (x, y, w, h) in enumerate(btns):
                roi = btn_strip[y:y+h, x:x+w]
                name = btn_names[j] if j < len(btn_names) else f"btn{j}"
                path = os.path.join(BTN_DIR, f"btn_{name}.png")
                cv2.imwrite(path, roi)
                print(f"  -> btn_{name}.png ({w}x{h})")
            # 同时保存整条按钮区截图供参考
            cv2.imwrite(os.path.join(BTN_DIR, f"_btn_strip_sec{sec:02d}.png"), btn_strip)
            found_any = True
            break

    if not found_any:
        print("[按钮] 未检测到明显按钮，保存各秒按钮条带供人工查看")
        cap2 = cv2.VideoCapture(VIDEO)
        for sec in [5, 6, 7, 8, 9]:
            cap2.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
            ret, frame = cap2.read()
            if ret:
                cv2.imwrite(os.path.join(BTN_DIR, f"_strip_sec{sec:02d}.png"),
                            frame[340:470, :])
        cap2.release()

    cap.release()


def print_report(saved: dict):
    print("\n" + "=" * 56)
    found = set(saved.keys())
    groups = [
        ("万", [f"{i}m" for i in range(1, 10)]),
        ("筒", [f"{i}p" for i in range(1, 10)]),
        ("条", [f"{i}s" for i in range(1, 10)]),
        ("字", [f"{i}z" for i in range(1, 8)]),
    ]
    for name, ids in groups:
        row = "".join(f"[{t}]" if t in found else f" {t} " for t in ids)
        print(f"{name}: {row}")
    missing = [t for t in ALL_TILES if t not in found]
    print(f"\n已保存: {len(found)}/34   缺失: {missing}")
    print(f"未分类图案 → {DEBUG_DIR}")


if __name__ == "__main__":
    extract()
