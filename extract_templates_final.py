"""
最终版：精准提取麻将牌模板
修复：
  - 去掉MORPH_CLOSE（会合并相邻牌，间距仅2px）
  - HoughCircles: minR=w//9(≈8px), param2=25，过滤掉竹节假圆(<8px)
  - 万牌：识别M/W形绿色万字特征
  - 条牌：竹节垂直结构（边缘峰值法）
  - 字牌：排除法，保存到 debug_zi 供人工标注
"""
import cv2
import numpy as np
import os

VIDEO   = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
TILE_DIR  = r"C:\MahjongAI\templates\tiles"
DEBUG_ZI  = r"C:\MahjongAI\templates\debug_zi"    # 未分类字牌/其他
BTN_DIR   = r"C:\MahjongAI\templates\buttons"

TILE_SIZE = (48, 64)
HAND_Y1, HAND_Y2 = 462, 590

ALL_TILES = (
    [f"{i}m" for i in range(1, 10)] +
    [f"{i}p" for i in range(1, 10)] +
    [f"{i}s" for i in range(1, 10)] +
    [f"{i}z" for i in range(1, 8)]
)

for d in [TILE_DIR, DEBUG_ZI, BTN_DIR]:
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

# ── 分割（仅 MORPH_OPEN 去噪点，不 CLOSE）───────────────────────────────────

def segment_hand(strip_bgr):
    hsv = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    rois = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 2000: continue
        if not (40 <= w <= 130 and 55 <= h <= 140): continue
        rois.append(strip_bgr[y:y+h, x:x+w])
    return rois

# ── 筒牌：精准圆圈检测 ────────────────────────────────────────────────────────

def count_tong_circles(roi):
    """
    只检测筒牌主圆（半径 ≥ w//9 ≈ 8px），过滤竹节假圆（<8px）。
    param2=25 要求足够明显的圆边缘。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    blur = cv2.GaussianBlur(gray, (5, 5), 1.5)
    h, w = gray.shape
    minR = max(7, w // 9)   # 9筒时每个圆半径 ≈ w/9
    maxR = max(25, w // 2)  # 1筒时圆半径 ≈ w/2
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=minR * 1.5,
        param1=60, param2=25,
        minRadius=minR, maxRadius=maxR,
    )
    return 0 if circles is None else len(circles[0])

# ── 条牌：垂直边缘计数 ────────────────────────────────────────────────────────

def count_bamboo(roi):
    """
    返回 (竹节数, is_bamboo)。
    每根竹在列投影上产生2个边缘峰，threshold=0.25。
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    crop = gray[h // 5 : h * 4 // 5, :]
    sx = cv2.Sobel(crop, cv2.CV_64F, 1, 0, ksize=3)
    proj = np.abs(sx).sum(axis=0)
    if proj.max() == 0:
        return 0, False
    proj /= proj.max()
    in_p, peaks = False, 0
    for v in proj:
        if not in_p and v >= 0.25: in_p = True;  peaks += 1
        elif in_p and v < 0.25:    in_p = False
    sticks    = max(1, round(peaks / 2))
    is_bamboo = peaks >= 2   # 至少1根竹 = 2个边缘峰
    return min(sticks, 9), is_bamboo

# ── 颜色特征 ──────────────────────────────────────────────────────────────────

def color_features(roi):
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    total = roi.shape[0] * roi.shape[1] * 255 + 1e-6
    gm  = cv2.inRange(hsv, np.array([38, 50, 50]),  np.array([90, 255, 255]))
    rm1 = cv2.inRange(hsv, np.array([0,  60, 80]),  np.array([10, 255, 255]))
    rm2 = cv2.inRange(hsv, np.array([168,60, 80]),  np.array([180,255, 255]))
    gr  = gm.sum() / total
    rr  = cv2.bitwise_or(rm1, rm2).sum() / total
    return gr, rr

# ── 万牌数字（列投影峰数 on 顶部区域）────────────────────────────────────────

def estimate_wan_number(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    h, w = gray.shape
    top = gray[2:h // 3, w // 8:w * 7 // 8]
    _, bw = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    proj = bw.sum(axis=0).astype(float)
    if proj.max() == 0:
        return 0
    proj /= proj.max()
    in_p, cnt = False, 0
    for v in proj:
        if not in_p and v >= 0.3: in_p = True;  cnt += 1
        elif in_p and v < 0.3:    in_p = False
    return cnt  # 直接用峰数估算（一≈1, 二≈2, 三≈3, 四-九较复杂）

# ── 分类主函数 ────────────────────────────────────────────────────────────────

def classify(roi):
    """
    返回 (tile_id | None, debug_label)
    """
    cc         = count_tong_circles(roi)
    sticks, is_bamboo = count_bamboo(roi)
    gr, rr     = color_features(roi)

    # ── 1. 筒牌：检测到真实主圆 ──────────────────────────────────
    if cc >= 1:
        n = min(cc, 9)
        return f"{n}p", f"筒{n}(cc={cc})"

    # ── 2. 发(6z)：大块绿色，不是竹节排列 ─────────────────────
    if gr > 0.18 and not is_bamboo:
        return "6z", "发"

    # ── 3. 中(5z)：大块红色，无圆圈 ───────────────────────────
    if rr > 0.12 and cc == 0:
        return "5z", "中"

    # ── 4. 条牌：有竹节垂直结构 ─────────────────────────────────
    if is_bamboo:
        # 发牌绿色太大时单独处理（已在上面 catch）
        return f"{sticks}s", f"条{sticks}(peaks)"

    # ── 5. 万牌：有红色数字 ─────────────────────────────────────
    if rr > 0.025:
        n = estimate_wan_number(roi)
        if 1 <= n <= 9:
            return f"{n}m", f"万{n}"
        return None, f"万?峰{n}"

    # ── 6. 其他字牌 ─────────────────────────────────────────────
    return None, f"zi_gr{gr:.2f}_rr{rr:.2f}"

# ── 主流程 ────────────────────────────────────────────────────────────────────

def extract():
    cap = cv2.VideoCapture(VIDEO)
    assert cap.isOpened(), f"无法打开视频"
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    print(f"视频 {total}帧 @ {fps:.1f}fps，开始扫描...")

    saved       = {}   # tile_id -> [(hash, path)]
    all_unique  = []   # [(hash, roi, label)] 去重后全部
    all_hashes  = []

    STEP = 3
    TOL  = 5

    for fi in range(0, total, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        strip = frame[HAND_Y1:HAND_Y2, :]
        for roi in segment_hand(strip):
            if roi.shape[0] < 40 or roi.shape[1] < 30:
                continue
            hv = dhash(roi)
            if any(hamming(hv, h2) <= TOL for h2, _, _ in all_unique):
                continue

            tile_id, label = classify(roi)
            all_unique.append((hv, roi.copy(), label))
            all_hashes.append(hv)

            if tile_id:
                bucket = saved.setdefault(tile_id, [])
                if not any(hamming(hv, h2) <= TOL for h2, _ in bucket):
                    proc    = preprocess(roi)
                    resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
                    path    = os.path.join(TILE_DIR, f"{tile_id}.png")
                    existing = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if os.path.exists(path) else None
                    if existing is None or resized.mean() > existing.mean():
                        cv2.imwrite(path, resized)
                        print(f"  [保存] {tile_id} ({label}) frame={fi}")
                    bucket.append((hv, path))

    cap.release()

    # 保存未分类字牌
    zi_idx = 0
    for hv, roi, label in all_unique:
        if label.startswith("zi_") or label.startswith("万?"):
            proc    = preprocess(roi)
            resized = cv2.resize(proc, TILE_SIZE, interpolation=cv2.INTER_AREA)
            cv2.imwrite(os.path.join(DEBUG_ZI, f"{zi_idx:03d}_{label}.png"), resized)
            zi_idx += 1

    print(f"\n共 {len(all_unique)} 个独立牌面，保存模板 {len(saved)} 种，未分类字牌 {zi_idx} 个")
    extract_buttons(fps)
    print_report(saved)

def extract_buttons(fps):
    """保存前20秒中含金色按钮的条带图像。"""
    cap = cv2.VideoCapture(VIDEO)
    if not cap.isOpened():
        return
    found = False
    for sec in range(0, 20):
        fi = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        strip = frame[340:470, :]
        hsv   = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        gold  = cv2.inRange(hsv, np.array([10, 100, 150]), np.array([38, 255, 255]))
        if gold.sum() > 80000:
            path = os.path.join(BTN_DIR, f"_btn_strip_sec{sec:02d}.png")
            cv2.imwrite(path, strip)
            print(f"[按钮] sec={sec} 金色像素充足，已保存: {path}")
            found = True
            break
    if not found:
        # 保存 sec=5-9 供手动裁剪
        for sec in [5, 6, 7, 8, 9]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(os.path.join(BTN_DIR, f"_strip_sec{sec:02d}.png"),
                            frame[320:480, :])
    cap.release()

def print_report(saved):
    found = set(saved.keys())
    groups = [("万", [f"{i}m" for i in range(1,10)]),
              ("筒", [f"{i}p" for i in range(1,10)]),
              ("条", [f"{i}s" for i in range(1,10)]),
              ("字", [f"{i}z" for i in range(1,8)])]
    print("\n" + "=" * 56)
    for name, ids in groups:
        row = "".join(f"[{t}]" if t in found else f" {t} " for t in ids)
        print(f"{name}: {row}")
    missing = [t for t in ALL_TILES if t not in found]
    print(f"\n已保存: {len(found)}/34   缺失: {missing}")
    print(f"字牌/未知 → {DEBUG_ZI}")

if __name__ == "__main__":
    extract()
