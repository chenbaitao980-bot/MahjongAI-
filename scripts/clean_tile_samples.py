"""清洗 tile_samples 训练数据。

策略：
1. 尺寸筛选 —— 剔除明显不是单张牌的图
2. 帧间去重 —— 同一视频+位置连续帧去重（用平均哈希）
3. 标签校验 —— 用现有模板交叉验证，筛掉标签明显错误的
4. 重新分类 _unclassified —— 尝试用模板匹配把能认出的移回对应类
5. 统一 resize 到 48×64
6. 输出到新目录，保留原始数据
"""
from __future__ import annotations
import os
import sys
import shutil
import glob
import hashlib
import argparse
import cv2
import numpy as np
import logging
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from game.state import ALL_TILE_IDS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("clean_samples")

# 目标尺寸
TILE_W, TILE_H = 48, 64

# 正常单张牌的尺寸范围（基于观察数据）
MIN_W, MAX_W = 32, 55
MIN_H, MAX_H = 45, 80
MIN_RATIO, MAX_RATIO = 0.50, 0.95  # w/h


def avg_hash(img: np.ndarray, size: int = 16) -> str:
    """计算平均哈希（aHash），用于快速去重。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    mean = resized.mean()
    bits = (resized > mean).astype(np.uint8)
    # 转为 16 进制字符串
    hex_str = ""
    for i in range(size):
        for j in range(0, size, 4):
            n = (bits[i, j] << 3) | (bits[i, j+1] << 2) | (bits[i, j+2] << 1) | bits[i, j+3]
            hex_str += format(n, "x")
    return hex_str


def hamming_distance(h1: str, h2: str) -> int:
    """计算两个 16x16 aHash 的汉明距离（最大 256）。"""
    d = 0
    for c1, c2 in zip(h1, h2):
        x = int(c1, 16) ^ int(c2, 16)
        d += (x & 8) >> 3
        d += (x & 4) >> 2
        d += (x & 2) >> 1
        d += x & 1
    return d


def is_valid_size(img: np.ndarray) -> bool:
    """判断尺寸是否像单张牌。"""
    if img is None or img.size == 0:
        return False
    h, w = img.shape[:2]
    ratio = w / max(h, 1)
    if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
        return False
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        return False
    return True


def load_templates(template_dir: str) -> dict[str, np.ndarray]:
    """加载现有模板用于交叉验证。"""
    templates: dict[str, np.ndarray] = {}
    if not os.path.isdir(template_dir):
        return templates
    for fname in sorted(os.listdir(template_dir)):
        if not fname.endswith(".png"):
            continue
        tile_id = fname[:-4]
        if tile_id not in ALL_TILE_IDS:
            continue
        path = os.path.join(template_dir, fname)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[tile_id] = cv2.resize(img, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)
    logger.info("加载模板 %d 张", len(templates))
    return templates


def ncc_score(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关，两图需同尺寸。"""
    if a.shape != b.shape:
        return -1.0
    a_f = a.astype(np.float32).flatten()
    b_f = b.astype(np.float32).flatten()
    a_norm = a_f - a_f.mean()
    b_norm = b_f - b_f.mean()
    denom = np.linalg.norm(a_norm) * np.linalg.norm(b_norm)
    if denom < 1e-6:
        return -1.0
    return float(np.dot(a_norm, b_norm) / denom)


def cross_validate(img: np.ndarray, templates: dict[str, np.ndarray], label: str) -> tuple[bool, str, float]:
    """
    用模板对单张图做交叉验证。
    Returns:
        (是否通过, 预测标签, 最佳分数)
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    gray = cv2.resize(gray, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)

    best_id = None
    best_score = -1.0
    scores: dict[str, float] = {}
    for tid, tmpl in templates.items():
        s = ncc_score(gray, tmpl)
        scores[tid] = s
        if s > best_score:
            best_score = s
            best_id = tid

    if best_id is None:
        return False, None, 0.0

    # 通过条件：预测标签 == 自身标签，且分数足够高
    passed = (best_id == label) and (best_score >= 0.45)
    return passed, best_id, best_score


def parse_source_info(fname: str) -> tuple[str | None, int | None, int | None]:
    """
    从文件名解析视频源信息。
    例: 028c8ada..._f10020_12.png -> (hash, frame_ms, slot_idx)
    """
    base = os.path.splitext(fname)[0]
    parts = base.split("_")
    if len(parts) >= 3 and parts[-2].startswith("f") and parts[-1].isdigit():
        vhash = "_".join(parts[:-2])
        frame_ms = int(parts[-2][1:])
        slot_idx = int(parts[-1])
        return vhash, frame_ms, slot_idx
    # 简化格式: xxx_01.png
    if len(parts) == 2 and parts[-1].isdigit():
        return parts[0], None, int(parts[-1])
    return base, None, None


def clean_folder(
    src_dir: str,
    dst_dir: str,
    tile_id: str,
    templates: dict[str, np.ndarray],
    dedup_thresh: int = 8,
    cross_val: bool = True,
) -> dict:
    """清洗单个类别的文件夹。"""
    files = sorted(glob.glob(os.path.join(src_dir, tile_id, "*.png")))
    if not files:
        return {"kept": 0, "removed_size": 0, "removed_dup": 0, "removed_cross": 0}

    # 1. 尺寸筛选 + 计算 hash
    valid_items = []
    removed_size = 0
    for path in files:
        img = cv2.imread(path)
        if img is None:
            removed_size += 1
            continue
        if not is_valid_size(img):
            removed_size += 1
            continue
        h = avg_hash(img)
        valid_items.append({"path": path, "img": img, "hash": h})

    # 2. 帧间去重：按 (视频hash, slot_idx) 分组，组内按时间排序，去重
    groups = defaultdict(list)
    for item in valid_items:
        vhash, fms, slot = parse_source_info(os.path.basename(item["path"]))
        key = (vhash, slot if slot is not None else 0)
        groups[key].append((fms if fms is not None else 0, item))

    deduped = []
    removed_dup = 0
    for key, items in groups.items():
        items.sort(key=lambda x: x[0])
        kept_hashes = []
        for _, item in items:
            h = item["hash"]
            # 与已保留的比较汉明距离
            is_dup = False
            for kh in kept_hashes:
                if hamming_distance(h, kh) <= dedup_thresh:
                    is_dup = True
                    break
            if is_dup:
                removed_dup += 1
            else:
                kept_hashes.append(h)
                deduped.append(item)

    # 3. 交叉验证（可选）
    final_kept = []
    removed_cross = 0
    if cross_val and templates:
        for item in deduped:
            passed, pred, score = cross_validate(item["img"], templates, tile_id)
            if passed:
                final_kept.append(item)
            else:
                removed_cross += 1
                # 保存到可疑目录供人工复查
                bad_dir = os.path.join(dst_dir, "_suspicious", tile_id)
                os.makedirs(bad_dir, exist_ok=True)
                shutil.copy2(item["path"], os.path.join(bad_dir, os.path.basename(item["path"])))
    else:
        final_kept = deduped

    # 4. 保存清洗后的图（统一 resize）
    out_folder = os.path.join(dst_dir, tile_id)
    os.makedirs(out_folder, exist_ok=True)
    for item in final_kept:
        img = item["img"]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        resized = cv2.resize(gray, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)
        out_path = os.path.join(out_folder, os.path.basename(item["path"]))
        cv2.imwrite(out_path, resized)

    return {
        "kept": len(final_kept),
        "removed_size": removed_size,
        "removed_dup": removed_dup,
        "removed_cross": removed_cross,
    }


def reclassify_unclassified(
    src_dir: str,
    dst_dir: str,
    templates: dict[str, np.ndarray],
    min_score: float = 0.55,
) -> dict:
    """尝试把 _unclassified 里的有效图重新分类。"""
    files = sorted(glob.glob(os.path.join(src_dir, "_unclassified", "*.png")))
    if not files:
        return {"reclassified": 0, "removed": 0}

    reclassified = 0
    removed = 0
    for path in files:
        img = cv2.imread(path)
        if img is None:
            removed += 1
            continue
        if not is_valid_size(img):
            removed += 1
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
        gray = cv2.resize(gray, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)

        best_id = None
        best_score = -1.0
        for tid, tmpl in templates.items():
            s = ncc_score(gray, tmpl)
            if s > best_score:
                best_score = s
                best_id = tid

        if best_id is not None and best_score >= min_score:
            out_folder = os.path.join(dst_dir, best_id)
            os.makedirs(out_folder, exist_ok=True)
            fname = os.path.basename(path)
            # 避免覆盖
            out_path = os.path.join(out_folder, fname)
            counter = 1
            while os.path.exists(out_path):
                stem, ext = os.path.splitext(fname)
                out_path = os.path.join(out_folder, f"{stem}_{counter:03d}{ext}")
                counter += 1
            cv2.imwrite(out_path, gray)
            reclassified += 1
        else:
            removed += 1

    return {"reclassified": reclassified, "removed": removed}


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗麻将牌训练样本")
    parser.add_argument("--src", default="data/tile_samples", help="原始样本目录")
    parser.add_argument("--dst", default="data/tile_samples_cleaned", help="清洗后输出目录")
    parser.add_argument("--templates", default="data/templates/tiles", help="模板目录（用于交叉验证）")
    parser.add_argument("--no-cross-val", action="store_true", help="跳过交叉验证（保留所有尺寸/去重通过的图）")
    parser.add_argument("--dedup-thresh", type=int, default=8, help="去重汉明距离阈值（默认8，越大越严格）")
    args = parser.parse_args()

    src_dir = os.path.abspath(args.src)
    dst_dir = os.path.abspath(args.dst)
    template_dir = os.path.abspath(args.templates)

    if not os.path.isdir(src_dir):
        logger.error("源目录不存在：%s", src_dir)
        sys.exit(1)

    os.makedirs(dst_dir, exist_ok=True)

    # 加载模板
    templates = load_templates(template_dir)
    do_cross = (not args.no_cross_val) and bool(templates)

    logger.info("=" * 60)
    logger.info("开始清洗样本")
    logger.info("  源目录: %s", src_dir)
    logger.info("  输出目录: %s", dst_dir)
    logger.info("  模板: %d 张", len(templates))
    logger.info("  交叉验证: %s", "启用" if do_cross else "跳过")
    logger.info("=" * 60)

    total_stats = {"kept": 0, "removed_size": 0, "removed_dup": 0, "removed_cross": 0}

    for tile_id in ALL_TILE_IDS:
        stats = clean_folder(src_dir, dst_dir, tile_id, templates, args.dedup_thresh, do_cross)
        total_stats["kept"] += stats["kept"]
        total_stats["removed_size"] += stats["removed_size"]
        total_stats["removed_dup"] += stats["removed_dup"]
        total_stats["removed_cross"] += stats["removed_cross"]
        logger.info(
            "  %-3s: 保留 %4d | 尺寸筛 %4d | 去重 %4d | 交叉筛 %4d",
            tile_id,
            stats["kept"],
            stats["removed_size"],
            stats["removed_dup"],
            stats["removed_cross"],
        )

    # 处理 _unclassified
    if os.path.isdir(os.path.join(src_dir, "_unclassified")):
        rc_stats = reclassify_unclassified(src_dir, dst_dir, templates)
        logger.info(
            "  _unclassified: 重分类 %4d | 丢弃 %4d",
            rc_stats["reclassified"],
            rc_stats["removed"],
        )
        total_stats["kept"] += rc_stats["reclassified"]

    logger.info("=" * 60)
    logger.info("清洗完成")
    logger.info("  总计保留: %d", total_stats["kept"])
    logger.info("  尺寸筛除: %d", total_stats["removed_size"])
    logger.info("  去重筛除: %d", total_stats["removed_dup"])
    logger.info("  交叉验证筛除: %d", total_stats["removed_cross"])
    logger.info("  输出目录: %s", dst_dir)
    logger.info("=" * 60)

    # 如果启用了交叉验证，提醒用户检查 _suspicious
    if do_cross:
        sus_dir = os.path.join(dst_dir, "_suspicious")
        if os.path.isdir(sus_dir):
            n = sum(len(files) for _, _, files in os.walk(sus_dir))
            logger.info("⚠️ 有 %d 张图被标记为可疑，请人工检查: %s", n, sus_dir)


if __name__ == "__main__":
    main()
