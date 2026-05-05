"""HOG + SVM 麻将牌识别器。

不依赖 PyTorch，仅用 OpenCV 内置 ML 模块。
准确率目标：98%+（训练样本充足时）。

使用流程：
  1. 用 collect_tile_samples.py 收集标注样本到 data/tile_samples/
  2. 运行 python scripts/train_hog_svm.py 训练并保存模型
  3. 识别时自动加载 models/tile_svm.xml
"""
from __future__ import annotations
import os
import json
import cv2
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger("mahjongai.hog_classifier")

# HOG 参数：(64, 96) = (宽, 高)，针对手牌牌面纵向比例优化
_HOG_WIN = (64, 96)
_HOG_BLOCK = (16, 16)
_HOG_STRIDE = (8, 8)
_HOG_CELL = (8, 8)
_HOG_BINS = 9
# 特征维度 = ((64-16)/8+1) * ((96-16)/8+1) * (16/8)^2 * 9 = 7*11*4*9 = 2772
_HOG_DIM = 2772
MIN_TRUSTED_CLASSES = 34
MIN_TRUSTED_SAMPLES_PER_CLASS = 5


def _make_hog() -> cv2.HOGDescriptor:
    return cv2.HOGDescriptor(_HOG_WIN, _HOG_BLOCK, _HOG_STRIDE, _HOG_CELL, _HOG_BINS)


def extract_hog(roi: np.ndarray, hog: cv2.HOGDescriptor | None = None) -> np.ndarray:
    """从 BGR/灰度 tile ROI 提取 HOG 特征向量（长度 2772）。"""
    if roi is None or roi.size == 0:
        return np.zeros(_HOG_DIM, dtype=np.float32)
    if hog is None:
        hog = _make_hog()
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi.copy()
    # CLAHE 对比度增强：clipLimit=3.0 对低对比度万字牌面效果更好
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    gray = clahe.apply(gray)
    resized = cv2.resize(gray, _HOG_WIN)
    feat = hog.compute(resized)
    return feat.flatten().astype(np.float32)


class TileHOGClassifier:
    """HOG 特征 + SVM 分类器，34 类麻将牌。"""

    def __init__(self, model_path: Optional[str] = None):
        self._hog = _make_hog()
        self._svm: Optional[cv2.ml.SVM] = None
        self._tile_labels: list[str] = []   # 索引 → tile_id
        self._label_to_idx: dict[str, int] = {}
        self._class_counts: dict[str, int] = {}
        self._trusted = False
        self._loaded = False

        if model_path and os.path.exists(model_path):
            self.load(model_path)

    # ------------------------------------------------------------------ #
    #  训练                                                                #
    # ------------------------------------------------------------------ #

    def train(
        self,
        samples: list[np.ndarray],
        labels: list[str],
        auto_params: bool = True,
        C: float = 10.0,
        gamma: float = 0.001,
    ) -> dict:
        """
        训练 SVM 分类器。

        Args:
            samples: 牌面 ROI 列表（BGR 或灰度）
            labels:  对应 tile_id 列表（如 "2m", "5z"）
            auto_params: 是否用交叉验证自动找最优 C/gamma（慢但效果好）
            C, gamma: auto_params=False 时的手动参数
        Returns:
            训练统计 dict
        """
        if not samples or len(samples) != len(labels):
            raise ValueError("samples 和 labels 数量不一致或为空")

        unique = sorted(set(labels))
        self._tile_labels = unique
        self._label_to_idx = {l: i for i, l in enumerate(unique)}
        n_classes = len(unique)
        n_samples = len(samples)

        logger.info("HOG 特征提取：%d 张牌，%d 类别", n_samples, n_classes)
        features = np.array([extract_hog(s, self._hog) for s in samples], dtype=np.float32)
        label_idx = np.array([self._label_to_idx[l] for l in labels], dtype=np.int32)

        td = cv2.ml.TrainData.create(features, cv2.ml.ROW_SAMPLE, label_idx)

        self._svm = cv2.ml.SVM_create()
        self._svm.setType(cv2.ml.SVM_C_SVC)
        self._svm.setKernel(cv2.ml.SVM_RBF)
        self._svm.setTermCriteria(
            (cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS, 2000, 1e-6)
        )

        if auto_params:
            logger.info("自动搜索 SVM 超参数（可能需要 30s-3min）...")
            self._svm.trainAuto(
                td,
                kFold=5,
                Cgrid=cv2.ml.SVM.getDefaultGridPtr(cv2.ml.SVM_C),
                gammaGrid=cv2.ml.SVM.getDefaultGridPtr(cv2.ml.SVM_GAMMA),
            )
        else:
            self._svm.setC(C)
            self._svm.setGamma(gamma)
            self._svm.train(td)

        # 训练集准确率
        _, train_pred = self._svm.predict(features)
        train_pred_flat = train_pred.flatten().astype(int)
        acc = float(np.mean(train_pred_flat == label_idx))
        logger.info("训练集准确率：%.1f%%  (%d/%d)", acc * 100, int(acc * n_samples), n_samples)
        self._loaded = True

        # 返回每类样本数
        class_counts = {self._tile_labels[i]: int(np.sum(label_idx == i)) for i in range(n_classes)}
        self._class_counts = class_counts
        min_count = min(class_counts.values()) if class_counts else 0
        self._trusted = n_classes >= MIN_TRUSTED_CLASSES and min_count >= MIN_TRUSTED_SAMPLES_PER_CLASS
        return {"train_acc": acc, "n_samples": n_samples, "n_classes": n_classes, "class_counts": class_counts}

    # ------------------------------------------------------------------ #
    #  推理                                                                #
    # ------------------------------------------------------------------ #

    def predict(self, roi: np.ndarray) -> tuple[Optional[str], float]:
        """
        预测单张牌。
        Returns:
            (tile_id, confidence)  confidence 为 [0, 1] 估计值
        """
        if not self._loaded or self._svm is None:
            return None, 0.0
        feat = extract_hog(roi, self._hog).reshape(1, -1)
        _, result = self._svm.predict(feat)
        idx = int(result[0, 0])
        if idx < 0 or idx >= len(self._tile_labels):
            return None, 0.0
        tile_id = self._tile_labels[idx]

        # 置信度：用 decision function 距离（越大越确定）
        _, raw = self._svm.predict(feat, flags=cv2.ml.StatModel_RAW_OUTPUT)
        dist = float(abs(raw[0, 0]))
        # sigmoid 压缩到 [0,1]，经验系数 k=3 使距离 1.0 → conf≈0.95
        conf = float(1.0 / (1.0 + np.exp(-3.0 * dist + 1.5)))
        conf = min(0.99, conf)
        return tile_id, conf

    def predict_batch(self, rois: list[np.ndarray]) -> list[tuple[Optional[str], float]]:
        """批量预测（性能优化版）。"""
        if not self._loaded or self._svm is None or not rois:
            return [(None, 0.0)] * len(rois)
        features = np.array([extract_hog(r, self._hog) for r in rois], dtype=np.float32)
        _, results = self._svm.predict(features)
        _, raws = self._svm.predict(features, flags=cv2.ml.StatModel_RAW_OUTPUT)
        out = []
        for i in range(len(rois)):
            idx = int(results[i, 0])
            if idx < 0 or idx >= len(self._tile_labels):
                out.append((None, 0.0))
                continue
            tile_id = self._tile_labels[idx]
            dist = float(abs(raws[i, 0]))
            conf = float(1.0 / (1.0 + np.exp(-3.0 * dist + 1.5)))
            out.append((tile_id, min(0.99, conf)))
        return out

    # ------------------------------------------------------------------ #
    #  保存 / 加载                                                          #
    # ------------------------------------------------------------------ #

    def save(self, model_path: str) -> None:
        """保存 SVM 模型和标签映射。"""
        if self._svm is None:
            raise RuntimeError("模型尚未训练")
        os.makedirs(os.path.dirname(model_path) or ".", exist_ok=True)
        self._svm.save(model_path)
        # 标签文件保存在同目录
        label_path = model_path.replace(".xml", "_labels.txt")
        meta_path = model_path.replace(".xml", "_meta.json")
        with open(label_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self._tile_labels))
        meta = {
            "class_counts": self._class_counts,
            "n_classes": len(self._tile_labels),
            "min_samples_per_class": min(self._class_counts.values()) if self._class_counts else 0,
            "trusted": self._trusted,
            "trusted_rule": {
                "min_classes": MIN_TRUSTED_CLASSES,
                "min_samples_per_class": MIN_TRUSTED_SAMPLES_PER_CLASS,
            },
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        logger.info("模型已保存：%s  标签：%s", model_path, label_path)

    def load(self, model_path: str) -> bool:
        """加载 SVM 模型。"""
        label_path = model_path.replace(".xml", "_labels.txt")
        meta_path = model_path.replace(".xml", "_meta.json")
        if not os.path.exists(model_path) or not os.path.exists(label_path):
            return False
        try:
            self._svm = cv2.ml.SVM.load(model_path)
            with open(label_path, "r", encoding="utf-8") as f:
                self._tile_labels = [l.strip() for l in f if l.strip()]
            self._label_to_idx = {l: i for i, l in enumerate(self._tile_labels)}
            self._class_counts = {}
            self._trusted = False
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._class_counts = {
                    str(k): int(v) for k, v in (meta.get("class_counts") or {}).items()
                }
                min_count = min(self._class_counts.values()) if self._class_counts else 0
                self._trusted = (
                    bool(meta.get("trusted"))
                    and len(self._tile_labels) >= MIN_TRUSTED_CLASSES
                    and min_count >= MIN_TRUSTED_SAMPLES_PER_CLASS
                )
            else:
                logger.warning("HOG 分类器缺少训练质量元数据，将只加载但不作为可信主判：%s", meta_path)
            self._loaded = True
            logger.info(
                "HOG 分类器加载：%d 类 trusted=%s model=%s",
                len(self._tile_labels),
                self._trusted,
                model_path,
            )
            return True
        except Exception as e:
            logger.warning("HOG 分类器加载失败：%s", e)
            return False

    @property
    def is_ready(self) -> bool:
        return self._loaded and self._svm is not None and len(self._tile_labels) > 0

    @property
    def n_classes(self) -> int:
        return len(self._tile_labels)

    @property
    def is_trusted(self) -> bool:
        return self.is_ready and self._trusted

    @property
    def class_counts(self) -> dict[str, int]:
        return dict(self._class_counts)
