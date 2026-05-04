from __future__ import annotations
import os
import cv2
import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional

from game.state import ALL_TILE_IDS, BUTTON_IDS

logger = logging.getLogger("mahjongai.recognizer")


def _read_image(path: str, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """Read image paths containing non-ASCII characters on Windows."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, flags)
    except Exception:
        return cv2.imread(path, flags)


@dataclass
class MatchResult:
    tile_id: Optional[str]
    confidence: float
    location: tuple[int, int] = (0, 0)
    method: str = "structural"

    def __bool__(self) -> bool:
        return self.tile_id is not None


@dataclass
class StripMatch:
    """滑动窗口扫描结果"""
    tile_id: Optional[str]
    confidence: float
    x_center: int
    method: str = "scan_canny"

    def __bool__(self) -> bool:
        return self.tile_id is not None


class TileRecognizer:
    TILE_SIZE = (48, 64)
    # 纯形状匹配：更低的阈值，因为形状信息比颜色更稀疏
    STRUCT_THRESHOLD = 0.25
    HIST_THRESHOLD = 0.55
    NCC_THRESHOLD = 0.45
    CANNY_THRESHOLD = 0.25
    INK_THRESHOLD = 0.35
    ORB_MIN_MATCHES = 5
    LOWE_RATIO = 0.75

    def __init__(self, template_dir: str, threshold: float = 0.60, use_orb: bool = True, hog_model_path: str | None = None):
        self._threshold = threshold
        self._use_orb = use_orb
        self._templates_bgr: dict[str, np.ndarray] = {}
        self._templates_struct: dict[str, np.ndarray] = {}
        self._templates_gray: dict[str, np.ndarray] = {}
        self._templates_hist: dict[str, np.ndarray] = {}
        self._orb_descriptors: dict[str, tuple] = {}
        self._templates_canny: dict[str, np.ndarray] = {}
        self._templates_ink: dict[str, np.ndarray] = {}
        self._templates_upper_ink: dict[str, np.ndarray] = {}
        self._training_exemplars: list[dict] = []
        self._exemplar_tile_ids: list[str] = []
        self._exemplar_sources: list[str] = []
        self._exemplar_gray_matrix: np.ndarray | None = None
        self._exemplar_ink_matrix: np.ndarray | None = None
        self._exemplar_upper_matrix: np.ndarray | None = None
        self._exemplar_ink_counts: np.ndarray | None = None
        self._exemplar_upper_counts: np.ndarray | None = None
        self._orb = None
        self._bfm = None

        # HOG+SVM 分类器（仅完整 34 类模型可作为主判）
        self._hog_clf = None
        if hog_model_path and os.path.exists(hog_model_path):
            from vision.hog_classifier import TileHOGClassifier
            self._hog_clf = TileHOGClassifier(hog_model_path)
            if self._hog_clf.is_ready:
                trusted = bool(getattr(self._hog_clf, "is_trusted", False))
                logger.info("HOG 分类器已加载：%d 类 trusted=%s", self._hog_clf.n_classes, trusted)
                if self._hog_clf.n_classes < len(ALL_TILE_IDS) or not trusted:
                    logger.warning(
                        "HOG 分类器未达到可信主判条件：classes=%d/%d trusted=%s，仅保留加载但不会主导识别",
                        self._hog_clf.n_classes,
                        len(ALL_TILE_IDS),
                        trusted,
                    )
            else:
                self._hog_clf = None

        if os.path.isdir(template_dir):
            self.load_templates(template_dir)
            root_dir = os.path.abspath(os.path.join(template_dir, "..", ".."))
            self.load_training_samples(os.path.join(root_dir, "data", "tile_samples_cleaned"))

    def load_templates(self, template_dir: str) -> int:
        loaded = 0
        for fname in os.listdir(template_dir):
            if not fname.endswith(".png"):
                continue
            tile_id = fname[:-4]
            if tile_id not in ALL_TILE_IDS:
                continue
            path = os.path.join(template_dir, fname)
            img_bgr = _read_image(path, cv2.IMREAD_COLOR)
            if img_bgr is not None:
                self._templates_bgr[tile_id] = img_bgr
                self._templates_struct[tile_id] = self._extract_structure(img_bgr)
                self._templates_canny[tile_id] = self._extract_canny(img_bgr)
                self._templates_gray[tile_id] = self._preprocess_gray(img_bgr)
                self._templates_hist[tile_id] = self._compute_hsv_hist(img_bgr)
                self._templates_ink[tile_id] = self._extract_ink_mask(img_bgr)
                self._templates_upper_ink[tile_id] = self._extract_upper_ink_mask(img_bgr)
                loaded += 1
                continue
            img_gray = _read_image(path, cv2.IMREAD_GRAYSCALE)
            if img_gray is not None:
                self._templates_gray[tile_id] = self._prepare_gray_template(img_gray)
                self._templates_struct[tile_id] = self._extract_structure_from_gray(img_gray)
                self._templates_canny[tile_id] = self._extract_canny(img_gray)
                self._templates_ink[tile_id] = self._extract_ink_mask(img_gray)
                self._templates_upper_ink[tile_id] = self._extract_upper_ink_mask(img_gray)
                loaded += 1

        logger.info("模板加载完成：%d 种", loaded)
        if self._use_orb and self._templates_struct:
            self._precompute_orb()
        return loaded

    def load_training_samples(self, samples_dir: str, max_per_class: int = 4) -> int:
        """Load manually corrected ROI samples as immediate nearest-neighbor memory."""
        self._training_exemplars.clear()
        if not os.path.isdir(samples_dir):
            return 0
        loaded = 0
        for tile_id in sorted(os.listdir(samples_dir)):
            if tile_id not in ALL_TILE_IDS:
                continue
            tile_dir = os.path.join(samples_dir, tile_id)
            if not os.path.isdir(tile_dir):
                continue
            files = [
                os.path.join(tile_dir, name)
                for name in os.listdir(tile_dir)
                if name.lower().endswith(".png")
            ]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for path in files[:max_per_class]:
                img = _read_image(path, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                self.add_training_sample(img, tile_id, source=path, rebuild_index=False)
                loaded += 1
        self._rebuild_training_index()
        logger.info("人工纠正样本加载完成：%d 张", loaded)
        return loaded

    def add_training_sample(self, roi: np.ndarray, tile_id: str, source: str = "", rebuild_index: bool = True) -> None:
        """Add a corrected sample to the live recognizer without waiting for model training."""
        if tile_id not in ALL_TILE_IDS or roi is None or roi.size == 0:
            return
        self._training_exemplars.append({
            "tile_id": tile_id,
            "gray": self._preprocess_gray(roi),
            "ink": self._extract_ink_mask(roi),
            "upper": self._extract_upper_ink_mask(roi),
            "source": source,
        })
        if rebuild_index:
            self._rebuild_training_index()

    def _rebuild_training_index(self) -> None:
        self._exemplar_tile_ids = []
        self._exemplar_sources = []
        gray_rows = []
        ink_rows = []
        upper_rows = []
        ink_counts = []
        upper_counts = []
        for item in self._training_exemplars:
            gray = item["gray"].astype(np.float32).reshape(-1)
            gray = gray - float(gray.mean())
            norm = float(np.linalg.norm(gray))
            if norm <= 1e-6:
                continue
            gray_rows.append(gray / norm)
            ink = (item["ink"].reshape(-1) > 0).astype(np.float32)
            upper = (item["upper"].reshape(-1) > 0).astype(np.float32)
            ink_rows.append(ink)
            upper_rows.append(upper)
            ink_counts.append(float(ink.sum()))
            upper_counts.append(float(upper.sum()))
            self._exemplar_tile_ids.append(item["tile_id"])
            self._exemplar_sources.append(item.get("source", ""))
        self._exemplar_gray_matrix = np.vstack(gray_rows).astype(np.float32) if gray_rows else None
        self._exemplar_ink_matrix = np.vstack(ink_rows).astype(np.float32) if ink_rows else None
        self._exemplar_upper_matrix = np.vstack(upper_rows).astype(np.float32) if upper_rows else None
        self._exemplar_ink_counts = np.array(ink_counts, dtype=np.float32) if ink_counts else None
        self._exemplar_upper_counts = np.array(upper_counts, dtype=np.float32) if upper_counts else None

    def _precompute_orb(self) -> None:
        self._init_orb()
        self._orb_descriptors.clear()
        for tile_id, tmpl in self._templates_struct.items():
            kp, des = self._orb.detectAndCompute(tmpl, None)
            if des is not None:
                self._orb_descriptors[tile_id] = (kp, des)
            else:
                self._orb_descriptors[tile_id] = ([], None)

    def _init_orb(self) -> None:
        if self._orb is not None:
            return
        self._orb = cv2.ORB_create(nfeatures=300, scaleFactor=1.2, nlevels=8)
        self._bfm = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    def match_sequence(self, rois: list[np.ndarray]) -> list[MatchResult]:
        """批量匹配一组 ROI（纯形状匹配）。"""
        results: list[MatchResult] = []
        for roi in rois:
            if not self.is_probably_tile_roi(roi):
                results.append(MatchResult(tile_id=None, confidence=0.0, method="empty_slot"))
                continue
            results.append(self.match_tile(roi))
        return results

    @staticmethod
    def is_probably_tile_roi(roi: np.ndarray) -> bool:
        """Cheap guard for discard-grid slots before running expensive tile matching."""
        if roi is None or roi.size == 0:
            return False
        h, w = roi.shape[:2]
        if h < 12 or w < 8:
            return False
        bgr = roi if len(roi.shape) == 3 else cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        white = ((hsv[:, :, 2] > 135) & (hsv[:, :, 1] < 130)).astype(np.uint8)
        if float(white.mean()) < 0.10:
            return False
        n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(white * 255)
        min_area = max(10, int(h * w * 0.06))
        for label in range(1, n_labels):
            _x, _y, bw, bh, area = [int(v) for v in stats[label]]
            if area >= min_area and bw >= max(4, int(w * 0.20)) and bh >= max(6, int(h * 0.25)):
                return True
        return False

    def match_tile(self, roi: np.ndarray, debug_info: dict | None = None) -> MatchResult:
        """识别单张牌。

        HOG 模型必须覆盖 34 类牌种才可参与主判；否则会把未知牌硬压到
        少数已训练类别，造成整手牌大量变成同一牌种。
        """
        if roi is None or roi.size == 0:
            return MatchResult(tile_id=None, confidence=0.0)

        hog_result: MatchResult | None = None
        hog_complete = (
            self._hog_clf is not None
            and self._hog_clf.is_ready
            and self._hog_clf.n_classes >= len(ALL_TILE_IDS)
            and bool(getattr(self._hog_clf, "is_trusted", False))
        )
        if hog_complete:
            tile_id, conf = self._hog_clf.predict(roi)
            if tile_id is not None:
                if debug_info is not None:
                    debug_info["hog_tile"] = tile_id
                    debug_info["hog_conf"] = round(conf, 4)
                hog_result = MatchResult(tile_id=tile_id, confidence=conf, method="hog_svm")
        elif debug_info is not None and self._hog_clf is not None and self._hog_clf.is_ready:
            trusted = bool(getattr(self._hog_clf, "is_trusted", False))
            debug_info["hog_skipped"] = f"untrusted_model:{self._hog_clf.n_classes}/{len(ALL_TILE_IDS)} trusted={trusted}"

        # 回退：传统多策略模板匹配
        if not self._templates_struct and not self._templates_canny:
            return hog_result or MatchResult(tile_id=None, confidence=0.0)

        roi_struct = self._extract_structure(roi)
        roi_canny = self._extract_canny(roi)
        roi_gray = self._preprocess_gray(roi)
        roi_ink = self._extract_ink_mask(roi)
        roi_upper_ink = self._extract_upper_ink_mask(roi)

        exemplar_result = self._match_training_exemplars(roi_gray, roi_ink, roi_upper_ink, debug_info)

        struct_result = self._match_structural(roi_struct, debug_info)
        canny_result = self._match_canny(roi_canny, debug_info)
        gray_result = self._match_ncc_gray(roi_gray, debug_info)
        ink_result = self._match_ink(roi_ink, debug_info)
        upper_result = self._match_upper_ink(roi_upper_ink, debug_info)

        best = self._fuse_visual_results(
            struct_result, canny_result, gray_result, ink_result, upper_result, debug_info
        )
        if exemplar_result.tile_id is not None:
            return exemplar_result
        sample_best_id = None
        if debug_info is not None:
            class_top = debug_info.get("corrected_sample_class_top5") or []
            if class_top:
                sample_best_id = class_top[0].get("tile_id")
        if (
            sample_best_id is not None
            and best.tile_id == sample_best_id
            and best.tile_id is not None
            and exemplar_result.confidence >= 0.68
        ):
            return MatchResult(
                tile_id=best.tile_id,
                confidence=max(best.confidence, min(0.96, exemplar_result.confidence)),
                method="sample_visual_agree",
            )

        if hog_result is not None:
            if best.tile_id == hog_result.tile_id and best.tile_id is not None:
                return MatchResult(
                    tile_id=best.tile_id,
                    confidence=max(best.confidence, hog_result.confidence),
                    method="hog_visual_agree",
                )
            if hog_result.confidence >= 0.97 and (best.tile_id is None or best.confidence < 0.88):
                return hog_result
            if debug_info is not None:
                debug_info["hog_visual_conflict"] = {
                    "hog": hog_result.tile_id,
                    "hog_conf": round(hog_result.confidence, 4),
                    "visual": best.tile_id,
                    "visual_conf": round(best.confidence, 4),
                }
        if best.tile_id is not None and best.confidence >= self._threshold:
            return best
        return best if best.tile_id is not None else (hog_result or best)

    def _match_training_exemplars(
        self,
        roi_gray: np.ndarray,
        roi_ink: np.ndarray,
        roi_upper_ink: np.ndarray,
        debug_info: dict | None,
    ) -> MatchResult:
        if self._exemplar_gray_matrix is None or not self._exemplar_tile_ids:
            return MatchResult(tile_id=None, confidence=0.0, method="corrected_sample")

        q_gray = roi_gray.astype(np.float32).reshape(-1)
        q_gray = q_gray - float(q_gray.mean())
        q_norm = float(np.linalg.norm(q_gray))
        if q_norm <= 1e-6:
            return MatchResult(tile_id=None, confidence=0.0, method="corrected_sample")
        q_gray = q_gray / q_norm

        gray_scores = self._exemplar_gray_matrix @ q_gray
        q_ink = (roi_ink.reshape(-1) > 0).astype(np.float32)
        q_upper = (roi_upper_ink.reshape(-1) > 0).astype(np.float32)
        q_ink_count = float(q_ink.sum())
        q_upper_count = float(q_upper.sum())
        if self._exemplar_ink_matrix is not None and self._exemplar_ink_counts is not None:
            ink_inter = self._exemplar_ink_matrix @ q_ink
            ink_scores = (2.0 * ink_inter) / np.maximum(self._exemplar_ink_counts + q_ink_count, 1.0)
        else:
            ink_scores = np.zeros_like(gray_scores)
        if self._exemplar_upper_matrix is not None and self._exemplar_upper_counts is not None:
            upper_inter = self._exemplar_upper_matrix @ q_upper
            upper_scores = (2.0 * upper_inter) / np.maximum(self._exemplar_upper_counts + q_upper_count, 1.0)
        else:
            upper_scores = np.zeros_like(gray_scores)
        final_scores = 0.58 * gray_scores + 0.17 * ink_scores + 0.25 * upper_scores

        order = np.argsort(final_scores)[::-1]
        scores: list[tuple[str, float, str]] = [
            (
                self._exemplar_tile_ids[int(i)],
                float(final_scores[int(i)]),
                self._exemplar_sources[int(i)],
            )
            for i in order[: min(20, len(order))]
        ]

        if not scores:
            return MatchResult(tile_id=None, confidence=0.0, method="corrected_sample")

        per_tile: dict[str, tuple[float, str]] = {}
        for i in order:
            tid = self._exemplar_tile_ids[int(i)]
            score = float(final_scores[int(i)])
            src = self._exemplar_sources[int(i)]
            if tid not in per_tile or score > per_tile[tid][0]:
                per_tile[tid] = (score, src)
        ranked_tiles = sorted(per_tile.items(), key=lambda kv: kv[1][0], reverse=True)
        best_id, (best_score, best_source) = ranked_tiles[0]
        second_score = ranked_tiles[1][1][0] if len(ranked_tiles) > 1 else 0.0
        margin = best_score - second_score
        if debug_info is not None:
            debug_info["corrected_sample_top5"] = [
                {"tile_id": tid, "confidence": round(score, 4), "source": src}
                for tid, score, src in scores[:5]
            ]
            debug_info["corrected_sample_class_top5"] = [
                {"tile_id": tid, "confidence": round(score, 4), "source": src}
                for tid, (score, src) in ranked_tiles[:5]
            ]
            debug_info["corrected_sample_margin"] = round(margin, 4)

        if best_score >= 0.74 and margin >= 0.015:
            return MatchResult(tile_id=best_id, confidence=min(0.98, best_score), method="corrected_sample")
        return MatchResult(tile_id=None, confidence=best_score, method="corrected_sample")

    @staticmethod
    def _ncc_score(a: np.ndarray, b: np.ndarray) -> float:
        result = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return float(max_val)

    @staticmethod
    def _dice_score(a: np.ndarray, b: np.ndarray) -> float:
        denom = int(a.sum()) + int(b.sum())
        if denom <= 0:
            return 0.0
        return float(2.0 * int(np.logical_and(a, b).sum()) / denom)

    def _fuse_visual_results(
        self,
        struct_r: MatchResult,
        canny_r: MatchResult,
        gray_r: MatchResult,
        ink_r: MatchResult,
        upper_r: MatchResult,
        debug_info: dict | None,
    ) -> MatchResult:
        """Fuse same-size tile-template signals without depending on color histograms.

        The old recognizer often returned None because every single channel was
        below a hard threshold, even when two channels agreed on the same tile.
        For this app the better failure mode is a low-confidence guess, because
        downstream logs and screenshots are used for calibration.
        """
        all_results = [struct_r, canny_r, gray_r, ink_r, upper_r]
        usable = [r for r in all_results if r.tile_id is not None]

        votes: dict[str, list[float]] = {}
        for r in usable:
            weight = 1.35 if r.method == "upper_ink" else 1.0
            votes.setdefault(r.tile_id, []).append(r.confidence * weight)

        if votes:
            def rank(item: tuple[str, list[float]]) -> tuple[int, float, float]:
                tid, vals = item
                return (len(vals), max(vals), sum(vals) / len(vals))

            best_id, vals = max(votes.items(), key=rank)
            conf = max(vals)
            if len(vals) >= 2:
                conf = min(1.0, conf * (1.10 + 0.05 * (len(vals) - 2)))
            method = "visual_fused" if len(vals) >= 2 else next(
                (r.method for r in usable if r.tile_id == best_id), usable[0].method
            )
            conf = self._calibrate_visual_confidence(best_id, conf, debug_info)
            if debug_info is not None:
                debug_info["visual_votes"] = {k: [round(v, 4) for v in vs] for k, vs in votes.items()}
                debug_info["visual_winner"] = best_id
            return MatchResult(tile_id=best_id, confidence=conf, method=method)

        # If thresholds rejected everything, still surface the best raw score.
        best = max(all_results, key=lambda r: r.confidence)
        if best.tile_id is not None and best.confidence >= 0.22:
            return MatchResult(tile_id=best.tile_id, confidence=best.confidence, method=best.method)
        raw_guess = self._best_raw_debug_candidate(debug_info)
        if raw_guess is not None:
            return raw_guess
        return best

    def _calibrate_visual_confidence(
        self,
        tile_id: str,
        confidence: float,
        debug_info: dict | None,
    ) -> float:
        """Keep template confidence honest when top candidates are close.

        Template matching scores are similarities, not probabilities. In
        particular, 万字牌 share the same lower glyph and often have several
        near-ties. The old fusion inflated those near-ties to 0.98/1.00, which
        made wrong results look certain.
        """
        if not debug_info:
            return min(float(confidence), 0.88)

        weights = {
            "struct_top5": 1.00,
            "canny_top5": 0.90,
            "ncc_top5": 1.10,
            "ink_top5": 1.00,
            "upper_ink_top5": 1.20,
        }
        scores: dict[str, float] = {}
        for key, weight in weights.items():
            for rank, item in enumerate(debug_info.get(key, [])[:5]):
                tid = item.get("tile_id")
                raw = item.get("confidence")
                if not tid or raw is None:
                    continue
                scores[tid] = scores.get(tid, 0.0) + max(0.0, float(raw)) * weight / (rank + 1)

        if len(scores) < 2:
            return min(float(confidence), 0.88)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        agg_best, agg_score = ranked[0]
        second_score = ranked[1][1]
        margin = agg_score - second_score
        if debug_info is not None:
            debug_info["visual_margin"] = round(margin, 4)
            debug_info["visual_aggregate_top5"] = [
                {"tile_id": tid, "score": round(score, 4)}
                for tid, score in ranked[:5]
            ]

        cap = 0.95
        if agg_best != tile_id:
            cap = 0.60
        elif margin < 0.04:
            cap = 0.58
        elif margin < 0.08:
            cap = 0.70
        elif margin < 0.15:
            cap = 0.82
        return min(float(confidence), cap)

    def _best_raw_debug_candidate(self, debug_info: dict | None) -> MatchResult | None:
        """Return a low-confidence guess from raw matcher score lists.

        Individual matchers clear tile_id when below their hard threshold. For
        data collection, a marked low-confidence guess is more useful than ???.
        """
        if not debug_info:
            return None
        weighted: dict[str, float] = {}
        weights = {
            "struct_top5": 1.00,
            "canny_top5": 0.90,
            "ncc_top5": 0.85,
            "ink_top5": 1.10,
            "upper_ink_top5": 1.45,
        }
        for key, weight in weights.items():
            for rank, item in enumerate(debug_info.get(key, [])[:5]):
                tile_id = item.get("tile_id")
                conf = item.get("confidence")
                if not tile_id or conf is None:
                    continue
                weighted[tile_id] = weighted.get(tile_id, 0.0) + max(0.0, float(conf)) * weight / (rank + 1)
        if not weighted:
            return None
        tile_id, score = max(weighted.items(), key=lambda kv: kv[1])
        if score < 0.08:
            return None
        if debug_info is not None:
            debug_info["low_conf_guess"] = {"tile_id": tile_id, "score": round(score, 4)}
        return MatchResult(tile_id=tile_id, confidence=min(0.35, score), method="low_conf_guess")

    def scan_hand_strip(
        self,
        strip: np.ndarray,
        est_tile_count: int = 13,
        debug_info: dict | None = None,
    ) -> list[StripMatch]:
        """滑动窗口扫描：等分条带为 est_tile_count 个窗口，每窗口做 match_tile。

        核心发现：直接在缩放后的条带上做 matchTemplate 效果极差，
        因为缩放比例不匹配导致模板与条带中牌的宽高比不同。
        正确做法：逐窗口裁剪 → resize 到 TILE_SIZE → 多策略匹配。

        Args:
            strip: 手牌条带图像（BGR）
            est_tile_count: 预估手牌数
            debug_info: 可选调试字典

        Returns:
            按 x 位置从左到右排序的 StripMatch 列表
        """
        if strip is None or strip.size == 0:
            return []
        # HOG 模式下不需要模板
        has_fallback = self._templates_struct or self._templates_gray
        if not has_fallback and (self._hog_clf is None or not self._hog_clf.is_ready):
            return []

        h, w = strip.shape[:2]
        tile_w_est = w // max(est_tile_count, 1)

        # 等间距检测：在每张牌的中心位置采样（比密集滑动更高效）
        # 同时也在偏移位置采样（容忍对齐偏差）
        candidates: list[tuple[int, str, float]] = []
        max_tiles = est_tile_count + 2

        for i in range(est_tile_count + 2):
            # 主窗口：以预估中心为基准
            cx = int((i + 0.5) * tile_w_est)
            x_start = cx - tile_w_est // 2
            x_end = x_start + tile_w_est
            if x_start < 0 or x_end > w:
                continue
            roi = strip[:, x_start:x_end]
            result = self.match_tile(roi)
            if result.tile_id is not None:
                candidates.append((cx, result.tile_id, result.confidence))

            # 微调窗口：左移/右移 1/4 牌宽（容忍对齐偏差）
            for offset_frac in [-0.25, 0.25]:
                offset = int(offset_frac * tile_w_est)
                cx2 = cx + offset
                x_start2 = cx2 - tile_w_est // 2
                x_end2 = x_start2 + tile_w_est
                if x_start2 < 0 or x_end2 > w:
                    continue
                roi2 = strip[:, x_start2:x_end2]
                result2 = self.match_tile(roi2)
                if result2.tile_id is not None:
                    candidates.append((cx2, result2.tile_id, result2.confidence))

        # NMS：同一位置附近只保留置信度最高的
        candidates.sort(key=lambda c: -c[2])  # 按置信度降序
        kept: list[StripMatch] = []
        used: set[int] = set()
        nms_radius = max(int(tile_w_est * 0.55), 5)

        for x_center, tid, conf in candidates:
            if any(abs(x_center - u) < nms_radius for u in used):
                continue
            used.add(x_center)
            kept.append(StripMatch(
                tile_id=tid, confidence=conf, x_center=x_center, method="scan_ncc"
            ))
            if len(kept) >= max_tiles:
                break

        # 按 x_center 排序
        kept.sort(key=lambda m: m.x_center)

        if debug_info is not None:
            debug_info["scan_n_candidates"] = len(candidates)
            debug_info["scan_n_kept"] = len(kept)
            debug_info["scan_tile_w_est"] = tile_w_est
            debug_info["scan_strip_size"] = (w, h)

        logger.info(
            "scan_hand_strip: %d candidates → %d kept (strip=%dx%d, tile_w=%d)",
            len(candidates), len(kept), w, h, tile_w_est,
        )
        return kept

    def _match_structural(self, roi_struct: np.ndarray, debug_info: dict | None) -> MatchResult:
        """结构匹配：同时尝试正反两种极性的二值图，解决暗/亮界面反转问题。"""
        if not self._templates_struct:
            return MatchResult(tile_id=None, confidence=0.0, method="structural")

        # 预计算反转二值图（用于暗色界面场景）
        roi_inverted = cv2.bitwise_not(roi_struct)

        best_id = None
        best_conf = -1.0
        all_scores: list[tuple[str, float]] = []

        for tile_id, tmpl in self._templates_struct.items():
            if tmpl.shape != roi_struct.shape:
                continue
            # 尝试正极（亮色界面）
            result = cv2.matchTemplate(roi_struct, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            # 尝试反极（暗色界面），取较高值
            result_inv = cv2.matchTemplate(roi_inverted, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val_inv, _, _ = cv2.minMaxLoc(result_inv)

            score = max(max_val, max_val_inv)
            all_scores.append((tile_id, score))
            if score > best_conf:
                best_conf = score
                best_id = tile_id

        if best_conf < self.STRUCT_THRESHOLD:
            best_id = None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["struct_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]
            debug_info["struct_best"] = best_id
            debug_info["struct_conf"] = round(best_conf, 4)

        return MatchResult(tile_id=best_id, confidence=best_conf, method="structural")

    def _match_histogram(self, roi_hist: np.ndarray, debug_info: dict | None) -> MatchResult:
        if not self._templates_hist:
            return MatchResult(tile_id=None, confidence=0.0, method="histogram")

        best_id = None
        best_conf = 0.0
        all_scores: list[tuple[str, float]] = []

        for tile_id, tmpl_hist in self._templates_hist.items():
            score = cv2.compareHist(roi_hist, tmpl_hist, cv2.HISTCMP_CORREL)
            all_scores.append((tile_id, score))
            if score > best_conf:
                best_conf = score
                best_id = tile_id

        if best_conf < self.HIST_THRESHOLD:
            best_id = None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["hist_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_conf, method="histogram")

    def _match_ncc_gray(self, roi_gray: np.ndarray, debug_info: dict | None) -> MatchResult:
        if not self._templates_gray:
            return MatchResult(tile_id=None, confidence=0.0, method="ncc_gray")

        best_id = None
        best_conf = -1.0
        all_scores: list[tuple[str, float]] = []

        for tile_id, tmpl in self._templates_gray.items():
            if tmpl.shape != roi_gray.shape:
                continue
            result = cv2.matchTemplate(roi_gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            all_scores.append((tile_id, max_val))
            if max_val > best_conf:
                best_conf = max_val
                best_id = tile_id

        if best_conf < self.NCC_THRESHOLD:
            best_id = None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["ncc_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_conf, method="ncc_gray")

    def _match_orb_method(self, roi_struct: np.ndarray, debug_info: dict | None) -> MatchResult | None:
        self._init_orb()
        kp_query, des_query = self._orb.detectAndCompute(roi_struct, None)
        if des_query is None or len(kp_query) < self.ORB_MIN_MATCHES:
            return None

        best_id = None
        best_score = 0.0
        all_scores: list[tuple[str, float, int]] = []

        for tile_id, (kp_tmpl, des_tmpl) in self._orb_descriptors.items():
            if des_tmpl is None or len(kp_tmpl) == 0:
                continue
            matches = self._bfm.knnMatch(des_query, des_tmpl, k=2)
            good = []
            for m_pair in matches:
                if len(m_pair) == 2:
                    m, n = m_pair
                    if m.distance < self.LOWE_RATIO * n.distance:
                        good.append(m)
            if len(good) < self.ORB_MIN_MATCHES:
                continue
            score = len(good) / max(len(kp_tmpl), 1)
            all_scores.append((tile_id, score, len(good)))
            if score > best_score:
                best_score = score
                best_id = tile_id

        if best_score < 0.05:
            return None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["orb_top5"] = [{"tile_id": t, "score": round(s, 4), "matches": m} for t, s, m in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_score, method="orb")

    def _match_canny(self, roi_canny: np.ndarray, debug_info: dict | None) -> MatchResult:
        if not self._templates_canny:
            return MatchResult(tile_id=None, confidence=0.0, method="canny")
        if roi_canny is None or roi_canny.size == 0:
            return MatchResult(tile_id=None, confidence=0.0, method="canny")

        best_id = None
        best_conf = -1.0
        all_scores: list[tuple[str, float]] = []

        for tile_id, tmpl in self._templates_canny.items():
            if tmpl.shape != roi_canny.shape:
                continue
            result = cv2.matchTemplate(roi_canny, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            all_scores.append((tile_id, max_val))
            if max_val > best_conf:
                best_conf = max_val
                best_id = tile_id

        if best_conf < self.CANNY_THRESHOLD:
            best_id = None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["canny_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_conf, method="canny")

    def _match_ink(self, roi_ink: np.ndarray, debug_info: dict | None) -> MatchResult:
        if not self._templates_ink:
            return MatchResult(tile_id=None, confidence=0.0, method="ink")

        best_id = None
        best_conf = -1.0
        all_scores: list[tuple[str, float]] = []

        q = roi_ink > 0
        q_count = int(q.sum())
        for tile_id, tmpl in self._templates_ink.items():
            if tmpl.shape != roi_ink.shape:
                continue
            result = cv2.matchTemplate(roi_ink, tmpl, cv2.TM_CCOEFF_NORMED)
            _, ncc, _, _ = cv2.minMaxLoc(result)
            t = tmpl > 0
            denom = q_count + int(t.sum())
            dice = (2.0 * int(np.logical_and(q, t).sum()) / denom) if denom else 0.0
            score = 0.65 * float(ncc) + 0.35 * dice
            all_scores.append((tile_id, score))
            if score > best_conf:
                best_conf = score
                best_id = tile_id

        if best_conf < self.INK_THRESHOLD:
            best_id = None

        if debug_info is not None:
            all_scores.sort(key=lambda x: x[1], reverse=True)
            debug_info["ink_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_conf, method="ink")

    def _match_upper_ink(self, roi_upper_ink: np.ndarray, debug_info: dict | None) -> MatchResult:
        if not self._templates_upper_ink:
            return MatchResult(tile_id=None, confidence=0.0, method="upper_ink")

        best_id = None
        best_conf = -1.0
        all_scores: list[tuple[str, float]] = []

        q = roi_upper_ink > 0
        q_count = int(q.sum())
        for tile_id, tmpl in self._templates_upper_ink.items():
            if tmpl.shape != roi_upper_ink.shape:
                continue
            result = cv2.matchTemplate(roi_upper_ink, tmpl, cv2.TM_CCOEFF_NORMED)
            _, ncc, _, _ = cv2.minMaxLoc(result)
            t = tmpl > 0
            denom = q_count + int(t.sum())
            dice = (2.0 * int(np.logical_and(q, t).sum()) / denom) if denom else 0.0
            score = 0.45 * float(ncc) + 0.55 * dice
            all_scores.append((tile_id, score))
            if score > best_conf:
                best_conf = score
                best_id = tile_id

        all_scores.sort(key=lambda x: x[1], reverse=True)
        second_conf = all_scores[1][1] if len(all_scores) > 1 else 0.0
        # Upper glyphs are useful only when the winner is clear. Otherwise many
        # suits share small strokes and this channel becomes noisy.
        if best_conf < 0.55 or (best_conf - second_conf) < 0.08:
            best_id = None

        if debug_info is not None:
            debug_info["upper_ink_top5"] = [{"tile_id": t, "confidence": round(c, 4)} for t, c in all_scores[:5]]

        return MatchResult(tile_id=best_id, confidence=best_conf, method="upper_ink")

    def _fuse_shape_results(self, struct_r, canny_r, debug_info) -> MatchResult:
        """纯形状融合：只使用 Structural + Canny，完全不依赖颜色/亮度。"""
        candidates = []
        if struct_r.tile_id is not None:
            candidates.append(struct_r)
        if canny_r.tile_id is not None:
            candidates.append(canny_r)

        if len(candidates) == 2 and struct_r.tile_id == canny_r.tile_id:
            # 两路一致：置信度上浮
            conf = min(max(struct_r.confidence, canny_r.confidence) * 1.15, 1.0)
            if debug_info is not None:
                debug_info["shape_fused"] = "agree"
                debug_info["shape_fused_conf"] = round(conf, 4)
            return MatchResult(tile_id=struct_r.tile_id, confidence=conf, method="shape_fused")

        if not candidates:
            # 两路都未识别
            if debug_info is not None:
                debug_info["shape_fused"] = "none"
            best = struct_r if struct_r.confidence >= canny_r.confidence else canny_r
            return best

        # 单选：取置信度高者
        best = max(candidates, key=lambda r: r.confidence)
        if debug_info is not None:
            debug_info["shape_fused"] = "single"
            debug_info["shape_winner"] = best.method
            debug_info["shape_fused_conf"] = round(best.confidence, 4)
        return best

    def _fuse_results(self, struct_r, hist_r, gray_r, orb_r, canny_r, debug_info, is_dark: bool = False) -> MatchResult:
        if is_dark:
            # 暗色模式：只信任 Canny 和 Structural
            candidates = []
            if struct_r.tile_id is not None:
                candidates.append(struct_r)
            if canny_r.tile_id is not None:
                candidates.append(canny_r)
            if len(candidates) == 2 and struct_r.tile_id == canny_r.tile_id:
                conf = max(struct_r.confidence, canny_r.confidence)
                return MatchResult(tile_id=struct_r.tile_id, confidence=min(conf * 1.1, 1.0), method="dark_fused")
            if candidates:
                # 若不一致，优先信任 Canny（在跨亮度场景下更鲁棒）
                if canny_r.tile_id is not None:
                    return MatchResult(tile_id=canny_r.tile_id, confidence=canny_r.confidence, method="dark_canny")
                return candidates[0]
            all_r = [struct_r, canny_r]
            best = max(all_r, key=lambda r: r.confidence)
            return best

        candidates = [r for r in [struct_r, hist_r, gray_r] if r.tile_id is not None]
        if orb_r and orb_r.tile_id is not None:
            candidates.append(orb_r)
        if canny_r and canny_r.tile_id is not None:
            candidates.append(canny_r)

        if not candidates:
            all_r = [struct_r, hist_r, gray_r]
            if orb_r:
                all_r.append(orb_r)
            if canny_r:
                all_r.append(canny_r)
            best = max(all_r, key=lambda r: r.confidence)
            return best

        vote_count: dict[str, int] = {}
        vote_conf: dict[str, float] = {}
        for r in candidates:
            tid = r.tile_id
            vote_count[tid] = vote_count.get(tid, 0) + 1
            if tid not in vote_conf or r.confidence > vote_conf[tid]:
                vote_conf[tid] = r.confidence

        max_votes = max(vote_count.values())
        top_candidates = [tid for tid, v in vote_count.items() if v == max_votes]
        if len(top_candidates) == 1:
            best_tid = top_candidates[0]
        else:
            best_tid = max(top_candidates, key=lambda t: vote_conf[t])

        n_votes = vote_count[best_tid]
        fused_conf = vote_conf[best_tid]
        if n_votes >= 3:
            fused_conf = min(fused_conf * 1.2, 1.0)
        elif n_votes >= 2:
            fused_conf = min(fused_conf * 1.1, 1.0)

        if struct_r.tile_id == best_tid and struct_r.confidence >= 0.6:
            fused_conf = max(fused_conf, struct_r.confidence)

        if fused_conf < self._threshold:
            best_tid = None

        return MatchResult(tile_id=best_tid, confidence=fused_conf, method="fused")

    def _extract_structure(self, img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 2:
            return self._extract_structure_from_gray(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        crop_x = max(3, int(w * 0.06))
        crop_y = max(3, int(h * 0.08))
        crop_b = max(3, int(h * 0.06))
        crop_r = max(3, int(w * 0.05))
        gray = gray[crop_y:h - crop_b, crop_x:w - crop_r]
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.resize(binary, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        _, binary = cv2.threshold(binary, 128, 255, cv2.THRESH_BINARY)
        return binary

    def _extract_structure_from_gray(self, gray: np.ndarray) -> np.ndarray:
        if gray is None or gray.size == 0:
            return np.zeros((self.TILE_SIZE[1], self.TILE_SIZE[0]), dtype=np.uint8)
        h, w = gray.shape
        if (w, h) == self.TILE_SIZE:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            return binary
        crop_x = max(3, int(w * 0.06))
        crop_y = max(3, int(h * 0.08))
        crop_b = max(3, int(h * 0.06))
        crop_r = max(3, int(w * 0.05))
        cropped = gray[crop_y:h - crop_b, crop_x:w - crop_r]
        binary = cv2.adaptiveThreshold(cropped, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.resize(binary, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        _, binary = cv2.threshold(binary, 128, 255, cv2.THRESH_BINARY)
        return binary

    def _extract_canny(self, img: np.ndarray) -> np.ndarray:
        if img is None or img.size == 0:
            return np.zeros((self.TILE_SIZE[1], self.TILE_SIZE[0]), dtype=np.uint8)
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()
        h, w = gray.shape
        crop_x = max(3, int(w * 0.06))
        crop_y = max(3, int(h * 0.08))
        crop_b = max(3, int(h * 0.06))
        crop_r = max(3, int(w * 0.05))
        gray = gray[crop_y:h - crop_b, crop_x:w - crop_r]
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # 自适应 Canny 阈值：基于图像中位数
        med = np.median(blurred)
        low = max(10, int(0.4 * med))
        high = min(255, int(1.33 * med))

        edges = cv2.Canny(blurred, low, high)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        edges = cv2.resize(edges, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        return edges

    def _preprocess_gray(self, img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 3:
            img = self._crop_tile_face(img)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        img = clahe.apply(img)
        img = cv2.resize(img, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        return img

    def _crop_tile_face(self, img: np.ndarray) -> np.ndarray:
        if img is None or img.size == 0:
            return img
        if len(img.shape) != 3:
            return img
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # 策略A：白色牌面（亮色界面）
        white_mask = ((hsv[:, :, 2] > 135) & (hsv[:, :, 1] < 115)).astype(np.uint8)
        ys, xs = np.where(white_mask > 0)
        if len(xs) >= 50:
            x1 = max(0, int(xs.min()) - 2)
            x2 = min(img.shape[1], int(xs.max()) + 3)
            y1 = max(0, int(ys.min()) - 2)
            y2 = min(img.shape[0], int(ys.max()) + 3)
            if x2 > x1 and y2 > y1:
                return img[y1:y2, x1:x2]
        # 策略B：暗色牌面（暗色界面）—— 找高饱和度+中等亮度的区域
        dark_mask = ((hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 50) & (hsv[:, :, 2] < 180)).astype(np.uint8)
        ys2, xs2 = np.where(dark_mask > 0)
        if len(xs2) >= 50:
            x1 = max(0, int(xs2.min()) - 2)
            x2 = min(img.shape[1], int(xs2.max()) + 3)
            y1 = max(0, int(ys2.min()) - 2)
            y2 = min(img.shape[0], int(ys2.max()) + 3)
            if x2 > x1 and y2 > y1:
                return img[y1:y2, x1:x2]
        # 都失败，返回原图
        return img

    def _extract_ink_mask(self, img: np.ndarray) -> np.ndarray:
        if img is None or img.size == 0:
            return np.zeros((self.TILE_SIZE[1], self.TILE_SIZE[0]), dtype=np.uint8)
        if len(img.shape) == 2:
            gray = img.copy()
        else:
            gray = cv2.cvtColor(self._crop_tile_face(img), cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        # Color-invariant ink: use grayscale strokes and local contrast, not hue.
        dark = (gray < min(170, int(gray.mean() * 0.92))).astype(np.uint8) * 255
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
        )
        edges = cv2.Canny(gray, 35, 110)
        ink = cv2.bitwise_or(cv2.bitwise_or(dark, adaptive), edges)
        h, w = ink.shape
        ink[: max(1, int(h * 0.10)), :] = 0
        ink[int(h * 0.96):, :] = 0
        ink[:, : max(1, int(w * 0.04))] = 0
        ink[:, int(w * 0.96):] = 0
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
        return ink

    def _extract_upper_ink_mask(self, img: np.ndarray) -> np.ndarray:
        """Extract upper-half dark ink, where number glyphs live on man/dragon tiles."""
        if img is None or img.size == 0:
            return np.zeros((self.TILE_SIZE[1], self.TILE_SIZE[0]), dtype=np.uint8)
        if len(img.shape) == 2:
            gray = img.copy()
        else:
            gray = cv2.cvtColor(self._crop_tile_face(img), cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, self.TILE_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
        )
        dark = (gray < min(165, int(gray.mean() * 0.92))).astype(np.uint8) * 255
        ink = cv2.bitwise_or(adaptive, dark)
        h, w = ink.shape
        ink[int(h * 0.56):, :] = 0
        ink[: max(1, int(h * 0.08)), :] = 0
        ink[:, : max(1, int(w * 0.12))] = 0
        ink[:, int(w * 0.88):] = 0
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
        return self._normalize_binary_glyph(ink, self.TILE_SIZE)

    def _normalize_binary_glyph(self, mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
        """Center a binary glyph by its ink bbox before shape matching."""
        if mask is None or mask.size == 0:
            return np.zeros((size[1], size[0]), dtype=np.uint8)
        ys, xs = np.where(mask > 0)
        out = np.zeros((size[1], size[0]), dtype=np.uint8)
        if len(xs) < 8 or len(ys) < 8:
            return out
        glyph = mask[max(0, ys.min() - 1):min(mask.shape[0], ys.max() + 2),
                     max(0, xs.min() - 1):min(mask.shape[1], xs.max() + 2)]
        gh, gw = glyph.shape[:2]
        max_w = max(1, size[0] - 8)
        max_h = max(1, size[1] - 8)
        scale = min(max_w / gw, max_h / gh)
        nw = max(1, int(round(gw * scale)))
        nh = max(1, int(round(gh * scale)))
        resized = cv2.resize(glyph, (nw, nh), interpolation=cv2.INTER_NEAREST)
        x = (size[0] - nw) // 2
        y = (size[1] - nh) // 2
        out[y:y + nh, x:x + nw] = resized
        return out

    def _prepare_gray_template(self, gray: np.ndarray) -> np.ndarray:
        if gray.shape[::-1] == self.TILE_SIZE:
            return gray.copy()
        return cv2.resize(gray, self.TILE_SIZE, interpolation=cv2.INTER_AREA)

    def _compute_hsv_hist(self, img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 2:
            return np.zeros(64 + 64, dtype=np.float32)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h_hist = cv2.calcHist([hsv], [0], None, [64], [0, 180])
        cv2.normalize(h_hist, h_hist)
        s_hist = cv2.calcHist([hsv], [1], None, [64], [0, 256])
        cv2.normalize(s_hist, s_hist)
        return np.concatenate([h_hist.flatten(), s_hist.flatten()])

    def save_template(self, roi: np.ndarray, tile_id: str, save_dir: str) -> str:
        os.makedirs(save_dir, exist_ok=True)
        bgr_path = os.path.join(save_dir, f"{tile_id}.png")
        if len(roi.shape) == 3:
            cv2.imwrite(bgr_path, roi)
            self._templates_bgr[tile_id] = roi
        else:
            bgr = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
            cv2.imwrite(bgr_path, bgr)
            self._templates_bgr[tile_id] = bgr
        self._templates_struct[tile_id] = self._extract_structure(roi)
        self._templates_canny[tile_id] = self._extract_canny(roi)
        self._templates_gray[tile_id] = self._preprocess_gray(roi)
        self._templates_ink[tile_id] = self._extract_ink_mask(roi)
        self._templates_upper_ink[tile_id] = self._extract_upper_ink_mask(roi)
        if len(roi.shape) == 3:
            self._templates_hist[tile_id] = self._compute_hsv_hist(roi)
        if self._use_orb and self._orb is not None:
            kp, des = self._orb.detectAndCompute(self._templates_struct[tile_id], None)
            self._orb_descriptors[tile_id] = (kp, des)
        logger.info("模板已保存: %s", tile_id)
        return bgr_path

    @property
    def loaded_tiles(self) -> list[str]:
        return list(set(list(self._templates_struct.keys()) + list(self._templates_gray.keys())))

    @property
    def threshold(self) -> float:
        return self._threshold


class ButtonRecognizer:
    BUTTON_IDS = ["碰", "吃", "杠_明", "杠_暗", "杠_补", "胡", "过"]
    OVERLAY_IDS = ["流局", "胡牌"]
    BTN_THRESHOLD = 0.75
    OVERLAY_THRESHOLD = 0.70

    def __init__(self, button_dir: str, overlay_dir: str):
        self._btn_templates: dict[str, np.ndarray] = {}
        self._overlay_templates: dict[str, np.ndarray] = {}
        if os.path.isdir(button_dir):
            self._load_dir(button_dir, self._btn_templates)
        if os.path.isdir(overlay_dir):
            self._load_dir(overlay_dir, self._overlay_templates)

    def _load_dir(self, dirpath: str, cache: dict) -> None:
        for fname in os.listdir(dirpath):
            if not fname.endswith(".png"):
                continue
            key = fname[:-4]
            img = cv2.imread(os.path.join(dirpath, fname), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                cache[key] = img

    def detect_buttons(self, roi: np.ndarray) -> list[str]:
        if roi is None or roi.size == 0 or not self._btn_templates:
            return []
        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi
        found = []
        for btn_id, tmpl in self._btn_templates.items():
            if tmpl.shape[0] > gray.shape[0] or tmpl.shape[1] > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val >= self.BTN_THRESHOLD:
                found.append(btn_id)
        return found

    def detect_overlay(self, roi: np.ndarray) -> Optional[str]:
        if roi is None or roi.size == 0 or not self._overlay_templates:
            return None
        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi
        best_id = None
        best_conf = 0.0
        for ov_id, tmpl in self._overlay_templates.items():
            if tmpl.shape[0] > gray.shape[0] or tmpl.shape[1] > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > best_conf:
                best_conf = max_val
                best_id = ov_id
        if best_conf >= self.OVERLAY_THRESHOLD:
            return best_id
        return None

    @property
    def has_button_templates(self) -> bool:
        return bool(self._btn_templates)

    @property
    def has_overlay_templates(self) -> bool:
        return bool(self._overlay_templates)
