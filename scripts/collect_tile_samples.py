"""自动从历史录像关键帧收集麻将牌标注样本。

策略：
  1. 遍历所有 data/session_*/keyframes/*.png
  2. 用 ink 识别器（高置信度结果可信）对手牌区域逐张识别
  3. 置信度 >= CONF_THRESH 的结果作为弱监督标签保存到
     data/tile_samples/{tile_id}/{session}_{frame}_{idx}.png
  4. 同时把已有的 templates/tiles/ 里的模板也加入（如果质量够好）

运行：
  python scripts/collect_tile_samples.py [--min-conf 0.45] [--data-dir data]
"""
from __future__ import annotations
import os
import sys
import argparse
import glob
import json
import cv2
import numpy as np
import logging

# 确保能 import 项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vision.recognizer import TileRecognizer
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("collect")

DEFAULT_MIN_CONF = 0.45  # ink 方法置信度阈值


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def crop_hand_region(frame: np.ndarray, layout: dict, meld_count: int = 0) -> np.ndarray | None:
    """根据 layout 配置裁剪手牌条带。"""
    fh, fw = frame.shape[:2]
    hand = layout.get("self_hand", {})
    meld_unit_w = hand.get("meld_unit_w", 0.12)
    x_ratio = hand.get("x", 0.01) + meld_count * meld_unit_w
    w_ratio = hand.get("w", 0.98) - meld_count * meld_unit_w
    y_ratio = hand.get("y", 0.77)
    h_ratio = hand.get("h", 0.23)

    x = max(0, int(x_ratio * fw))
    y = max(0, int(y_ratio * fh))
    w = min(fw - x, int(w_ratio * fw))
    h = min(fh - y, int(h_ratio * fh))
    if w <= 0 or h <= 0:
        return None
    return frame[y:y + h, x:x + w]


def segment_equal(strip: np.ndarray, n: int = 13) -> list[np.ndarray]:
    """等分切割（最可靠的兜底，确保拿到 n 张）。"""
    if strip is None or strip.size == 0 or n <= 0:
        return []
    h, w = strip.shape[:2]
    # 找白色区域
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
    pix = np.where(white_col > 0.3)[0]
    x_left, x_right = (int(pix[0]), int(pix[-1]) + 1) if len(pix) >= 60 else (0, w)
    tile_w = (x_right - x_left) / n
    pad_x = max(2, int(tile_w * 0.04))
    pad_y = max(2, int(h * 0.06))
    rois = []
    for i in range(n):
        sx1 = int(x_left + i * tile_w) + pad_x
        sx2 = int(x_left + (i + 1) * tile_w) - pad_x
        roi = strip[pad_y:h - pad_y, sx1:sx2]
        if roi.size > 0:
            rois.append(roi)
    return rois


def collect(
    data_dir: str,
    template_dir: str,
    out_dir: str,
    min_conf: float = DEFAULT_MIN_CONF,
    max_per_tile: int = 200,
) -> dict:
    recognizer = TileRecognizer(template_dir)

    config_path = os.path.join(os.path.dirname(data_dir), "config", "settings.yaml")
    config = load_config(config_path) if os.path.exists(config_path) else {}
    layout = config.get("layout", {})

    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}

    # ── 1. 现有 templates/tiles/ 直接加入 ────────────────────────────────
    tile_tmpl_dir = os.path.join(template_dir, "tiles")
    added_tmpl = 0
    if os.path.isdir(tile_tmpl_dir):
        for fname in os.listdir(tile_tmpl_dir):
            if not fname.endswith(".png"):
                continue
            tile_id = fname[:-4]
            img = cv2.imread(os.path.join(tile_tmpl_dir, fname))
            if img is None:
                continue
            dst_dir = os.path.join(out_dir, tile_id)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, "tmpl_00.png")
            cv2.imwrite(dst, img)
            counts[tile_id] = counts.get(tile_id, 0) + 1
            added_tmpl += 1
    logger.info("模板库：%d 张牌图已加入样本", added_tmpl)

    # ── 2. 从历史 session 关键帧收集 ─────────────────────────────────────
    frame_paths = sorted(glob.glob(os.path.join(data_dir, "session_*", "keyframes", "*.png")))
    logger.info("找到关键帧：%d 张", len(frame_paths))

    total_saved = 0
    total_skipped = 0

    for fp in frame_paths:
        frame = cv2.imread(fp)
        if frame is None:
            continue
        session_name = os.path.basename(os.path.dirname(os.path.dirname(fp)))
        frame_name = os.path.splitext(os.path.basename(fp))[0]

        # 从 frame_details.jsonl 读取 meld_count（如果有）
        meld_count = 0
        details_path = os.path.join(os.path.dirname(os.path.dirname(fp)), "frame_details.jsonl")
        if os.path.exists(details_path):
            with open(details_path, "r", encoding="utf-8") as df:
                for line in df:
                    try:
                        d = json.loads(line)
                        if d.get("frame_name") == frame_name or d.get("frame_index") == int(frame_name.split("_")[-1]):
                            meld_count = d.get("meld_count", 0)
                            break
                    except Exception:
                        continue

        strip = crop_hand_region(frame, layout, meld_count)
        if strip is None:
            continue

        rois = segment_equal(strip, 13 - meld_count * 3)
        if not rois:
            continue

        for idx, roi in enumerate(rois):
            result = recognizer.match_tile(roi)
            if result.tile_id is None or result.confidence < min_conf:
                total_skipped += 1
                continue

            tile_id = result.tile_id
            if counts.get(tile_id, 0) >= max_per_tile:
                continue

            dst_dir = os.path.join(out_dir, tile_id)
            os.makedirs(dst_dir, exist_ok=True)
            fname = f"{session_name}_{frame_name}_{idx:02d}.png"
            cv2.imwrite(os.path.join(dst_dir, fname), roi)
            counts[tile_id] = counts.get(tile_id, 0) + 1
            total_saved += 1

    logger.info("收集完成：保存 %d 张，跳过 %d 张（低置信度）", total_saved, total_skipped)
    logger.info("各类别样本数：")
    for tid in sorted(counts):
        logger.info("  %-6s: %d", tid, counts[tid])
    missing = [tid for tid in _ALL_TILES if tid not in counts]
    if missing:
        logger.warning("缺少样本的牌类（%d 种）：%s", len(missing), missing)
    return counts


_ALL_TILES = (
    [f"{i}m" for i in range(1, 10)]
    + [f"{i}p" for i in range(1, 10)]
    + [f"{i}s" for i in range(1, 10)]
    + [f"{i}z" for i in range(1, 8)]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="收集麻将牌训练样本")
    parser.add_argument("--data-dir", default="data", help="data 目录")
    parser.add_argument("--template-dir", default="templates", help="模板目录")
    parser.add_argument("--out-dir", default="data/tile_samples", help="输出样本目录")
    parser.add_argument("--min-conf", type=float, default=DEFAULT_MIN_CONF, help="最低置信度阈值")
    parser.add_argument("--max-per-tile", type=int, default=200, help="每种牌最多保存数量")
    args = parser.parse_args()

    collect(
        data_dir=args.data_dir,
        template_dir=args.template_dir,
        out_dir=args.out_dir,
        min_conf=args.min_conf,
        max_per_tile=args.max_per_tile,
    )
