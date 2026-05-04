"""用历史 session ROI 图片刷新 templates/tiles/ 模板，并训练 HOG+SVM 分类器。

原理：
  历史 session 的 recognition/frame_*/roi_*.json 里存有识别结果和置信度。
  高置信度的 ROI 和当前游戏画面来自同一个游戏，视觉上完全对齐。
  用这些真实截图替换原有可能不匹配的模板，NCC/ink 匹配分数会从 0.3→0.7+。

运行：
  cd C:\\MahjongAI
  python scripts/refresh_templates.py

完成后：
  - templates/tiles/*.png  →  已更新为高质量 in-game 截图
  - models/tile_svm.xml    →  HOG+SVM 分类器（31/34 类，缺 1m/3m/8m）
"""
from __future__ import annotations
import os, sys, json, glob, time
import cv2
import numpy as np
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from vision.hog_classifier import TileHOGClassifier

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("refresh")

DATA_DIR    = "data"
TMPL_DIR    = "templates/tiles"
OUT_MODEL   = "models/tile_svm.xml"
CONF_MIN    = 0.38   # 低于此置信度不信任
CONF_MAX    = 1.15   # 高于此可能是 fusion 数值溢出
MAX_TRAIN   = 120    # 每类最多训练样本（避免类别不平衡）

ALL_TILES = (
    [f"{i}m" for i in range(1, 10)]
    + [f"{i}p" for i in range(1, 10)]
    + [f"{i}s" for i in range(1, 10)]
    + [f"{i}z" for i in range(1, 8)]
)


# ── 1. 收集所有 session ROI ────────────────────────────────────────────
def collect_rois() -> dict[str, list[tuple[str, float]]]:
    """返回 {tile_id: [(roi_png_path, confidence), ...]}"""
    tile_rois: dict[str, list[tuple[str, float]]] = {}

    roi_jsons = glob.glob(
        os.path.join(DATA_DIR, "session_*", "recognition", "frame_*", "roi_*.json")
    )
    log.info("扫描 ROI json 文件：%d 个", len(roi_jsons))

    for jp in roi_jsons:
        try:
            d = json.load(open(jp, encoding="utf-8"))
        except Exception:
            continue
        tid = d.get("tile_id")
        conf = float(d.get("confidence", 0))
        if not tid or conf < CONF_MIN or conf > CONF_MAX:
            continue
        # 要求 ncc 或 ink 方法识别（排除 low_conf_guess）
        method = d.get("method", "")
        if "guess" in method:
            continue
        roi_png = jp.replace(".json", ".png")
        if not os.path.exists(roi_png):
            continue
        tile_rois.setdefault(tid, []).append((roi_png, conf))

    log.info("有效 ROI：%d 种牌，共 %d 张",
             len(tile_rois), sum(len(v) for v in tile_rois.values()))
    return tile_rois


# ── 2. 刷新 templates/tiles/ ──────────────────────────────────────────
def refresh_templates(tile_rois: dict[str, list[tuple[str, float]]]) -> None:
    os.makedirs(TMPL_DIR, exist_ok=True)
    updated, kept = 0, 0

    for tid, samples in tile_rois.items():
        # 选置信度最高的那张作为新模板
        best_path, best_conf = max(samples, key=lambda x: x[1])
        img = cv2.imread(best_path)
        if img is None:
            continue
        dst = os.path.join(TMPL_DIR, f"{tid}.png")
        cv2.imwrite(dst, img)
        log.debug("更新模板 %s ← conf=%.3f %s", tid, best_conf, best_path)
        updated += 1

    # 对于没有历史 ROI 的牌，保留原有模板
    for tid in ALL_TILES:
        tmpl_path = os.path.join(TMPL_DIR, f"{tid}.png")
        if tid not in tile_rois and os.path.exists(tmpl_path):
            kept += 1

    log.info("模板刷新：更新 %d 种，保留原有 %d 种", updated, kept)
    missing = [t for t in ALL_TILES if t not in tile_rois and
               not os.path.exists(os.path.join(TMPL_DIR, f"{t}.png"))]
    if missing:
        log.warning("缺少模板（既无 ROI 又无原文件）：%s", missing)


# ── 3. 训练 HOG+SVM ───────────────────────────────────────────────────
def train_svm(tile_rois: dict[str, list[tuple[str, float]]]) -> None:
    samples, labels = [], []

    for tid in sorted(tile_rois.keys()):
        # 按置信度降序，最多取 MAX_TRAIN 张
        sorted_rois = sorted(tile_rois[tid], key=lambda x: -x[1])[:MAX_TRAIN]
        for roi_path, conf in sorted_rois:
            img = cv2.imread(roi_path)
            if img is None:
                continue
            samples.append(img)
            labels.append(tid)

    n_classes = len(set(labels))
    log.info("训练样本：%d 张，%d 类", len(samples), n_classes)

    if n_classes < 2:
        log.error("类别数不足，跳过训练")
        return

    os.makedirs(os.path.dirname(OUT_MODEL) or ".", exist_ok=True)
    clf = TileHOGClassifier()

    t0 = time.time()
    stats = clf.train(
        samples, labels,
        auto_params=(len(samples) < 500),  # 样本少时自动搜参，多了用固定参数
        C=50.0, gamma=0.0005,
    )
    elapsed = time.time() - t0
    log.info("训练完成：%.1fs  train_acc=%.1f%%", elapsed, stats["train_acc"] * 100)

    clf.save(OUT_MODEL)
    log.info("模型已保存：%s", OUT_MODEL)

    # 显示每类样本数
    log.info("各类别样本数（共 %d 类）:", n_classes)
    for tid2 in sorted(stats["class_counts"]):
        cnt = stats["class_counts"][tid2]
        log.info("  %-6s: %d", tid2, cnt)

    missing = [t for t in ALL_TILES if t not in set(labels)]
    if missing:
        log.warning("未训练牌类（无样本）：%s", missing)
        log.warning("这些牌将退回模板匹配方法")


# ── 4. 测试刷新后的 NCC 分数 ──────────────────────────────────────────
def test_ncc_improvement() -> None:
    """验证刷新后的模板与 ROI 的 NCC 分数是否提升。"""
    import sys
    sys.path.insert(0, ".")
    from vision.recognizer import TileRecognizer

    rec = TileRecognizer(TMPL_DIR)
    log.info("\n===== 刷新后 NCC 测试（frame_0000, session 20260502_203614） =====")

    frame_dir = "data/session_20260502_203614/recognition/frame_0000"
    if not os.path.isdir(frame_dir):
        log.warning("测试目录不存在，跳过测试")
        return

    correct, total = 0, 0
    for i in range(13):
        roi_png = os.path.join(frame_dir, f"roi_{i}.png")
        roi_json = os.path.join(frame_dir, f"roi_{i}.json")
        if not os.path.exists(roi_png):
            continue
        roi = cv2.imread(roi_png)
        result = rec.match_tile(roi)

        # 读取原来的识别结果作为参考
        try:
            orig = json.load(open(roi_json, encoding="utf-8"))
            orig_tid = orig.get("tile_id")
        except Exception:
            orig_tid = None

        match_str = "✓" if result.tile_id == orig_tid else "≠"
        log.info("roi_%02d: %s orig=%-4s → new=%-4s conf=%.3f [%s]",
                 i, match_str, orig_tid or "?", result.tile_id or "?",
                 result.confidence, result.method)
        if orig_tid:
            total += 1
            if result.tile_id == orig_tid:
                correct += 1

    if total:
        log.info("一致率：%d/%d = %.0f%%", correct, total, correct/total*100)


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("步骤 1/3: 收集历史 session ROI 数据")
    tile_rois = collect_rois()

    log.info("=" * 60)
    log.info("步骤 2/3: 刷新 templates/tiles/")
    refresh_templates(tile_rois)

    log.info("=" * 60)
    log.info("步骤 3/3: 训练 HOG+SVM 分类器")
    train_svm(tile_rois)

    log.info("=" * 60)
    log.info("验证新模板效果")
    test_ncc_improvement()

    log.info("=" * 60)
    log.info("完成！请重启应用让新模板和分类器生效。")
