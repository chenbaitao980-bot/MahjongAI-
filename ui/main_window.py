from __future__ import annotations
import os
import yaml
import glob
import time
import math
import shutil
import json
from copy import deepcopy
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QCloseEvent, QPixmap, QImage
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QStatusBar, QMessageBox,
    QGridLayout, QScrollArea, QFileDialog, QProgressDialog,
    QDialog, QComboBox, QDialogButtonBox,
)
import cv2
import numpy as np
import mss

from ui.region_selector import RegionSelectorOverlay
from ui.calibration import CalibrationWizard
from ui.capture_panel import CapturePanel
from ui.battle_panel import ApiConfigDialog, BattlePanel
from ui.collection_panels import RegionDivisionPanel, EventCollectionPanel
from battle import BattleService
from battle.state import BattleAdvice, BattleState
from vision.capture import ScreenCapture
from vision.discard_tile_cropper import (
    extract_discard_tile_candidates,
    prepare_trainable_discard_roi_image,
)
from vision.hand_region_module import HandRegionModule, prepare_trainable_hand_roi_image
from vision.layout import LayoutCalculator
from vision.recognizer import TileRecognizer, ButtonRecognizer
from vision.discard_recognizer import DiscardAreaRecognizer
from vision.hog_classifier import TileHOGClassifier
from vision.hog_classifier import MIN_TRUSTED_SAMPLES_PER_CLASS
from vision.pipeline import RecognitionPipeline
from game.session import GameSession
from game.state import ALL_TILE_IDS, GameState
from utils.paths import data_path, template_dir

_MAHJONG_QSS = """
QWidget {
    background: #1c2820;
    color: #ccddd5;
    font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid #3a5c48;
    background: #1c2820;
}
QTabBar::tab {
    background: #223228;
    color: #7aaa8a;
    border: 1px solid #3a5c48;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 4px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #2a3e30;
    color: #74c69d;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #283a2e;
    color: #ccddd5;
}
QGroupBox {
    background: #223228;
    border: 1px solid #3a5c48;
    border-radius: 7px;
    margin-top: 9px;
    padding-top: 7px;
    font-weight: bold;
    color: #74c69d;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: #74c69d;
    background: #1c2820;
    border-radius: 3px;
}
QPushButton {
    background: #2a3e30;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    border-radius: 6px;
    padding: 3px 10px;
    min-height: 22px;
}
QPushButton:hover {
    background: #334a3c;
    border-color: #52b788;
    color: #74c69d;
}
QPushButton:pressed {
    background: #1c2820;
    border-color: #52b788;
    color: #52b788;
}
QPushButton:disabled {
    background: #1e2c22;
    color: #3a5042;
    border-color: #2a3c30;
}
QLineEdit, QPlainTextEdit, QTextEdit {
    background: #18231c;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    border-radius: 5px;
    padding: 2px 5px;
    selection-background-color: #52b788;
    selection-color: #fff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #52b788;
}
QComboBox {
    background: #2a3e30;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    border-radius: 5px;
    padding: 2px 6px;
    min-height: 22px;
}
QComboBox:hover { border-color: #52b788; }
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #7aaa8a;
    margin-right: 4px;
}
QComboBox QAbstractItemView {
    background: #2a3e30;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    selection-background-color: #334a3c;
    selection-color: #74c69d;
    outline: none;
}
QSpinBox {
    background: #18231c;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    border-radius: 5px;
    padding: 2px 4px;
}
QSpinBox:hover { border-color: #52b788; }
QSpinBox::up-button, QSpinBox::down-button {
    background: #2a3e30;
    border: none;
    width: 16px;
}
QCheckBox { color: #ccddd5; spacing: 5px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #3a5c48;
    border-radius: 4px;
    background: #18231c;
}
QCheckBox::indicator:checked {
    background: #52b788;
    border-color: #52b788;
}
QCheckBox::indicator:hover { border-color: #74c69d; }
QTableWidget {
    background: #18231c;
    color: #ccddd5;
    border: 1px solid #3a5c48;
    border-radius: 5px;
    gridline-color: #2a3e30;
    alternate-background-color: #1f2e24;
}
QHeaderView::section {
    background: #2a3e30;
    color: #74c69d;
    border: none;
    border-right: 1px solid #3a5c48;
    border-bottom: 1px solid #3a5c48;
    padding: 4px 5px;
    font-weight: bold;
}
QTableWidget::item { padding: 2px 4px; }
QTableWidget::item:selected {
    background: #334a3c;
    color: #74c69d;
}
QScrollBar:vertical {
    background: #1c2820;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a5c48;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #52b788; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1c2820;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #3a5c48;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #52b788; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar {
    background: #223228;
    color: #7aaa8a;
    border-top: 1px solid #3a5c48;
}
QDialog { background: #1c2820; }
QDialogButtonBox QPushButton { min-width: 70px; }
QMessageBox { background: #1c2820; }
"""


def _hog_sample_counts(samples_dir: str) -> dict[str, int]:
    """Return per-class png counts exactly as HOG training will consume them."""
    counts: dict[str, int] = {}
    if not os.path.isdir(samples_dir):
        return counts
    for tile_id in sorted(os.listdir(samples_dir)):
        if tile_id.startswith("_"):
            continue
        tile_dir = os.path.join(samples_dir, tile_id)
        if not os.path.isdir(tile_dir):
            continue
        pngs = glob.glob(os.path.join(tile_dir, "*.png"))
        if pngs:
            counts[tile_id] = len(pngs)
    return counts


def _read_image(path: str) -> np.ndarray | None:
    """Read images with Chinese file names reliably on Windows."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return cv2.imread(path)


def _cleanup_debug_dir(retain_hours: int = 24) -> None:
    debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug")
    if not os.path.isdir(debug_dir):
        return

    cutoff = time.time() - max(1, retain_hours) * 3600
    for name in os.listdir(debug_dir):
        path = os.path.join(debug_dir, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except OSError:
            pass


def _prepare_trainable_roi_image(img: np.ndarray) -> tuple[bool, np.ndarray | None, str]:
    """Return a cleaned single-tile face crop for hand training."""
    return prepare_trainable_hand_roi_image(img)


def _is_trainable_roi_image(img: np.ndarray) -> tuple[bool, str]:
    ok, _crop, reason = _prepare_trainable_roi_image(img)
    return ok, reason


TILE_DISPLAY_NAMES = {
    **{f"{i}m": f"{i}万" for i in range(1, 10)},
    **{f"{i}p": f"{i}筒" for i in range(1, 10)},
    **{f"{i}s": f"{i}条" for i in range(1, 10)},
    "1z": "东", "2z": "南", "3z": "西", "4z": "北",
    "5z": "中", "6z": "发", "7z": "白",
}


def _ensure_battle_config_defaults(config: dict) -> dict:
    app_cfg = config.setdefault("app", {})
    app_cfg.setdefault("match_threshold", 0.8)
    app_cfg.setdefault("output_dir", "data")

    deepseek_cfg = config.setdefault("deepseek", {})
    deepseek_cfg.setdefault("api_key", "")
    deepseek_cfg.setdefault("model", "deepseek-chat")

    vision_cfg = config.setdefault("vision", {})
    vision_cfg.setdefault("provider", "auto")
    vision_cfg.setdefault("volc", {})
    vision_cfg.setdefault("glm", {})
    vision_cfg.setdefault("qwen", {})
    vision_cfg["volc"].setdefault("api_key", "")
    vision_cfg["volc"].setdefault("model", "")
    vision_cfg["volc"].setdefault("endpoint", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    vision_cfg["glm"].setdefault("api_key", "")
    vision_cfg["glm"].setdefault("model", "glm-4.6v-flash")
    vision_cfg["qwen"].setdefault("api_key", "")
    vision_cfg["qwen"].setdefault("model", "qwen-vl-plus-latest")

    battle_cfg = config.setdefault("battle", {})
    battle_cfg.setdefault("ai_recognition_enabled", False)
    return config


class RoiTrainingDialog(QDialog):
    """Review historical ROI images and add confirmed samples to cleaned training data."""

    def __init__(self, roi_paths: list[str], recognizer: TileRecognizer, parent=None,
                 save_dir: str | None = None,
                 prepare_fn=None):
        super().__init__(parent)
        self.setWindowTitle("数据训练吧")
        self.resize(520, 560)
        self._roi_paths = roi_paths
        self._recognizer = recognizer
        self._save_dir = save_dir  # None = 使用默认 tile_samples_cleaned
        self._prepare_fn = prepare_fn or _prepare_trainable_roi_image
        self._index = 0
        self.accepted_count = 0
        self.closed_without_training = False
        self.processed_sources = self._extract_processed_sources(roi_paths)
        self._current_guess = ""
        self._current_confidence = 0.0
        self._current_clean_img = None
        self._current_prepare_ok = False

        root = QVBoxLayout(self)
        self._info = QLabel("")
        self._info.setWordWrap(True)
        root.addWidget(self._info)

        preview_row = QHBoxLayout()

        raw_layout = QVBoxLayout()
        raw_layout.addWidget(QLabel("原始 ROI"))
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumHeight(260)
        self._image.setStyleSheet("border:1px solid #bbb; background:#f8f8f8;")
        raw_layout.addWidget(self._image)
        preview_row.addLayout(raw_layout, 1)

        clean_layout = QVBoxLayout()
        self._clean_title = QLabel("训练入库预览")
        clean_layout.addWidget(self._clean_title)
        self._clean_image = QLabel()
        self._clean_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clean_image.setMinimumHeight(260)
        self._clean_image.setStyleSheet("border:1px solid #bbb; background:#f8f8f8;")
        clean_layout.addWidget(self._clean_image)
        preview_row.addLayout(clean_layout, 1)

        root.addLayout(preview_row)

        row = QHBoxLayout()
        row.addWidget(QLabel("正确牌型："))
        self._combo = QComboBox()
        from game.state import ALL_TILE_IDS
        for tid in ALL_TILE_IDS:
            self._combo.addItem(f"{TILE_DISPLAY_NAMES.get(tid, tid)} ({tid})", tid)
        row.addWidget(self._combo, 1)
        root.addLayout(row)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("加入训练集")
        self._btn_skip = QPushButton("跳过")
        self._btn_delete = QPushButton("删除坏样本")
        self._btn_clear_rest = QPushButton("清空剩余ROI")
        self._btn_close = QPushButton("关闭并训练")
        self._btn_add.clicked.connect(self._accept_current)
        self._btn_skip.clicked.connect(self._next)
        self._btn_delete.clicked.connect(self._delete_current)
        self._btn_clear_rest.clicked.connect(self._clear_remaining)
        self._btn_close.clicked.connect(self._close_and_train)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_skip)
        btn_row.addWidget(self._btn_delete)
        btn_row.addWidget(self._btn_clear_rest)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._load_current()

    def _load_current(self) -> None:
        while self._index < len(self._roi_paths) and not os.path.exists(self._roi_paths[self._index]):
            self._index += 1
        if self._index >= len(self._roi_paths):
            self._info.setText(f"没有更多 ROI。已加入 {self.accepted_count} 张。")
            self._image.clear()
            self._clean_image.clear()
            self._clean_title.setText("训练入库预览")
            self._btn_add.setEnabled(False)
            self._btn_skip.setEnabled(False)
            self._btn_delete.setEnabled(False)
            self._btn_clear_rest.setEnabled(False)
            return

        path = self._roi_paths[self._index]
        img = cv2.imread(path)
        if img is None:
            self._delete_path(path)
            self._index += 1
            self._load_current()
            return
        result = self._recognizer.match_tile(img)
        ok, clean_img, prepare_reason = self._prepare_fn(img)
        self._current_guess = result.tile_id or ""
        self._current_confidence = float(result.confidence or 0.0)
        self._current_clean_img = clean_img
        self._current_prepare_ok = bool(ok and clean_img is not None)
        guess = result.tile_id
        if guess:
            pos = self._combo.findData(guess)
            if pos >= 0:
                self._combo.setCurrentIndex(pos)
        guess_text = f"{TILE_DISPLAY_NAMES.get(guess, guess)} ({guess}) {result.confidence:.3f} {result.method}" if guess else "无"
        self._info.setText(
            f"{self._index + 1}/{len(self._roi_paths)}  当前猜测：{guess_text}\n"
            f"预处理：{'可入库' if ok else '失败'} ({prepare_reason})\n{path}"
        )
        self._set_preview_image(self._image, img)
        self._clean_title.setText(f"训练入库预览 ({prepare_reason})")
        if ok and clean_img is not None:
            self._set_preview_image(self._clean_image, clean_img)
        else:
            self._clean_image.clear()
            self._clean_image.setText("预处理失败")

    def _accept_current(self) -> None:
        if self._index >= len(self._roi_paths):
            return
        src = self._roi_paths[self._index]
        if not self._current_prepare_ok or self._current_clean_img is None:
            img = cv2.imread(src)
            if img is None:
                self._next()
                return
            ok, _clean_img, reason = self._prepare_fn(img)
            if not ok:
                QMessageBox.warning(
                    self,
                    "坏ROI",
                    f"这张 ROI 看起来不是完整单张牌，已拒绝加入训练集。\n原因：{reason}\n\n{src}",
                )
                self._delete_path(src)
                self._index += 1
                self._load_current()
                return
            self._next()
            return
        tile_id = self._combo.currentData()
        if (
            self._current_guess
            and tile_id != self._current_guess
            and self._current_confidence >= 0.78
        ):
            ret = QMessageBox.question(
                self,
                "标签冲突确认",
                "当前样本与你选的标签冲突。\n"
                f"模型当前高置信预测：{TILE_DISPLAY_NAMES.get(self._current_guess, self._current_guess)} ({self._current_guess})，"
                f"置信度 {self._current_confidence:.3f}\n"
                f"你当前选择：{TILE_DISPLAY_NAMES.get(tile_id, tile_id)} ({tile_id})\n\n"
                "如果这是模型识别错了，请继续；如果是手滑选错，建议取消后重新确认。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        if self._save_dir:
            dst_dir = os.path.join(self._save_dir, tile_id)
        else:
            dst_dir = data_path(os.path.join("data", "tile_samples_cleaned", tile_id))
        os.makedirs(dst_dir, exist_ok=True)
        import time
        dst = os.path.join(dst_dir, f"{time.strftime('%Y%m%d_%H%M%S')}_{self.accepted_count:04d}.png")
        cv2.imwrite(dst, self._current_clean_img)
        if hasattr(self._recognizer, "add_training_sample"):
            self._recognizer.add_training_sample(self._current_clean_img, tile_id, source=dst)
        parent = self.parent()
        if parent is not None and hasattr(parent, "_pipeline"):
            parent._pipeline.clear_match_cache()
        self._delete_path(src)
        self.accepted_count += 1
        self._index += 1
        self._load_current()

    def _next(self) -> None:
        self._index += 1
        self._load_current()

    def _delete_current(self) -> None:
        if self._index < len(self._roi_paths):
            self._delete_path(self._roi_paths[self._index])
            self._index += 1
        self._load_current()

    def _set_preview_image(self, label: QLabel, img: np.ndarray) -> None:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if len(img.shape) == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            QSize(420, 300),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pix)
        label.setText("")

    def _clear_remaining(self) -> None:
        remaining = [p for p in self._roi_paths[self._index:] if os.path.exists(p)]
        if not remaining:
            self._load_current()
            return
        ret = QMessageBox.question(
            self,
            "清空剩余ROI",
            f"将删除当前队列剩余 {len(remaining)} 张 ROI 图片。\n"
            "已加入训练集的样本不会删除。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        for path in remaining:
            self._delete_path(path)
        self._index = len(self._roi_paths)
        self._load_current()

    def _close_and_train(self) -> None:
        for path in [p for p in self._roi_paths[self._index:] if os.path.exists(p)]:
            self._delete_path(path)
        self._index = len(self._roi_paths)
        self.accept()

    def reject(self) -> None:
        self.closed_without_training = True
        for path in [p for p in self._roi_paths[self._index:] if os.path.exists(p)]:
            self._delete_path(path)
        super().reject()

    def _delete_path(self, path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    @staticmethod
    def _extract_processed_sources(paths: list[str]) -> set[str]:
        sources: set[str] = set()
        for path in paths:
            name = os.path.basename(path)
            if name.startswith("roi_session_"):
                parts = name.split("_")
                # roi_session_YYYYMMDD_HHMMSS_frame_NNNN_...
                if len(parts) >= 6 and parts[1] == "session":
                    sources.add(f"session_{parts[2]}_{parts[3]}:{parts[4]}_{parts[5]}")
            elif name.endswith("_picture_tile_request.png") or name.endswith("_picture_tile_response.png"):
                sources.add(f"battle_picture:{name}")
        return sources

    @property
    def current_source_key(self) -> str | None:
        if self._index >= len(self._roi_paths):
            return None
        sources = self._extract_processed_sources([self._roi_paths[self._index]])
        return next(iter(sources), None)


class HOGTrainerThread(QThread):
    """后台训练 HOG+SVM 模型线程。"""
    progress = pyqtSignal(str)      # 进度文字
    finished_ok = pyqtSignal(dict)  # 训练成功，返回统计 dict
    finished_err = pyqtSignal(str)  # 训练失败，返回错误信息

    def __init__(self, samples_dir: str, model_path: str, auto_params: bool = False, parent=None):
        super().__init__(parent)
        self.samples_dir = samples_dir
        self.model_path = model_path
        self.temp_model_path = model_path + ".new"
        self.auto_params = auto_params

    def run(self):
        try:
            self.progress.emit("正在加载样本...")
            samples: list[np.ndarray] = []
            labels: list[str] = []

            if not os.path.isdir(self.samples_dir):
                raise FileNotFoundError(f"样本目录不存在：{self.samples_dir}")

            class_counts = _hog_sample_counts(self.samples_dir)
            tile_ids = sorted(class_counts)
            if not tile_ids:
                raise ValueError("未找到任何样本类别")

            for tile_id in tile_ids:
                tile_dir = os.path.join(self.samples_dir, tile_id)
                pngs = glob.glob(os.path.join(tile_dir, "*.png"))
                for p in pngs:
                    img = _read_image(p)
                    if img is not None:
                        samples.append(img)
                        labels.append(tile_id)

            if not samples:
                raise ValueError("未找到任何 .png 样本")

            self.progress.emit(f"加载完成：{len(samples)} 张，{len(set(labels))} 类。开始训练...")

            clf = TileHOGClassifier()
            stats = clf.train(samples, labels, auto_params=self.auto_params, C=10.0, gamma=0.001)
            stats["samples_dir"] = self.samples_dir

            os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
            clf.save(self.temp_model_path)

            self.finished_ok.emit(stats)
        except Exception as e:
            self.finished_err.emit(str(e))


class CaptureWorkerThread(QThread):
    """Run recognition off the UI thread so painting and counters stay responsive."""

    frame_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, pipeline: RecognitionPipeline, interval_ms: int, parent=None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._interval_ms = max(1, int(interval_ms))
        self._running = True

    def request_stop(self) -> None:
        self._running = False

    def run(self):
        self._pipeline.reset_runtime()
        next_tick = time.perf_counter()
        while self._running:
            try:
                state = self._pipeline.run_frame()
            except Exception as e:
                self.failed.emit(str(e))
                break
            self.frame_ready.emit(state)

            next_tick += self._interval_ms / 1000.0
            delay = next_tick - time.perf_counter()
            if delay > 0:
                self.msleep(max(1, int(delay * 1000)))
            else:
                next_tick = time.perf_counter()
        self._pipeline.stop()


class BattleAnalysisThread(QThread):
    finished_ok = pyqtSignal(object, object)
    finished_err = pyqtSignal(str)
    stream_chunk = pyqtSignal(str)

    def __init__(self, service: BattleService, state: BattleState, trigger_reason: str, parent=None, mode: str = "full"):
        super().__init__(parent)
        self._service = service
        self._state = deepcopy(state)
        self._trigger_reason = trigger_reason
        self._mode = mode

    def run(self):
        on_chunk = lambda text: self.stream_chunk.emit(text)
        try:
            if self._trigger_reason == "start":
                state, advice = self._service.analyze_opening(self._state)
            elif self._mode == "recognition_only":
                state, advice = self._service.analyze_recognition_only(self._state, self._trigger_reason)
            elif self._mode == "state_only":
                state, advice = self._service.analyze_state_only(self._state, self._trigger_reason)
            elif self._mode == "state_with_ai":
                state, advice = self._service.analyze_state_with_ai(self._state, self._trigger_reason, on_chunk=on_chunk)
            else:
                state, advice = self._service.analyze_after_action(self._state, self._trigger_reason, on_chunk=on_chunk)
            self.finished_ok.emit(state, advice)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self._config = _ensure_battle_config_defaults(config)
        self._session: GameSession | None = None
        self._capture_worker: CaptureWorkerThread | None = None
        self._battle_worker: BattleAnalysisThread | None = None
        self._battle_analysis_started_at: float | None = None
        self._hog_train_thread: HOGTrainerThread | None = None

        self.setWindowTitle("台州麻将AI — 视觉识别层 v1.0")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(860, 560)
        self.setStyleSheet(_MAHJONG_QSS)

        # 初始化各模块
        self._layout_calc = LayoutCalculator(config)

        # 从已保存的 config 加载截图区域，避免重启后丢失
        gw = config.get("game_window", {})
        if gw.get("width") and gw.get("height"):
            self._capture = ScreenCapture(region={
                "top": gw.get("top", 0),
                "left": gw.get("left", 0),
                "width": gw["width"],
                "height": gw["height"],
            })
        else:
            self._capture = ScreenCapture()
        self._hand_region = HandRegionModule()

        tile_dir = template_dir("tiles")
        btn_dir = template_dir("buttons")
        overlay_dir = template_dir("overlays")
        threshold = config.get("app", {}).get("match_threshold", 0.60)

        # 优先加载 HOG+SVM 模型（如果存在）
        hog_model_path = os.path.join(os.path.dirname(tile_dir), "..", "models", "tile_svm.xml")
        hog_model_path = os.path.normpath(os.path.abspath(hog_model_path))
        self._tile_rec = TileRecognizer(tile_dir, threshold, use_orb=True, hog_model_path=hog_model_path)
        self._btn_rec = ButtonRecognizer(btn_dir, overlay_dir)
        self._discard_rec = DiscardAreaRecognizer(tile_dir, threshold)
        self._pipeline = RecognitionPipeline(
            self._capture, self._layout_calc, self._tile_rec, self._btn_rec,
            discard_recognizer=self._discard_rec,
        )
        self._pipeline.set_on_frame(self._on_frame)
        self._battle_service = BattleService(
            self._capture,
            self._layout_calc,
            self._hand_region,
            self._tile_rec,
            self._config,
        )

        self._region_selector = RegionSelectorOverlay()
        self._region_selector.region_selected.connect(self._on_region_selected)
        self._region_selector.cancelled.connect(self._on_region_cancelled)

        # 截屏识别（牌面收集页面的一键截屏）
        self._tile_capture_selector = RegionSelectorOverlay()
        self._tile_capture_selector.cropped_image.connect(self._on_tile_capture_cropped)
        self._tile_capture_selector.cancelled.connect(self._on_tile_capture_cancelled)

        # 截屏验证（点击某个已收集牌面后，截图验证该牌面是否匹配）
        self._tile_verify_selector = RegionSelectorOverlay()
        self._tile_verify_selector.cropped_image.connect(self._on_verify_capture_cropped)
        self._tile_verify_selector.cancelled.connect(self._on_verify_capture_cancelled)
        self._verify_tile_id: str | None = None

        # 截屏替换（点击某个已收集牌面后，截图框选并直接替换该样本）
        self._tile_replace_selector = RegionSelectorOverlay()
        self._tile_replace_selector.cropped_image.connect(self._on_replace_capture_cropped)
        self._tile_replace_selector.cancelled.connect(self._on_replace_capture_cancelled)
        self._replace_tile_id: str | None = None

        self._setup_ui()
        self._update_region_status()

    # ------------------------------------------------------------------ #
    #  UI 搭建                                                             #
    # ------------------------------------------------------------------ #

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        tabs = QTabWidget()
        tabs.addTab(self._build_setup_tab(), "① 游戏窗口")
        tabs.addTab(self._build_calibration_tab(), "② 牌面收集")
        tabs.addTab(self._build_region_tab(), "③ 区域划分")
        tabs.addTab(self._build_event_tab(), "④ 事件收集")
        tabs.addTab(self._build_capture_tab(), "⑤ 识别运行")
        tabs.addTab(self._build_battle_tab(), "⑥ 正式战斗")
        root.addWidget(tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    def _build_setup_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        box = QGroupBox("游戏窗口区域")
        b_layout = QVBoxLayout(box)
        self._region_status = QLabel("未设置")
        self._region_status.setFont(QFont("Consolas", 10))
        b_layout.addWidget(self._region_status)
        btn = QPushButton("🖱 框选游戏窗口")
        btn.setFixedHeight(36)
        btn.clicked.connect(self._show_region_selector)
        b_layout.addWidget(btn)
        layout.addWidget(box)

        # 数据收集状态
        tmpl_box = QGroupBox("牌面样本状态")
        t_layout = QVBoxLayout(tmpl_box)
        self._tmpl_status = QLabel(self._get_template_status())
        t_layout.addWidget(self._tmpl_status)
        btn_refresh = QPushButton("刷新状态")
        btn_refresh.clicked.connect(self._refresh_template_status)
        t_layout.addWidget(btn_refresh)
        layout.addWidget(tmpl_box)

        layout.addStretch()
        return w

    def _build_calibration_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # 顶部说明
        desc = QLabel(
            "<b>牌面收集</b> — 绿色=已收集，灰色=未收集。<br>"
            "点击牌面可查看/替换样本，点击「打开牌面收集向导」从截图中补充新牌面。"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_calib = QPushButton("打开牌面收集向导")
        btn_calib.setFixedHeight(36)
        btn_calib.clicked.connect(self._open_calibration)
        btn_row.addWidget(btn_calib)

        btn_quick = QPushButton("📷 截屏识别")
        btn_quick.setFixedHeight(36)
        btn_quick.setToolTip("隐藏窗口并截图，框选一张牌后自动识别牌种")
        btn_quick.clicked.connect(self._on_quick_capture)
        btn_row.addWidget(btn_quick)

        self._btn_train_hog = QPushButton("🧠 一键训练HOG模型")
        self._btn_train_hog.setFixedHeight(36)
        self._btn_train_hog.setToolTip("使用 data/tile_samples_cleaned 下的干净样本训练 HOG+SVM 模型（自动忽略 _suspicious）")
        self._btn_train_hog.clicked.connect(self._on_train_hog)
        btn_row.addWidget(self._btn_train_hog)

        self._calib_status = QLabel(f"已收集：{len(self._tile_rec.loaded_tiles)} / 34 种")
        btn_row.addWidget(self._calib_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 牌面图鉴网格（34 格）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(280)
        self._tile_grid_widget = QWidget()
        self._tile_grid = QGridLayout(self._tile_grid_widget)
        self._tile_grid.setSpacing(4)
        self._tile_cells: dict[str, QLabel] = {}

        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }
        from game.state import ALL_TILE_IDS
        for i, tid in enumerate(ALL_TILE_IDS):
            cell = QLabel()
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setFixedSize(72, 90)
            cell.setStyleSheet("border:1px solid #ccc; border-radius:4px; background:#f0f0f0;")
            cell.setToolTip(f"{TILE_DISPLAY.get(tid, tid)} ({tid})")
            cell.setProperty("tile_id", tid)
            cell.mousePressEvent = lambda event, t=tid: self._on_tile_cell_clicked(t)
            self._tile_grid.addWidget(cell, i // 9, i % 9)
            self._tile_cells[tid] = cell

        scroll.setWidget(self._tile_grid_widget)
        layout.addWidget(scroll)

        self._refresh_tile_grid()
        layout.addStretch()
        return w

    def _refresh_tile_grid(self):
        """刷新牌面图鉴网格的显示。"""
        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }
        tile_dir = template_dir("tiles")
        for tid, cell in self._tile_cells.items():
            path = os.path.join(tile_dir, f"{tid}.png")
            name = TILE_DISPLAY.get(tid, tid)
            if os.path.exists(path):
                # 有样本：显示缩略图
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    # 灰度转 RGB 用于显示
                    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                    h, w = rgb.shape[:2]
                    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
                    pix = QPixmap.fromImage(qimg).scaled(
                        60, 72, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    cell.setPixmap(pix)
                cell.setStyleSheet("border:1px solid #2a7; border-radius:4px; background:#e8f5e9;")
                cell.setToolTip(f"{name} ({tid}) — 已收集，点击编辑")
            else:
                # 无样本：显示文字
                cell.setText(name)
                cell.setStyleSheet(
                    "border:1px solid #ccc; border-radius:4px; background:#f0f0f0;"
                    "color:#999; font-size:12px;"
                )
                cell.setToolTip(f"{name} ({tid}) — 未收集")
        self._calib_status.setText(f"已收集：{len(self._tile_rec.loaded_tiles)} / 34 种")

    def _on_tile_cell_clicked(self, tile_id: str):
        """点击牌面格子：已收集的提供替换/验证/取消，未收集的提示去收集。"""
        tile_dir = template_dir("tiles")
        path = os.path.join(tile_dir, f"{tile_id}.png")
        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }
        name = TILE_DISPLAY.get(tile_id, tile_id)
        if os.path.exists(path):
            msg = QMessageBox(self)
            msg.setWindowTitle(f"编辑牌面样本 — {name}")
            msg.setText(f"「{name}」({tile_id}) 已有牌面样本。")
            msg.setInformativeText("请选择要执行的操作：")
            btn_replace = msg.addButton("从文件替换", QMessageBox.ButtonRole.ActionRole)
            btn_screenshot = msg.addButton("截屏替换", QMessageBox.ButtonRole.ActionRole)
            btn_verify = msg.addButton("截屏验证", QMessageBox.ButtonRole.ActionRole)
            btn_cancel = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == btn_screenshot:
                self._replace_tile_id = tile_id
                self._start_replace_capture()
            elif msg.clickedButton() == btn_replace:
                file_path, _ = QFileDialog.getOpenFileName(
                    self, f"选择新的「{name}」牌面样本", "", "图片 (*.png *.jpg *.bmp)"
                )
                if file_path:
                    img = cv2.imread(file_path)
                    if img is not None:
                        self._tile_rec.save_template(img, tile_id, tile_dir)
                        self._refresh_tile_grid()
                        self.statusBar().showMessage(f"已替换「{name}」牌面样本")
                    else:
                        QMessageBox.warning(self, "错误", "无法读取图片")

            elif msg.clickedButton() == btn_verify:
                self._verify_tile_id = tile_id
                self._start_verify_capture()
        else:
            # 未收集的牌面：提供截屏上传和从文件上传选项
            msg = QMessageBox(self)
            msg.setWindowTitle(f"收集牌面样本 — {name}")
            msg.setText(f"「{name}」({tile_id}) 尚未收集。")
            msg.setInformativeText("请选择收集方式：")
            btn_screenshot = msg.addButton("截屏上传", QMessageBox.ButtonRole.ActionRole)
            btn_file = msg.addButton("从文件上传", QMessageBox.ButtonRole.ActionRole)
            btn_cancel = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == btn_screenshot:
                self._replace_tile_id = tile_id
                self._start_replace_capture()
            elif msg.clickedButton() == btn_file:
                file_path, _ = QFileDialog.getOpenFileName(
                    self, f"选择「{name}」牌面样本图片", "", "图片 (*.png *.jpg *.bmp)"
                )
                if file_path:
                    img = cv2.imread(file_path)
                    if img is not None:
                        self._tile_rec.save_template(img, tile_id, tile_dir)
                        self._refresh_tile_grid()
                        self._refresh_template_status()
                        self.statusBar().showMessage(f"已收集「{name}」牌面样本")
                    else:
                        QMessageBox.warning(self, "错误", "无法读取图片")

    def _start_verify_capture(self):
        """隐藏主窗口，静默截全屏，弹出覆盖层供用户框选要验证的牌。"""
        self.hide()
        QTimer.singleShot(250, self._do_verify_capture)

    def _do_verify_capture(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._tile_verify_selector.set_background_image(arr)
        self._tile_verify_selector.show()

    def _on_verify_capture_cancelled(self):
        self._tile_verify_selector.clear_background()
        self._verify_tile_id = None
        self.show()
        self.raise_()
        self.statusBar().showMessage("截屏验证已取消")

    def _on_verify_capture_cropped(self, cropped: np.ndarray):
        """用户框选完成，只与点击的牌面样本比对，显示精确相似度。"""
        self._tile_verify_selector.clear_background()
        self.show()
        self.raise_()

        tile_id = self._verify_tile_id
        self._verify_tile_id = None
        if tile_id is None:
            return

        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }
        name = TILE_DISPLAY.get(tile_id, tile_id)

        if tile_id not in self._tile_rec.loaded_tiles:
            QMessageBox.information(self, "验证失败", f"「{name}」牌面样本尚未加载。")
            return

        result = self._tile_rec.match_single_template(cropped, tile_id)
        conf = result.confidence

        if conf >= 0.80:
            level = "优秀"
            title = "验证结果"
            color = "#2d8a2d"
        elif conf >= 0.60:
            level = "一般"
            title = "验证结果"
            color = "#d4a017"
        else:
            level = "较差"
            title = "验证结果"
            color = "#c00"

        self.statusBar().showMessage(
            f"截屏验证：「{name}」相似度 {conf:.3f}（{level}）"
        )
        QMessageBox.information(
            self, title,
            f"牌面样本：「{name}」({tile_id})\n"
            f"相似度：{conf:.3f}\n"
            f"评级：{level}\n\n"
            f"说明：数值为该截图与「{name}」牌面样本的直接相似度，"
            f"未与其他牌种比较。"
        )
        if conf >= 0.60:
            self._highlight_tile_cell(tile_id)

    # ------------------------------------------------------------------ #
    #  截屏替换                                                            #
    # ------------------------------------------------------------------ #

    def _start_replace_capture(self):
        """隐藏主窗口，静默截全屏，弹出覆盖层供用户框选要替换的牌。"""
        self.hide()
        QTimer.singleShot(250, self._do_replace_capture)

    def _do_replace_capture(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._tile_replace_selector.set_background_image(arr)
        self._tile_replace_selector.show()

    def _on_replace_capture_cancelled(self):
        self._tile_replace_selector.clear_background()
        self._replace_tile_id = None
        self.show()
        self.raise_()
        self.statusBar().showMessage("截屏替换已取消")

    def _on_replace_capture_cropped(self, cropped: np.ndarray):
        """用户框选完成，直接用裁剪图替换对应牌面样本。"""
        self._tile_replace_selector.clear_background()
        self.show()
        self.raise_()

        tile_id = self._replace_tile_id
        self._replace_tile_id = None
        if tile_id is None:
            return

        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }
        name = TILE_DISPLAY.get(tile_id, tile_id)
        tile_dir = template_dir("tiles")

        self._tile_rec.save_template(cropped, tile_id, tile_dir)
        self._refresh_tile_grid()
        self.statusBar().showMessage(f"截屏替换成功：「{name}」牌面样本已更新")
        QMessageBox.information(
            self, "替换成功",
            f"「{name}」牌面样本已通过截图替换并保存。"
        )
        self._highlight_tile_cell(tile_id)

    def _build_capture_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        top = QHBoxLayout()
        self._btn_data_training = QPushButton("数据训练吧")
        self._btn_data_training.setFixedHeight(36)
        self._btn_data_training.setToolTip("从历史手牌 ROI 抽样 → 人工确认 → 加入 tile_samples_cleaned → 训练 HOG")
        self._btn_data_training.clicked.connect(self._open_roi_training)

        self._btn_discard_training = QPushButton("弃牌区域训练")
        self._btn_discard_training.setFixedHeight(36)
        self._btn_discard_training.setToolTip("从历史弃牌 ROI 抽样 → 人工确认 → 加入 tile_samples_discard_cleaned")
        self._btn_discard_training.clicked.connect(self._open_discard_roi_training)

        top.addStretch()
        top.addWidget(self._btn_data_training)
        top.addWidget(self._btn_discard_training)
        layout.addLayout(top)

        self._capture_panel = CapturePanel()
        self._capture_panel.start_requested.connect(self._start_capture)
        self._capture_panel.stop_requested.connect(self._stop_capture)
        layout.addWidget(self._capture_panel)
        return w

    def _build_battle_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self._battle_panel = BattlePanel(self._config)
        self._battle_panel.start_requested.connect(self._on_battle_start_requested)
        self._battle_panel.end_requested.connect(self._on_battle_end_requested)
        self._battle_panel.state_changed.connect(self._on_battle_state_changed)
        self._battle_panel.analysis_requested.connect(self._on_battle_analysis_requested)
        self._battle_panel.recognition_only_requested.connect(self._on_battle_recognition_only_requested)
        self._battle_panel.state_reanalyze_requested.connect(self._on_battle_state_reanalyze_requested)
        self._battle_panel.reanalyze_with_ai_requested.connect(self._on_battle_reanalyze_with_ai_requested)
        self._battle_panel.config_requested.connect(self._open_api_config_dialog)
        self._battle_panel.config_save_requested.connect(self._on_battle_config_save)
        self._battle_panel.tile_correction_requested.connect(self._on_battle_tile_correction)
        self._battle_panel.meld_correction_requested.connect(self._on_battle_meld_correction)
        layout.addWidget(self._battle_panel)
        return w

    def _build_region_tab(self) -> QWidget:
        self._region_panel = RegionDivisionPanel(self._config)
        self._region_panel.config_changed.connect(self._on_region_config_changed)
        return self._region_panel

    def _build_event_tab(self) -> QWidget:
        self._event_panel = EventCollectionPanel(self._config)
        return self._event_panel

    # ------------------------------------------------------------------ #
    #  区域选取                                                            #
    # ------------------------------------------------------------------ #

    def _show_region_selector(self):
        """隐藏主窗口后再显示区域选取覆盖层，避免主窗口出现在截图中。"""
        self.hide()
        QTimer.singleShot(250, self._region_selector.show)

    def _on_region_cancelled(self):
        self.show()
        self.raise_()
        self.statusBar().showMessage("区域选取已取消")

    def _on_region_selected(self, region: dict):
        self.show()
        self.raise_()
        gw = self._config.setdefault("game_window", {})
        gw["top"] = region["top"]
        gw["left"] = region["left"]
        gw["width"] = region["width"]
        gw["height"] = region["height"]
        self._layout_calc.update_window(
            region["top"], region["left"], region["width"], region["height"]
        )
        self._capture.update_region(self._layout_calc.window_region)
        self._update_region_status()
        self._save_config()
        self.statusBar().showMessage(
            f"已设置游戏窗口：{region['width']}×{region['height']} @ ({region['left']},{region['top']})"
        )

    def _update_region_status(self):
        gw = self._config.get("game_window", {})
        w, h = gw.get("width", 0), gw.get("height", 0)
        if w and h:
            self._region_status.setText(
                f"{w}×{h} @ ({gw.get('left', 0)}, {gw.get('top', 0)})"
            )
            self._region_status.setStyleSheet("color: #2d8a2d;")
        else:
            self._region_status.setText("未设置 — 请框选游戏窗口")
            self._region_status.setStyleSheet("color: #c00;")

    # ------------------------------------------------------------------ #
    #  标定                                                                #
    # ------------------------------------------------------------------ #

    def _open_calibration(self):
        wizard = CalibrationWizard(
            tile_recognizer=self._tile_rec,
            button_recognizer=self._btn_rec,
            tile_template_dir=template_dir("tiles"),
            button_template_dir=template_dir("buttons"),
            overlay_template_dir=template_dir("overlays"),
            parent=self,
        )
        wizard.calibration_complete.connect(self._on_calibration_done)
        wizard.exec()

    # ------------------------------------------------------------------ #
    #  牌面图鉴 — 一键截屏识别                                             #
    # ------------------------------------------------------------------ #

    def _on_quick_capture(self):
        """隐藏主窗口 → 静默截全屏 → 弹出覆盖层供用户框选一张牌。"""
        self.hide()
        QTimer.singleShot(250, self._do_quick_capture)

    def _do_quick_capture(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._tile_capture_selector.set_background_image(arr)
        self._tile_capture_selector.show()

    def _on_tile_capture_cancelled(self):
        self._tile_capture_selector.clear_background()
        self.show()
        self.raise_()
        self.statusBar().showMessage("截屏识别已取消")

    def _on_tile_capture_cropped(self, cropped: np.ndarray):
        """用户框选完成，自动匹配模板并高亮对应格子。"""
        self._tile_capture_selector.clear_background()
        self.show()
        self.raise_()

        result = self._tile_rec.match_tile(cropped) if self._tile_rec.loaded_tiles else None
        TILE_DISPLAY = {
            **{f"{i}m": f"{i}万" for i in range(1, 10)},
            **{f"{i}p": f"{i}筒" for i in range(1, 10)},
            **{f"{i}s": f"{i}条" for i in range(1, 10)},
            "1z": "东", "2z": "南", "3z": "西", "4z": "北",
            "5z": "中", "6z": "发", "7z": "白",
        }

        if result and result.tile_id:
            name = TILE_DISPLAY.get(result.tile_id, result.tile_id)
            self._highlight_tile_cell(result.tile_id)
            self.statusBar().showMessage(f"截屏识别：{name} ({result.tile_id}) 置信度 {result.confidence:.3f}")
            QMessageBox.information(
                self, "识别成功",
                f"识别结果：「{name}」({result.tile_id})\n置信度：{result.confidence:.3f}"
            )
        else:
            best_conf = result.confidence if result else 0.0
            self.statusBar().showMessage(f"截屏识别：未匹配 最佳置信度 {best_conf:.3f}")
            tip_extra = ""
            if not self._tile_rec.loaded_tiles:
                tip_extra = "\n\n提示：尚未收集任何牌面样本，请先通过「打开牌面收集向导」补充样本。"
            QMessageBox.information(
                self, "识别失败",
                f"未能匹配已知牌面样本。\n最佳置信度：{best_conf:.3f}\n\n"
                f"可能原因：\n· 牌面样本数量不足（当前 {len(self._tile_rec.loaded_tiles)} 种）\n"
                f"· 框选区域不够精确，包含多余背景\n· 该牌尚未收集牌面样本"
                f"{tip_extra}"
            )

    def _highlight_tile_cell(self, tile_id: str):
        """高亮牌面图鉴中的指定格子（2 秒后自动恢复）。"""
        cell = self._tile_cells.get(tile_id)
        if cell is None:
            return
        original_ss = cell.styleSheet()
        cell.setStyleSheet(
            "border:2px solid #ff8800; border-radius:4px; background:#fff3e0;"
        )
        QTimer.singleShot(2000, lambda ss=original_ss, c=cell: c.setStyleSheet(ss))

    def _on_calibration_done(self, tile_dir: str):
        # 重新加载牌面样本
        self._tile_rec.load_templates(tile_dir)
        self._refresh_tile_grid()
        self._refresh_template_status()
        self.statusBar().showMessage("牌面收集完成，样本已重新加载")

    # ------------------------------------------------------------------ #
    #  一键训练 HOG 模型                                                    #
    # ------------------------------------------------------------------ #

    def _on_train_hog(self):
        """启动后台训练线程。"""
        self._start_hog_training(confirm_incomplete=True)

    def _start_hog_training(self, confirm_incomplete: bool = True):
        """启动后台训练线程。"""
        data_root = data_path("data")
        cleaned_dir = os.path.join(data_root, "tile_samples_cleaned")
        raw_dir = os.path.join(data_root, "tile_samples")
        samples_dir = cleaned_dir if os.path.isdir(cleaned_dir) else raw_dir
        model_path = os.path.join(data_path(), "models", "tile_svm.xml")

        if not os.path.isdir(samples_dir):
            QMessageBox.warning(self, "训练失败", f"样本目录不存在：\n{samples_dir}")
            return

        # 检查是否有足够样本
        class_counts = _hog_sample_counts(samples_dir)
        n_classes = len(class_counts)
        if n_classes < 2:
            QMessageBox.warning(self, "训练失败", "样本类别不足，请先收集牌面样本。")
            return
        if confirm_incomplete and os.path.normcase(samples_dir) == os.path.normcase(cleaned_dir) and n_classes < 34:
            ret = QMessageBox.question(
                self,
                "样本不完整",
                f"当前将使用 data/tile_samples_cleaned 训练，但只有 {n_classes}/34 类、"
                f"{sum(class_counts.values())} 张样本。\n\n"
                "继续训练会覆盖当前 HOG 模型，未收集的牌种将无法由 HOG 识别。\n"
                "是否仍然继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        if os.path.normcase(samples_dir) == os.path.normcase(cleaned_dir):
            missing = [tid for tid in ALL_TILE_IDS if class_counts.get(tid, 0) <= 0]
            weak = {
                tid: class_counts.get(tid, 0)
                for tid in ALL_TILE_IDS
                if 0 < class_counts.get(tid, 0) < MIN_TRUSTED_SAMPLES_PER_CLASS
            }
            if missing or weak:
                weak_preview = ", ".join(f"{k}:{v}" for k, v in sorted(weak.items())[:12])
                missing_preview = ", ".join(missing[:12])
                QMessageBox.warning(
                    self,
                    "训练样本不足",
                    "当前 cleaned 训练集还不能生成可信 HOG 主判模型。\n\n"
                    f"可信训练要求：34 类齐全，且每类至少 {MIN_TRUSTED_SAMPLES_PER_CLASS} 张干净样本。\n"
                    f"缺失类别：{missing_preview or '无'}\n"
                    f"样本过少：{weak_preview or '无'}\n\n"
                    "本次不会覆盖模型。请继续用「数据训练吧」补齐少样本类别。",
                )
                return

        self._btn_train_hog.setEnabled(False)
        self._btn_train_hog.setText("训练中...")

        self.statusBar().showMessage(
            f"HOG training from {samples_dir}: {sum(class_counts.values())} samples, {n_classes} classes"
        )
        self._hog_train_thread = HOGTrainerThread(samples_dir, model_path, auto_params=False, parent=self)
        self._hog_train_thread.progress.connect(self._on_hog_train_progress)
        self._hog_train_thread.finished_ok.connect(self._on_hog_train_finished)
        self._hog_train_thread.finished_err.connect(self._on_hog_train_error)
        self._hog_train_thread.start()
        if hasattr(self, "_battle_panel"):
            self._battle_panel.set_training_in_progress()

    def _on_hog_train_progress(self, msg: str):
        self.statusBar().showMessage(msg)

    def _on_hog_train_finished(self, stats: dict):
        self._btn_train_hog.setEnabled(True)
        self._btn_train_hog.setText("🧠 一键训练HOG模型")
        self._hog_train_thread = None

        train_acc = stats.get("train_acc", 0.0) * 100
        n_samples = stats.get("n_samples", 0)
        n_classes = stats.get("n_classes", 0)
        class_counts = stats.get("class_counts", {})
        samples_dir = stats.get("samples_dir", "")

        # 原子替换模型文件（训练写临时文件，完成后一次性替换）
        model_path = os.path.join(data_path(), "models", "tile_svm.xml")
        temp_path = model_path + ".new"
        if os.path.exists(temp_path):
            os.replace(temp_path, model_path)

        # 重置 mtime 缓存，让下次识别强制重载新模型
        self._battle_service.invalidate_model_cache()

        # 重新加载 HOG 分类器
        if self._tile_rec._hog_clf is not None and self._tile_rec._hog_clf.is_ready:
            self._tile_rec._hog_clf.load(model_path)
        else:
            self._tile_rec._hog_clf = TileHOGClassifier(model_path)
        cleaned_dir = os.path.join(data_path("data"), "tile_samples_cleaned")
        if hasattr(self._tile_rec, "load_training_samples"):
            self._tile_rec.load_training_samples(cleaned_dir)
        hog_loaded = bool(self._tile_rec._hog_clf is not None and self._tile_rec._hog_clf.is_ready)
        hog_primary = bool(
            hog_loaded
            and self._tile_rec._hog_clf is not None
            and getattr(self._tile_rec._hog_clf, "is_trusted", False)
        )
        self._pipeline.clear_match_cache()

        self.statusBar().showMessage(
            f"HOG 模型训练完成：{n_classes} 类，{n_samples} 张，训练准确率 {train_acc:.1f}%，已加载={hog_loaded}，主判={hog_primary}"
        )

        train_ts = datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")
        if hasattr(self, "_battle_panel"):
            self._battle_panel.set_train_success_message(
                f"{train_ts} 训练结束  准确率 {train_acc:.1f}%  {n_classes}类/{n_samples}张"
            )

    def _on_hog_train_error(self, err: str):
        self._btn_train_hog.setEnabled(True)
        self._btn_train_hog.setText("🧠 一键训练HOG模型")
        self._hog_train_thread = None
        self.statusBar().showMessage(f"训练失败：{err}")
        QMessageBox.critical(self, "训练失败", f"HOG 模型训练出错：\n{err}")

    def _is_hog_training_running(self) -> bool:
        return self._hog_train_thread is not None and self._hog_train_thread.isRunning()

    def _collect_historical_roi_paths(self) -> list[str]:
        data_root = data_path("data")
        capture_interval = int(self._config.get("app", {}).get("capture_interval_ms", 500) or 500)
        paths = self._hand_region.collect_training_roi_paths(
            data_root,
            capture_interval,
            self._layout_calc,
            self._capture,
        )
        paths.extend(self._collect_battle_picture_roi_paths(data_root))
        return paths

    def _collect_battle_picture_roi_paths(self, data_root: str) -> list[str]:
        """Collect unprocessed individual tile PNGs saved during battle AI recognition."""
        pic_dir = os.path.join(data_root, "picture")
        pool_dir = os.path.join(data_root, "training_roi_pool")
        os.makedirs(pool_dir, exist_ok=True)
        processed_path = os.path.join(pool_dir, "processed_sources.json")
        try:
            with open(processed_path, "r", encoding="utf-8") as f:
                processed_sources = set(json.load(f))
        except (OSError, ValueError, TypeError):
            processed_sources = set()
        if not os.path.isdir(pic_dir):
            return []
        candidates: list[tuple[float, str]] = []
        try:
            pic_names = sorted(os.listdir(pic_dir))
        except OSError:
            return []
        for name in pic_names:
            if not (
                name.endswith("_picture_tile_request.png")
                or name.endswith("_picture_tile_response.png")
            ):
                continue
            source_key = f"battle_picture:{name}"
            if source_key in processed_sources:
                continue
            path = os.path.join(pic_dir, name)
            try:
                modified_at = os.path.getmtime(path)
            except OSError:
                continue
            img = _read_image(path)
            if img is None:
                continue
            ok, _clean_img, _reason = _prepare_trainable_roi_image(img)
            if not ok:
                continue
            candidates.append((modified_at, path))
        if not candidates:
            return []

        candidates.sort(key=lambda item: item[0])
        latest_ts = candidates[-1][0]
        batch_window_seconds = 20.0
        latest_batch = [
            path
            for modified_at, path in candidates
            if latest_ts - modified_at <= batch_window_seconds
        ]
        return latest_batch or [candidates[-1][1]]

    def _mark_training_sources_processed(self, sources: set[str]) -> None:
        if not sources:
            return
        pool_dir = os.path.join(data_path("data"), "training_roi_pool")
        os.makedirs(pool_dir, exist_ok=True)
        processed_path = os.path.join(pool_dir, "processed_sources.json")
        try:
            with open(processed_path, "r", encoding="utf-8") as f:
                processed = set(json.load(f))
        except (OSError, ValueError, TypeError):
            processed = set()
        processed.update(sources)
        with open(processed_path, "w", encoding="utf-8") as f:
            json.dump(sorted(processed), f, ensure_ascii=False, indent=2)

    def _open_roi_training(self):
        roi_paths = self._collect_historical_roi_paths()
        if not roi_paths:
            pool_dir = os.path.join(data_path("data"), "training_roi_pool")
            recognition_dir = os.path.join(data_path("data"), "recognition")
            picture_dir = os.path.join(data_path("data"), "picture")
            QMessageBox.information(
                self,
                "数据训练吧",
                "没有找到可处理的训练 ROI。\n"
                f"训练池位置：{pool_dir}\n"
                f"请先运行识别生成 {recognition_dir}\\roi_*.png，"
                f"或先在正式战斗里跑一轮以生成 {picture_dir}\\*.png。",
            )
            return
        dlg = RoiTrainingDialog(roi_paths, self._tile_rec, self)
        dlg.setWindowTitle(f"数据训练吧 - 最新session抽样 {len(roi_paths)} 张")
        dlg.exec()
        self._mark_training_sources_processed(dlg.processed_sources)
        if dlg.closed_without_training:
            self.statusBar().showMessage("数据训练吧：已关闭并清空本轮待处理 ROI")
            return
        if dlg.accepted_count <= 0:
            self.statusBar().showMessage("数据训练吧：本次未加入新样本")
            return
        self._pipeline.clear_match_cache()
        self._refresh_tile_grid()
        self._refresh_template_status()
        self.statusBar().showMessage(f"数据训练吧：已加入 {dlg.accepted_count} 张样本，开始训练 HOG")
        self._start_hog_training(confirm_incomplete=False)

    def _collect_discard_roi_paths(self) -> list[str]:
        """从最新 session 的 discard_recognition/ 目录抽样弃牌 ROI 路径。"""
        data_root = data_path("data")
        pool_dir = os.path.join(data_root, "training_roi_pool_discard")
        os.makedirs(pool_dir, exist_ok=True)
        processed_path = os.path.join(pool_dir, "processed_sources.json")
        try:
            with open(processed_path, "r", encoding="utf-8") as f:
                processed_sources = set(json.load(f))
        except (OSError, ValueError, TypeError):
            processed_sources = set()

        # 清空上次遗留的 pool 图片
        for name in os.listdir(pool_dir):
            p = os.path.join(pool_dir, name)
            if os.path.isfile(p) and name.endswith(".png") and name.startswith("roi_"):
                try:
                    os.remove(p)
                except OSError:
                    pass

        capture_interval = int(self._config.get("app", {}).get("capture_interval_ms", 500) or 500)
        frames_per_batch = max(1, int(round(10000 / max(1, capture_interval))))
        copied: list[str] = []
        sessions = GameSession.list_sessions(data_root)
        if not sessions:
            return []

        for session_name in sessions[:1]:
            rec_dir = os.path.join(data_root, session_name, "discard_recognition")
            if not os.path.isdir(rec_dir):
                continue
            frame_names = [
                name for name in sorted(os.listdir(rec_dir))
                if name.startswith("frame_") and os.path.isdir(os.path.join(rec_dir, name))
            ]
            selected_frames = []
            for name in frame_names:
                try:
                    frame_index = int(name.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                if frame_index % frames_per_batch == 0:
                    selected_frames.append(name)
            if not selected_frames and frame_names:
                selected_frames = [frame_names[0]]

            for frame_name in selected_frames:
                source_key = f"{session_name}:{frame_name}"
                if source_key in processed_sources:
                    continue
                frame_dir = os.path.join(rec_dir, frame_name)
                for fname in sorted(os.listdir(frame_dir)):
                    if not fname.startswith("roi_") or not fname.endswith(".png"):
                        continue
                    if fname.endswith("_annotated.png"):
                        continue
                    src = os.path.join(frame_dir, fname)
                    img = cv2.imread(src)
                    base_name = os.path.splitext(fname)[0]
                    ok, clean_img, _clean_reason = prepare_trainable_discard_roi_image(img)
                    pool_images: list[np.ndarray] = []
                    if ok and clean_img is not None:
                        pool_images.append(clean_img)
                    else:
                        crops, _rects, _reason = extract_discard_tile_candidates(img, max_tiles=1)
                        for crop in crops:
                            ok, clean_img, _clean_reason = prepare_trainable_discard_roi_image(crop)
                            if ok and clean_img is not None:
                                pool_images.append(clean_img)
                    if not pool_images:
                        continue
                    for crop_idx, crop in enumerate(pool_images):
                        dst = os.path.join(
                            pool_dir,
                            f"roi_{session_name}_{frame_name}_{base_name}_tile{crop_idx}.png",
                        )
                        if not os.path.exists(dst):
                            try:
                                cv2.imwrite(dst, clean_img)
                            except Exception:
                                continue
                        copied.append(dst)
        return sorted(copied)

    def _mark_discard_training_sources_processed(self, sources: set[str]) -> None:
        if not sources:
            return
        pool_dir = os.path.join(data_path("data"), "training_roi_pool_discard")
        os.makedirs(pool_dir, exist_ok=True)
        processed_path = os.path.join(pool_dir, "processed_sources.json")
        try:
            with open(processed_path, "r", encoding="utf-8") as f:
                processed = set(json.load(f))
        except (OSError, ValueError, TypeError):
            processed = set()
        processed.update(sources)
        with open(processed_path, "w", encoding="utf-8") as f:
            json.dump(sorted(processed), f, ensure_ascii=False, indent=2)

    def _open_discard_roi_training(self):
        roi_paths = self._collect_discard_roi_paths()
        if not roi_paths:
            pool_dir = os.path.join(data_path("data"), "training_roi_pool_discard")
            recognition_dir = os.path.join(data_path("data"), "discard_recognition")
            QMessageBox.information(
                self,
                "弃牌区域训练",
                "没有找到可处理的弃牌训练 ROI。\n"
                f"训练池位置：{pool_dir}\n"
                f"请先运行识别以生成 {recognition_dir}\\roi_*.png。",
            )
            return
        dlg = RoiTrainingDialog(
            roi_paths,
            self._discard_rec.inner_recognizer,
            self,
            save_dir=self._discard_rec.discard_samples_dir,
            prepare_fn=prepare_trainable_discard_roi_image,
        )
        dlg.setWindowTitle(f"弃牌区域训练 - 抽样 {len(roi_paths)} 张")
        dlg.exec()
        self._mark_discard_training_sources_processed(dlg.processed_sources)
        if dlg.closed_without_training:
            self.statusBar().showMessage("弃牌区域训练：已关闭")
            return
        if dlg.accepted_count > 0:
            self._discard_rec.reload_samples()
            self._pipeline.clear_match_cache()
            self.statusBar().showMessage(
                f"弃牌区域训练：已加入 {dlg.accepted_count} 张样本，弃牌识别器已热重载"
            )
        else:
            self.statusBar().showMessage("弃牌区域训练：本次未加入新样本")

    # ------------------------------------------------------------------ #
    #  识别运行                                                            #
    # ------------------------------------------------------------------ #

    def _start_capture(self, interval_ms: int):
        gw = self._config.get("game_window", {})
        if not gw.get("width"):
            QMessageBox.warning(self, "提示", "请先在「游戏窗口」中框选游戏窗口")
            self._capture_panel.force_stop()
            return
        if len(self._tile_rec.loaded_tiles) < 10:
            QMessageBox.warning(self, "提示", "牌面样本不足，请先完成牌面收集（至少10种牌）")
            self._capture_panel.force_stop()
            return

        # 高频实时识别默认关闭逐帧 debug 落盘；ROI/关键帧由 pipeline 按抽样保存。
        self._pipeline.disable_debug()

        # 新建 session
        output = data_path(self._config.get("app", {}).get("output_dir", "data"))
        self._session = GameSession(output, self._config)
        self._pipeline.set_session(self._session)
        self._capture_worker = CaptureWorkerThread(self._pipeline, interval_ms, self)
        self._capture_worker.frame_ready.connect(self._on_frame)
        self._capture_worker.failed.connect(self._on_capture_worker_error)
        self._capture_worker.finished.connect(self._on_capture_worker_finished)
        self._capture_worker.start()
        self.statusBar().showMessage(f"识别已启动，间隔 {interval_ms}ms | 后台识别，UI 不阻塞")

        # 可选：识别运行时最小化窗口，避免遮挡游戏画面。
        if self._capture_panel.hide_on_start():
            self.showMinimized()

    def _stop_capture(self):
        if self._capture_worker and self._capture_worker.isRunning():
            self._capture_worker.request_stop()
            self._capture_worker.wait(3000)
        self._capture_worker = None
        self._pipeline.stop()
        self._pipeline.disable_debug()
        session = self._session
        if self._session:
            frames = self._session.frame_count
            path = self._session.frames_path
            keyframes_dir = self._session.keyframes_dir
            keyframe_count = self._session.keyframe_count
            self._session.close()
            self._session = None
            if frames <= 0:
                self.statusBar().showMessage(f"已停止，但本次没有保存任何帧 → {path}")
                QMessageBox.warning(
                    self,
                    "识别未产出帧",
                    "本次识别 session 没有写入任何帧数据。\n"
                    f"frames.jsonl: {path}\n"
                    f"keyframes: {keyframes_dir}\n\n"
                    "这通常表示识别线程启动后没有真正跑到一帧。\n"
                    "下次如果再次出现，请保留这次 session 目录，我继续顺着线程启动链路查。",
                )
            else:
                self.statusBar().showMessage(f"已停止，共保存 {frames} 帧 → {path}")

        # 如果开始时选择了隐藏/最小化，停止后恢复窗口。
        if self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()

        # 提示关键帧保存位置
        if session and keyframe_count > 0:
            kdir = keyframes_dir
            kcount = keyframe_count
            QMessageBox.information(
                self, "识别完成",
                f"本次识别共保存 {kcount} 张关键帧\n"
                f"保存位置: {kdir}\n\n"
                f"每 10 帧保存一张带标注的截图，"
                f"绿色框=手牌区域，蓝色=弃牌，白色=剩余牌数，橙色=决策按钮"
            )

    def _on_frame(self, state: GameState):
        self._capture_panel.on_frame(state)

    def _on_battle_start_requested(self):
        # 如果已有战斗 session，先关闭（防止重复开始）
        if getattr(self, "_battle_session", None) is not None:
            try:
                self._battle_session.close()
            except Exception:
                pass
            self._battle_session = None
            self._battle_service.set_session(None)

        # 新建 battle session（独立于采集识别的那个 session）
        output = data_path("data")
        self._battle_session = GameSession(output, self._config)
        self._battle_service.set_session(self._battle_session)
        self._battle_panel.set_game_started(True)
        self.statusBar().showMessage(f"正式战斗：已启动，session={self._battle_session.session_id}")

    @staticmethod
    def _ask_game_result() -> str:
        """弹出胜负确认对话框，返回 'win' / 'lose' / 'unknown'。"""
        dlg = QMessageBox()
        dlg.setWindowTitle("本局结果")
        dlg.setText("本局对局结果如何？")
        btn_win = dlg.addButton("赢了", QMessageBox.ButtonRole.AcceptRole)
        btn_lose = dlg.addButton("输了", QMessageBox.ButtonRole.DestructiveRole)
        dlg.addButton("跳过不记录", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked is btn_win:
            return "win"
        if clicked is btn_lose:
            return "lose"
        return "unknown"

    def _on_battle_end_requested(self):
        if self._battle_worker and self._battle_worker.isRunning():
            self.statusBar().showMessage("正式战斗：请等待当前分析完成后再结束游戏")
            return
        game_result = self._ask_game_result()
        state = self._battle_panel.current_state()
        state.append_operation("end_game", {"note": "reset round context", "result": game_result})
        self._battle_service.persist_round_event(state, "end_game", {"note": "reset round context", "result": game_result})
        state.reset_round()
        self._battle_panel.set_state(state)
        self._battle_panel.clear_round_feedback()
        self._battle_panel.clear_error()

        # 关闭 battle session
        if getattr(self, "_battle_session", None) is not None:
            try:
                self._battle_session.close()
            except Exception:
                pass
            self._battle_session = None
            self._battle_service.set_session(None)

        self._battle_panel.set_game_started(False)
        self.statusBar().showMessage("正式战斗：本轮对话与牌局数据已重置，session 已保存")

    def _on_battle_state_changed(self, _state: BattleState):
        self._config.setdefault("battle", {})["ai_recognition_enabled"] = bool(
            self._battle_panel.current_state().ai_recognition_enabled
        )
        self._config.setdefault("vision", {})["provider"] = str(
            self._battle_panel.current_state().vision_provider or "auto"
        )
        self._battle_service._config = self._config
        self._save_config()
        self._battle_panel.clear_error()

    _MODE_BUSY_MSG = {
        "full": "分析中...",
        "recognition_only": "正在重新识别牌区...",
        "state_only": "正在分析对策...",
        "state_with_ai": "正在重新分析（跳过识别）...",
    }

    def _start_battle_worker(self, trigger_reason: str, mode: str = "full") -> None:
        if self._battle_worker and self._battle_worker.isRunning():
            self.statusBar().showMessage("正式战斗：上一轮分析仍在进行，请稍候")
            return
        state = self._battle_panel.current_state()
        self._battle_panel.clear_error()
        busy_msg = self._MODE_BUSY_MSG.get(mode, "分析中...")
        self._battle_panel.set_busy(True, busy_msg)
        self._battle_analysis_started_at = time.perf_counter()
        self._battle_worker = BattleAnalysisThread(
            self._battle_service,
            state,
            trigger_reason,
            self,
            mode=mode,
        )
        uses_ai = mode in ("full", "state_with_ai") or trigger_reason == "start"
        if uses_ai:
            self._battle_panel.clear_stream_buffer()
        self._battle_worker.stream_chunk.connect(self._battle_panel.append_stream_chunk)
        self._battle_worker.finished_ok.connect(self._on_battle_analysis_finished)
        self._battle_worker.finished_err.connect(self._on_battle_analysis_failed)
        self._battle_worker.finished.connect(self._on_battle_worker_finished)
        self._battle_worker.start()

    def _on_battle_analysis_requested(self, trigger_reason: str):
        self._start_battle_worker(trigger_reason, mode="full")

    def _on_battle_recognition_only_requested(self, trigger_reason: str):
        self._start_battle_worker(trigger_reason, mode="recognition_only")

    def _on_battle_state_reanalyze_requested(self, trigger_reason: str):
        self._start_battle_worker(trigger_reason, mode="state_only")

    def _on_battle_reanalyze_with_ai_requested(self, trigger_reason: str):
        self._start_battle_worker(trigger_reason, mode="state_with_ai")

    def _on_battle_analysis_finished(self, state: BattleState, advice: BattleAdvice):
        state.append_operation(
            "analysis_success",
            {
                "trigger_reason": state.last_trigger_reason,
                "recommended_discard": advice.recommended_discard,
                "recognition_duration_ms": state.last_recognition_duration_ms,
                "advice_duration_ms": state.last_advice_duration_ms,
                "duration_ms": state.last_analysis_duration_ms,
            },
        )
        self._battle_panel.set_state(state)
        self._battle_panel.set_advice(advice)
        self._battle_panel.set_busy(False, "空闲")
        self.statusBar().showMessage(
            f"正式战斗：分析完成，推荐 {advice.recommended_discard or '--'}"
        )

    def _on_battle_analysis_failed(self, err: str):
        state = self._battle_panel.current_state()
        if self._battle_analysis_started_at is not None:
            state.last_analysis_duration_ms = max(
                1,
                int(math.ceil((time.perf_counter() - self._battle_analysis_started_at) * 1000)),
            )
        state.append_operation("analysis_failed", {"error": err})
        self._battle_panel.set_state(state)
        self._battle_panel.set_advice(BattleAdvice())
        self._battle_panel.set_busy(False, "失败")
        self._battle_panel.set_error(err)
        self.statusBar().showMessage(f"正式战斗：分析失败 - {err}")

    def _on_battle_worker_finished(self):
        if self._battle_worker and not self._battle_worker.isRunning():
            self._battle_worker = None
        self._battle_analysis_started_at = None

    def _on_battle_tile_correction(self, tile_index: int, correct_tile_id: str) -> None:
        """用户在手牌区点击纠正了一张牌：保存 ROI 到训练集并后台重训 HOG。"""
        rois = getattr(self._battle_service, "_last_match_rois", [])
        if tile_index >= len(rois):
            self.statusBar().showMessage(f"纠错：未找到第 {tile_index + 1} 张牌的 ROI，跳过保存")
            return
        roi = rois[tile_index]
        if roi is None or roi.size == 0:
            self.statusBar().showMessage(f"纠错：第 {tile_index + 1} 张牌 ROI 为空，跳过保存")
            return

        from vision.hand_region_module import prepare_trainable_hand_roi_image
        ok, clean_img, reason = prepare_trainable_hand_roi_image(roi)
        save_img = clean_img if ok and clean_img is not None else roi

        dst_dir = os.path.join(data_path("data"), "tile_samples_cleaned", correct_tile_id)
        os.makedirs(dst_dir, exist_ok=True)
        filename = f"battle_{time.strftime('%Y%m%d_%H%M%S')}_{tile_index:02d}.png"
        dst = os.path.join(dst_dir, filename)
        data = cv2.imencode(".png", save_img)[1].tobytes()
        with open(dst, "wb") as _f:
            _f.write(data)

        if hasattr(self._tile_rec, "add_training_sample"):
            self._tile_rec.add_training_sample(save_img, correct_tile_id, source=dst)
        self._pipeline.clear_match_cache()

        self.statusBar().showMessage(f"纠错：已保存 {correct_tile_id} 样本，开始后台重训 HOG…")
        self._start_hog_training(confirm_incomplete=False)

    def _on_battle_meld_correction(self, flat_tile_index: int, correct_tile_id: str) -> None:
        """用户在副露区纠正了一张牌：保存 ROI 到训练集并后台重训 HOG。"""
        rois = getattr(self._battle_service, "_last_meld_rois", [])
        if flat_tile_index >= len(rois):
            self.statusBar().showMessage(f"副露纠错：未找到第 {flat_tile_index + 1} 张牌的 ROI，跳过保存")
            return
        roi = rois[flat_tile_index]
        if roi is None or roi.size == 0:
            self.statusBar().showMessage(f"副露纠错：第 {flat_tile_index + 1} 张牌 ROI 为空，跳过保存")
            return

        from vision.hand_region_module import prepare_trainable_hand_roi_image
        ok, clean_img, reason = prepare_trainable_hand_roi_image(roi)
        save_img = clean_img if ok and clean_img is not None else roi

        dst_dir = os.path.join(data_path("data"), "tile_samples_cleaned", correct_tile_id)
        os.makedirs(dst_dir, exist_ok=True)
        filename = f"meld_{time.strftime('%Y%m%d_%H%M%S')}_{flat_tile_index:02d}.png"
        dst = os.path.join(dst_dir, filename)
        data = cv2.imencode(".png", save_img)[1].tobytes()
        with open(dst, "wb") as _f:
            _f.write(data)

        if hasattr(self._tile_rec, "add_training_sample"):
            self._tile_rec.add_training_sample(save_img, correct_tile_id, source=dst)
        self._pipeline.clear_match_cache()

        self.statusBar().showMessage(f"副露纠错：已保存 {correct_tile_id} 样本，开始后台重训 HOG…")
        self._start_hog_training(confirm_incomplete=False)

    def _open_api_config_dialog(self):
        dlg = ApiConfigDialog(self._config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._config = _ensure_battle_config_defaults(dlg.updated_config())
        self._battle_service._config = self._config
        self._battle_panel.apply_config(self._config)
        self._save_config()
        self.statusBar().showMessage("API 配置已保存")

    def _on_capture_worker_error(self, err: str):
        self.statusBar().showMessage(f"识别线程出错：{err}")
        QMessageBox.critical(self, "识别出错", err)
        self._capture_panel.force_stop()

    def _on_capture_worker_finished(self):
        if self._capture_worker and not self._capture_worker.isRunning():
            self._capture_worker = None

    def _on_region_config_changed(self):
        gw = self._config.get("game_window", {})
        self._layout_calc = LayoutCalculator(self._config)
        if gw.get("width") and gw.get("height"):
            self._layout_calc.update_window(
                gw.get("top", 0), gw.get("left", 0), gw["width"], gw["height"]
            )
        self._pipeline._layout = self._layout_calc
        self._battle_service._layout = self._layout_calc
        self.statusBar().showMessage("区域划分已更新，实时识别将使用新的 layout 配置")

    # ------------------------------------------------------------------ #
    #  辅助                                                                #
    # ------------------------------------------------------------------ #

    def _get_template_status(self) -> str:
        tiles = len(self._tile_rec.loaded_tiles)
        has_btn = self._btn_rec.has_button_templates
        has_ov = self._btn_rec.has_overlay_templates
        return (
            f"牌面样本：{tiles}/34 种   "
            f"决策按钮：{'✓' if has_btn else '未标定'}   "
            f"覆盖层：{'✓' if has_ov else '未标定'}"
        )

    def _refresh_template_status(self):
        self._tmpl_status.setText(self._get_template_status())

    def _on_battle_config_save(self, updates: dict):
        self._config.update(updates)
        self._save_config()

    def _save_config(self):
        """将当前 config 写回 settings.yaml。"""
        config_path = data_path("config") + os.sep + "settings.yaml"
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

    def closeEvent(self, event: QCloseEvent):
        if self._capture_worker and self._capture_worker.isRunning():
            self._capture_worker.request_stop()
            self._capture_worker.wait(3000)
        if self._battle_worker and self._battle_worker.isRunning():
            self._battle_worker.wait(3000)
        self._pipeline.stop()
        if self._session:
            self._session.close()
        _cleanup_debug_dir(retain_hours=24)
        event.accept()
