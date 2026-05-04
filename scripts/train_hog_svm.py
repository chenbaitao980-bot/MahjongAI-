"""训练 HOG+SVM 分类器。

用法：
  python scripts/train_hog_svm.py [--samples data/tile_samples] [--model models/tile_svm.xml]
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

from vision.hog_classifier import TileHOGClassifier

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("train_hog_svm")


def load_samples(samples_dir: str) -> tuple[list[np.ndarray], list[str]]:
    """从 data/tile_samples/{tile_id}/*.png 加载所有样本。"""
    samples: list[np.ndarray] = []
    labels: list[str] = []

    if not os.path.isdir(samples_dir):
        raise FileNotFoundError(f"样本目录不存在：{samples_dir}")

    for tile_id in sorted(os.listdir(samples_dir)):
        tile_dir = os.path.join(samples_dir, tile_id)
        if not os.path.isdir(tile_dir):
            continue
        pngs = glob.glob(os.path.join(tile_dir, "*.png"))
        for p in pngs:
            img = cv2.imread(p)
            if img is None:
                continue
            samples.append(img)
            labels.append(tile_id)

    if not samples:
        raise ValueError(f"未找到任何样本：{samples_dir}")

    logger.info("加载样本：%d 张，来自 %d 个类别", len(samples), len(set(labels)))
    return samples, labels


def main() -> None:
    parser = argparse.ArgumentParser(description="训练 HOG+SVM 麻将牌分类器")
    parser.add_argument("--samples", default="data/tile_samples", help="样本目录")
    parser.add_argument("--model", default="models/tile_svm.xml", help="输出模型路径")
    parser.add_argument("--auto-params", action="store_true", help="自动搜索 SVM 超参数（慢但效果好）")
    parser.add_argument("--C", type=float, default=10.0, help="SVM C 参数")
    parser.add_argument("--gamma", type=float, default=0.001, help="SVM gamma 参数")
    args = parser.parse_args()

    samples, labels = load_samples(args.samples)

    clf = TileHOGClassifier()
    stats = clf.train(samples, labels, auto_params=args.auto_params, C=args.C, gamma=args.gamma)

    clf.save(args.model)

    logger.info("=" * 50)
    logger.info("训练完成！")
    logger.info("  训练集准确率: %.1f%%", stats["train_acc"] * 100)
    logger.info("  样本总数: %d", stats["n_samples"])
    logger.info("  类别数: %d", stats["n_classes"])
    logger.info("  模型保存: %s", args.model)
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
