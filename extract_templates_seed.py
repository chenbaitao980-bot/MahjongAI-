"""
策略：手工标记帧0 → 模板匹配扫全视频捕获更多牌种
1. 帧0 14张牌已人工目视确认，硬编码 x位置 → tile_id
2. 保存为初始模板
3. 用 TM_CCOEFF_NORMED 扫全片，当匹配某模板置信度 < SAVE_NEW_THR 时
   说明是新牌种，保存供人工补充标注
"""
import cv2
import numpy as np
import os

VIDEO    = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
TILE_DIR = r"C:\MahjongAI\templates\tiles"
NEW_DIR  = r"C:\MahjongAI\templates\new_candidates"  # 疑似新牌种
BTN_DIR  = r"C:\MahjongAI\templates\buttons"

TILE_SIZE     = (48, 64)   # w × h
HAND_Y1, HAND_Y2 = 462, 590
MATCH_THR     = 0.75       # 低于此值 → 可能是新牌种
SAVE_NEW_THR  = 0.55       # 低于此值 → 一定是新的，保存

for d in [TILE_DIR, NEW_DIR, BTN_DIR]:
    os.makedirs(d, exist_ok=True)

# ── 帧0 手工标记（x位置容差 ±10px）──────────────────────────────────────────
FRAME0_MAP = {
    67:   "3s",   # 3条（绿竹节）
    148:  "2s",   # 2条（绿+红）
    229:  "3m",   # 3万
    392:  "3s",   # 3条（全红变体，可能覆盖为更清晰的模板）
    474:  "1p",   # 1筒
    555:  "2p",   # 2筒（绿同心圆）
    637:  "2p",   # 2筒（红变体）
    718:  "2p",   # 2筒（另一红变体）
    799:  "8p",   # 8筒
    881:  "8p",   # 8筒（重复）
    962:  "3p",   # 3筒
    1044: "4z",   # 北
    1134: "2s",   # 2条（重复）
    # 311: 3万重复，跳过
}

# ── 工具 ──────────────────────────────────────────────────────────────────────

def dhash(img, size=8):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size))
    return sum(bool(b) << i for i, b in enumerate((small[:,1:] > small[:,:-1]).flatten()))

def hamming(a, b):
    return bin(a ^ b).count('1')

def preprocess(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    return cv2.resize(clahe.apply(gray), TILE_SIZE, interpolation=cv2.INTER_AREA)

def segment_hand(strip_bgr):
    """白色掩码 + OPEN去噪（不用CLOSE，避免2px间距的牌合并）。"""
    hsv  = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
    k    = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    tiles = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 2000 or not (40 <= w <= 130 and 55 <= h <= 140):
            continue
        tiles.append((x, strip_bgr[y:y+h, x:x+w]))
    return tiles   # [(x, roi_bgr), ...]

# ── 第一步：保存帧0种子模板 ───────────────────────────────────────────────────

def seed_from_frame0(frame):
    strip = frame[HAND_Y1:HAND_Y2, :]
    tiles = segment_hand(strip)
    seeded = {}
    for (tx, roi) in tiles:
        # 匹配 FRAME0_MAP（容差 ±15px）
        tile_id = None
        for x0, tid in FRAME0_MAP.items():
            if abs(tx - x0) <= 15:
                tile_id = tid
                break
        if tile_id is None:
            continue

        proc = preprocess(roi)
        path = os.path.join(TILE_DIR, f"{tile_id}.png")
        existing = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        # 保留亮度更高（更清晰）的版本
        if existing is None or proc.mean() > existing.mean():
            cv2.imwrite(path, proc)
            seeded[tile_id] = True
            print(f"  [种子] {tile_id}  x={tx}")

    print(f"帧0种子: {len(seeded)} 种牌 → {list(seeded.keys())}")
    return seeded

# ── 第二步：模板匹配扫全片 ────────────────────────────────────────────────────

def load_templates():
    """从 TILE_DIR 加载所有已有模板。"""
    tmpl = {}
    for f in os.listdir(TILE_DIR):
        if not f.endswith('.png'):
            continue
        tid = f[:-4]
        img = cv2.imread(os.path.join(TILE_DIR, f), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            tmpl[tid] = img
    return tmpl

def match_tile(roi_gray, templates):
    """返回 (best_tile_id, best_conf)。"""
    best_id, best_conf = None, -1.0
    for tid, tmpl in templates.items():
        try:
            res = cv2.matchTemplate(roi_gray, tmpl, cv2.TM_CCOEFF_NORMED)
            conf = float(res.max())
        except Exception:
            continue
        if conf > best_conf:
            best_conf = conf
            best_id   = tid
    return best_id, best_conf

def scan_video(fps):
    """
    扫描全片：每帧每张牌与已有模板匹配，
    若最高置信度 < SAVE_NEW_THR，视为新牌种，存入 new_candidates。
    """
    templates = load_templates()
    print(f"\n加载 {len(templates)} 个模板，开始扫描...")

    cap = cv2.VideoCapture(VIDEO)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    new_hashes = []
    new_idx    = 0
    found_new  = {}   # label -> count

    STEP = 4
    for fi in range(0, total, STEP):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue

        strip = frame[HAND_Y1:HAND_Y2, :]
        tiles = segment_hand(strip)

        for (tx, roi) in tiles:
            proc = preprocess(roi)
            hv   = dhash(proc)

            # 已知哈希跳过
            if any(hamming(hv, h2) <= 5 for h2 in new_hashes):
                continue

            best_id, best_conf = match_tile(proc, templates)

            if best_conf < SAVE_NEW_THR:
                # 新牌种候选
                new_hashes.append(hv)
                label = f"new_{new_idx:03d}_conf{best_conf:.2f}_best{best_id}"
                path  = os.path.join(NEW_DIR, f"{label}.png")
                cv2.imwrite(path, proc)
                new_idx += 1
                found_new[label] = fi

            elif best_conf < MATCH_THR:
                # 同类但置信度偏低：可能是更好的模板变体
                new_hashes.append(hv)
                label = f"variant_{new_idx:03d}_{best_id}_conf{best_conf:.2f}"
                cv2.imwrite(os.path.join(NEW_DIR, f"{label}.png"), proc)
                new_idx += 1

    cap.release()
    print(f"新候选牌面: {new_idx} 个 → {NEW_DIR}")
    return found_new

# ── 按钮提取 ──────────────────────────────────────────────────────────────────

def extract_buttons(fps):
    cap = cv2.VideoCapture(VIDEO)
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
            cv2.imwrite(os.path.join(BTN_DIR, f"_strip_sec{sec:02d}.png"), strip)
            print(f"[按钮] sec={sec} 已保存条带")
            break
    else:
        for sec in [5, 6, 7, 8, 9]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(os.path.join(BTN_DIR, f"_strip_sec{sec:02d}.png"),
                            frame[320:480, :])
    cap.release()

# ── 报告 ─────────────────────────────────────────────────────────────────────

def print_report():
    ALL = ([f"{i}m" for i in range(1,10)] + [f"{i}p" for i in range(1,10)] +
           [f"{i}s" for i in range(1,10)] + [f"{i}z" for i in range(1,8)])
    found = {f[:-4] for f in os.listdir(TILE_DIR) if f.endswith('.png')}
    groups = [("万",[f"{i}m" for i in range(1,10)]),
              ("筒",[f"{i}p" for i in range(1,10)]),
              ("条",[f"{i}s" for i in range(1,10)]),
              ("字",[f"{i}z" for i in range(1,8)])]
    print("\n" + "="*56)
    for name, ids in groups:
        row = "".join(f"[{t}]" if t in found else f" {t} " for t in ids)
        print(f"{name}: {row}")
    missing = [t for t in ALL if t not in found]
    print(f"\n已保存: {len(found)}/34   缺失: {missing}")

# ── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cap0 = cv2.VideoCapture(VIDEO)
    fps  = cap0.get(cv2.CAP_PROP_FPS)
    cap0.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame0 = cap0.read()
    cap0.release()

    print("── 第一步：帧0种子标注 ──")
    seed_from_frame0(frame0)

    print("\n── 第二步：全片模板匹配扫描 ──")
    scan_video(fps)

    print("\n── 第三步：按钮提取 ──")
    extract_buttons(fps)

    print_report()
