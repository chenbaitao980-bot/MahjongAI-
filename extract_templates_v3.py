"""
v3: 白色掩码分割 + 改进分类
- 降低条牌检测阈值（1根竹节也能识别）
- 万牌用红色比例检测
- 字牌特征：发(大绿块)、中(大红块)、其余保存未分类
- 所有切割结果存 debug_all/ 方便核查
"""
import cv2
import numpy as np
import os

VIDEO   = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
TILE_DIR  = r"C:\MahjongAI\templates\tiles"
DEBUG_ALL = r"C:\MahjongAI\templates\debug_all"   # 所有已去重切片
BTN_DIR   = r"C:\MahjongAI\templates\buttons"

TILE_SIZE = (48, 64)
HAND_Y1, HAND_Y2 = 462, 590

ALL_TILES = (
    [f"{i}m" for i in range(1, 10)] +
    [f"{i}p" for i in range(1, 10)] +
    [f"{i}s" for i in range(1, 10)] +
    [f"{i}z" for i in range(1, 8)]
)

for d in [TILE_DIR, DEBUG_ALL, BTN_DIR]:
    os.makedirs(d, exist_ok=True)

# ── 工具 ──────────────────────────────────────────────────────────────────────

def dhash(img, size=8):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size))
    diff = small[:, 1:] > small[:, :-1]
    return sum(bool(b) << i for i, b in enumerate(diff.flatten()))

def hamming(a, b):
    return bin(a ^ b).count('1')

def preprocess(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    return clahe.apply(gray)

# ── 分割（白色掩码连通域，v1 方式）────────────────────────────────────────────

def segment_hand(strip_bgr):
    hsv = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (4, 4))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    rois = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 1800: continue
        if not (40 <= w <= 130 and 55 <= h <= 140): continue
        if not (0.3 <= w/h <= 1.1): continue
        rois.append(strip_bgr[y:y+h, x:x+w])
    return rois

# ── 分类 ──────────────────────────────────────────────────────────────────────

def circle_count(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    blur = cv2.GaussianBlur(gray, (5, 5), 1.5)
    h, w = gray.shape
    minR = max(4, w // 14)
    maxR = max(10, w // 3)
    c = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, 1.2,
                         minDist=minR * 1.8, param1=50, param2=14,
                         minRadius=minR, maxRadius=maxR)
    return 0 if c is None else len(c[0])

def bamboo_sticks(roi):
    """
    垂直边缘峰值法：每根竹对应左右两个边缘 → 峰数 ÷ 2 ≈ 竹节数。
    阈值低至 0.25，能识别 1 根竹节。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    crop = gray[h//5 : h*4//5, :]
    sx = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=3)
    proj = np.abs(sx).sum(axis=0)
    if proj.max() == 0:
        return 0, False
    proj /= proj.max()
    thr = 0.25
    in_p, cnt = False, 0
    for v in proj:
        if not in_p and v >= thr:
            in_p = True; cnt += 1
        elif in_p and v < thr:
            in_p = False
    sticks = max(1, round(cnt / 2))
    is_bamboo = cnt >= 2   # ≥1 根竹（2个边缘峰）
    return min(sticks, 9), is_bamboo

def color_ratios(roi):
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    total = roi.shape[0] * roi.shape[1] * 255 + 1e-6
    # 绿色
    gm = cv2.inRange(hsv, np.array([38, 50, 50]), np.array([90, 255, 255]))
    gr = gm.sum() / total
    # 红色（两段）
    rm1 = cv2.inRange(hsv, np.array([0,  60, 80]), np.array([10, 255, 255]))
    rm2 = cv2.inRange(hsv, np.array([168, 60, 80]), np.array([180, 255, 255]))
    rr = (cv2.bitwise_or(rm1, rm2)).sum() / total
    return gr, rr

def stroke_peaks_top(roi):
    """顶部数字区域的列投影峰数（用于万牌数字估算）。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    top = gray[2:h//3, w//8:w*7//8]
    _, bw = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    proj = bw.sum(axis=0).astype(float)
    if proj.max() == 0:
        return 0
    proj /= proj.max()
    in_p, cnt = False, 0
    for v in proj:
        if not in_p and v >= 0.3:
            in_p = True; cnt += 1
        elif in_p and v < 0.3:
            in_p = False
    return cnt

def classify(roi):
    """返回 (tile_id_or_None, label_for_debug)"""
    cc = circle_count(roi)
    sticks, is_bamboo = bamboo_sticks(roi)
    gr, rr = color_ratios(roi)

    # ── 筒牌 ──────────────────────────────────
    if cc >= 1:
        return f"{min(cc,9)}p", f"筒{min(cc,9)}"

    # ── 条牌 ──────────────────────────────────
    if is_bamboo:
        # 发(6z)：大绿块无竹节纹，绿色面积很大
        if gr > 0.18:
            return "6z", "发"
        return f"{sticks}s", f"条{sticks}"

    # ── 字牌特殊 ──────────────────────────────
    # 发(6z)：高绿，不是竹节但很绿
    if gr > 0.15:
        return "6z", "发"
    # 中(5z)：大红区域
    if rr > 0.12:
        return "5z", "中"

    # ── 万牌：有红色数字 ───────────────────────
    if rr > 0.025:
        peaks = stroke_peaks_top(roi)
        # 一(1)=1峰  二(2)=2  三(3)=3  四(4)≈5  五(5)≈5  六(6)≈4  七(7)≈3  八(8)≈4  九(9)≈5
        # 粗略映射
        mapping = {0:0, 1:1, 2:2, 3:3, 4:4, 5:5, 6:6, 7:7, 8:8, 9:9}
        n = mapping.get(peaks, 0)
        if 1 <= n <= 9:
            return f"{n}m", f"万{n}"
        # 无法确定数字，先保存为候选（返回None，存 debug）
        return None, f"万?峰{peaks}"

    # ── 其余字牌/未知 ──────────────────────────
    return None, f"unk"


# ── 主流程 ────────────────────────────────────────────────────────────────────

def extract():
    cap = cv2.VideoCapture(VIDEO)
    assert cap.isOpened()
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    print(f"视频: {total}帧 @ {fps:.1f}fps")

    saved  = {}         # tile_id -> [(hash, path)]
    all_crops = []      # [(hash, roi, label)] 去重后全部切片
    all_hashes = []

    STEP = 3
    TOL  = 5

    for fi in range(0, total, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        strip = frame[HAND_Y1:HAND_Y2, :]
        rois  = segment_hand(strip)

        for roi in rois:
            if roi.shape[0] < 40 or roi.shape[1] < 30:
                continue
            h_val = dhash(roi)
            if any(hamming(h_val, h2) <= TOL for h2, _, _ in all_crops):
                continue

            tile_id, label = classify(roi)
            all_crops.append((h_val, roi.copy(), label))
            all_hashes.append(h_val)

            if tile_id:
                bucket = saved.setdefault(tile_id, [])
                if not any(hamming(h_val, h2) <= TOL for h2, _ in bucket):
                    proc = preprocess(roi)
                    resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
                    path = os.path.join(TILE_DIR, f"{tile_id}.png")
                    existing = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if os.path.exists(path) else None
                    if existing is None or resized.mean() > existing.mean():
                        cv2.imwrite(path, resized)
                        print(f"  [保存] {tile_id}({label}) frame={fi}")
                    bucket.append((h_val, path))

    cap.release()

    # 保存所有去重切片（供人工核查）
    for i, (_, roi, label) in enumerate(all_crops):
        proc = preprocess(roi)
        resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(DEBUG_ALL, f"{i:03d}_{label}.png"), resized)

    print(f"\n共提取 {len(all_crops)} 个独立牌面，保存模板 {len(saved)} 种")

    extract_buttons(fps)
    print_report(saved)


def extract_buttons(fps):
    cap = cv2.VideoCapture(VIDEO)
    if not cap.isOpened():
        return
    # 保存全部秒 0-20 的按钮条带，供人工裁剪
    for sec in range(0, 20):
        fi = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        strip = frame[340:470, :]
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        # 金色按钮
        gold = cv2.inRange(hsv, np.array([10, 80, 150]), np.array([38, 255, 255]))
        if gold.sum() > 50000:   # 足够多的金色像素才存
            cv2.imwrite(os.path.join(BTN_DIR, f"_strip_sec{sec:02d}.png"), strip)
            print(f"[按钮] sec={sec} 检测到金色像素，已保存条带")
    cap.release()


def print_report(saved):
    found = set(saved.keys())
    groups = [("万",[f"{i}m" for i in range(1,10)]),
              ("筒",[f"{i}p" for i in range(1,10)]),
              ("条",[f"{i}s" for i in range(1,10)]),
              ("字",[f"{i}z" for i in range(1,8)])]
    print("\n" + "="*56)
    for name, ids in groups:
        row = "".join(f"[{t}]" if t in found else f" {t} " for t in ids)
        print(f"{name}: {row}")
    missing = [t for t in ALL_TILES if t not in found]
    print(f"\n已保存: {len(found)}/34   缺失: {missing}")
    print(f"所有切片 → {DEBUG_ALL}")


if __name__ == "__main__":
    extract()
