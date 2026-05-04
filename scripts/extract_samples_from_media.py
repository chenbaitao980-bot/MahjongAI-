"""从微信视频/图片中提取麻将牌训练样本。

用法：
  python scripts/extract_samples_from_media.py --src "C:/Users/.../video/2026-05" --out data/tile_samples

策略：
  1. 遍历所有 .jpg/.png（截图）和 .mp4（视频抽帧）
  2. 检测画面底部的手牌区域（绿色背景上的白色/暗色牌块）
  3. 等分手牌区域为 13 张牌
  4. 用现有模板做初步识别，高置信度的作为标签保存
  5. 低置信度的保存到 unclassified/ 供人工标注
"""
from __future__ import annotations
import os
import sys
import argparse
import glob
import cv2
import numpy as np
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vision.recognizer import TileRecognizer
from vision.hog_classifier import extract_hog

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("extract_samples")

DEFAULT_MIN_CONF = 0.35  # 比 collect_tile_samples 更低，增加收集量


def detect_hand_region(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """检测画面底部的手牌区域。

    返回 (x, y, w, h) 或 None。
    策略：找画面底部 15-30% 区域内的高饱和度/高亮度块。
    """
    h, w = frame.shape[:2]
    # 关注底部 35% 区域
    bottom = frame[int(h * 0.65):, :]
    bh, bw = bottom.shape[:2]

    if len(bottom.shape) != 3:
        return None

    hsv = cv2.cvtColor(bottom, cv2.COLOR_BGR2HSV)

    # 策略A：白色牌面（亮色界面）
    white_mask = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).astype(np.uint8) * 255
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5)))

    # 找最大的白色连通块
    n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(white_mask)
    best = None
    best_area = 0
    for label in range(1, n_labels):
        x, y, bw2, bh2, area = [int(v) for v in stats[label]]
        if area > best_area and bw2 > bw * 0.3 and bh2 > bh * 0.3:
            best_area = area
            best = (x, y, bw2, bh2)

    if best:
        x, y, rw, rh = best
        return (x, int(h * 0.65) + y, rw, rh)

    # 策略B：暗色牌面（暗色界面）
    dark_mask = ((hsv[:, :, 1] > 25) & (hsv[:, :, 2] > 40)).astype(np.uint8) * 255
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5)))

    n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(dark_mask)
    best = None
    best_area = 0
    for label in range(1, n_labels):
        x, y, bw2, bh2, area = [int(v) for v in stats[label]]
        if area > best_area and bw2 > bw * 0.3 and bh2 > bh * 0.3:
            best_area = area
            best = (x, y, bw2, bh2)

    if best:
        x, y, rw, rh = best
        return (x, int(h * 0.65) + y, rw, rh)

    return None


def segment_hand_strip(strip: np.ndarray, n: int = 13) -> list[np.ndarray]:
    """等分切割手牌条带为 n 张牌。"""
    if strip is None or strip.size == 0 or n <= 0:
        return []
    h, w = strip.shape[:2]

    # 找牌区边界
    if len(strip.shape) == 3:
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        v_mean = int(hsv[:, :, 2].mean())
        if v_mean > 120:
            white_col = ((hsv[:, :, 2] > 140) & (hsv[:, :, 1] < 100)).mean(axis=0)
            pix = np.where(white_col > 0.3)[0]
        else:
            content_col = ((hsv[:, :, 1] > 20) & (hsv[:, :, 2] > 40)).mean(axis=0)
            pix = np.where(content_col > 0.25)[0]
    else:
        pix = np.where(strip.mean(axis=0) > 40)[0]

    x_left, x_right = (int(pix[0]), int(pix[-1]) + 1) if len(pix) >= 60 else (0, w)
    tile_w = (x_right - x_left) / n
    pad_x = max(2, int(tile_w * 0.04))
    pad_y = max(2, int(h * 0.06))

    rois = []
    for i in range(n):
        sx1 = int(x_left + i * tile_w) + pad_x
        sx2 = int(x_left + (i + 1) * tile_w) - pad_x
        if sx2 > sx1:
            roi = strip[pad_y:h - pad_y, sx1:sx2]
            if roi.size > 0:
                rois.append(roi)
    return rois


def extract_from_image(image_path: str, recognizer: TileRecognizer, out_dir: str, unclassified_dir: str, min_conf: float) -> dict:
    """从单张图片提取样本。"""
    frame = cv2.imread(image_path)
    if frame is None:
        return {"saved": 0, "skipped": 0}

    hand_rect = detect_hand_region(frame)
    if hand_rect is None:
        logger.warning("未检测到手牌区域: %s", os.path.basename(image_path))
        return {"saved": 0, "skipped": 0}

    x, y, w, h = hand_rect
    strip = frame[y:y + h, x:x + w]
    rois = segment_hand_strip(strip, n=13)

    saved = 0
    skipped = 0
    for idx, roi in enumerate(rois):
        result = recognizer.match_tile(roi)

        if result.tile_id is not None and result.confidence >= min_conf:
            # 高置信度：直接保存到对应类别
            tile_id = result.tile_id
            dst_dir = os.path.join(out_dir, tile_id)
            os.makedirs(dst_dir, exist_ok=True)
            fname = f"{os.path.splitext(os.path.basename(image_path))[0]}_{idx:02d}.png"
            cv2.imwrite(os.path.join(dst_dir, fname), roi)
            saved += 1
        else:
            # 低置信度：保存到 unclassified 供人工检查
            fname = f"{os.path.splitext(os.path.basename(image_path))[0]}_{idx:02d}.png"
            cv2.imwrite(os.path.join(unclassified_dir, fname), roi)
            skipped += 1

    logger.info("%s: 手牌区=%dx%d@%d,%d, 保存=%d, 待确认=%d",
                os.path.basename(image_path), w, h, x, y, saved, skipped)
    return {"saved": saved, "skipped": skipped}


def extract_from_video(video_path: str, recognizer: TileRecognizer, out_dir: str, unclassified_dir: str, min_conf: float, fps: int = 1) -> dict:
    """从视频按 fps 抽帧提取样本。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("无法打开视频: %s", video_path)
        return {"saved": 0, "skipped": 0}

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = max(1, int(video_fps / fps))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    saved = 0
    skipped = 0
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            hand_rect = detect_hand_region(frame)
            if hand_rect is not None:
                x, y, w, h = hand_rect
                strip = frame[y:y + h, x:x + w]
                rois = segment_hand_strip(strip, n=13)

                for idx, roi in enumerate(rois):
                    result = recognizer.match_tile(roi)
                    base_name = f"{os.path.splitext(os.path.basename(video_path))[0]}_f{frame_idx:04d}"

                    if result.tile_id is not None and result.confidence >= min_conf:
                        tile_id = result.tile_id
                        dst_dir = os.path.join(out_dir, tile_id)
                        os.makedirs(dst_dir, exist_ok=True)
                        fname = f"{base_name}_{idx:02d}.png"
                        cv2.imwrite(os.path.join(dst_dir, fname), roi)
                        saved += 1
                    else:
                        fname = f"{base_name}_{idx:02d}.png"
                        cv2.imwrite(os.path.join(unclassified_dir, fname), roi)
                        skipped += 1

        frame_idx += 1

    cap.release()
    logger.info("%s: 总帧=%d, 保存=%d, 待确认=%d", os.path.basename(video_path), total_frames, saved, skipped)
    return {"saved": saved, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="从媒体文件提取麻将牌训练样本")
    parser.add_argument("--src", required=True, help="源目录（包含图片/视频）")
    parser.add_argument("--out", default="data/tile_samples", help="输出样本目录")
    parser.add_argument("--template-dir", default="templates", help="模板目录")
    parser.add_argument("--min-conf", type=float, default=DEFAULT_MIN_CONF, help="最低置信度阈值")
    parser.add_argument("--video-fps", type=int, default=1, help="视频抽帧率（每秒几帧）")
    args = parser.parse_args()

    # 初始化识别器
    tile_dir = os.path.join(args.template_dir, "tiles")
    hog_model_path = os.path.join(os.path.dirname(tile_dir), "..", "models", "tile_svm.xml")
    hog_model_path = os.path.normpath(os.path.abspath(hog_model_path))
    recognizer = TileRecognizer(tile_dir, hog_model_path=hog_model_path)

    out_dir = args.out
    unclassified_dir = os.path.join(out_dir, "_unclassified")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(unclassified_dir, exist_ok=True)

    total_saved = 0
    total_skipped = 0

    # 处理图片
    image_exts = ("*.jpg", "*.jpeg", "*.png")
    for ext in image_exts:
        for path in glob.glob(os.path.join(args.src, ext)):
            # 跳过缩略图
            if "_thumb" in path:
                continue
            stats = extract_from_image(path, recognizer, out_dir, unclassified_dir, args.min_conf)
            total_saved += stats["saved"]
            total_skipped += stats["skipped"]

    # 处理视频
    for path in glob.glob(os.path.join(args.src, "*.mp4")):
        stats = extract_from_video(path, recognizer, out_dir, unclassified_dir, args.min_conf, args.video_fps)
        total_saved += stats["saved"]
        total_skipped += stats["skipped"]

    logger.info("=" * 50)
    logger.info("提取完成！")
    logger.info("  高置信度样本: %d", total_saved)
    logger.info("  待人工确认: %d (在 %s)", total_skipped, unclassified_dir)
    logger.info("=" * 50)

    # 统计各类别
    counts = {}
    for tile_id in os.listdir(out_dir):
        tile_dir = os.path.join(out_dir, tile_id)
        if os.path.isdir(tile_dir) and not tile_id.startswith("_"):
            counts[tile_id] = len(glob.glob(os.path.join(tile_dir, "*.png")))

    if counts:
        logger.info("各类别样本数:")
        for tid in sorted(counts):
            logger.info("  %-6s: %d", tid, counts[tid])


if __name__ == "__main__":
    main()
