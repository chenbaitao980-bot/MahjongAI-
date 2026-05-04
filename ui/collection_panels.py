from __future__ import annotations

import json
import os
from datetime import datetime

import cv2
import mss
import numpy as np
import yaml

from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
    QComboBox, QFileDialog, QMessageBox, QTextEdit, QLineEdit,
)

from ui.calibration_canvas import CalibrationCanvas
from ui.region_selector import RegionSelectorOverlay
from utils.paths import data_path


def _app_data_path(*parts: str) -> str:
    """Return the app data directory used for sessions and collected samples."""
    base = data_path("data")
    path = os.path.join(base, *parts) if parts else base
    last = parts[-1] if parts else ""
    if os.path.splitext(last)[1]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    else:
        os.makedirs(path, exist_ok=True)
    return path


REGION_DEFS = [
    ("self_hand", "自家手牌区", ("self_hand",)),
    ("discard.self", "自家弃牌区", ("discard", "self")),
    ("discard.right", "右家弃牌区", ("discard", "right")),
    ("discard.across", "对家弃牌区", ("discard", "across")),
    ("discard.left", "左家弃牌区", ("discard", "left")),
    ("remaining_tiles", "剩余牌数区", ("remaining_tiles",)),
    ("decision_buttons", "决策按钮区", ("decision_buttons",)),
    ("game_overlay", "结算/流局覆盖层", ("game_overlay",)),
]

REGION_COLORS = {
    "self_hand": QColor(0, 220, 80),
    "discard.self": QColor(0, 120, 255),
    "discard.right": QColor(255, 210, 0),
    "discard.across": QColor(0, 220, 220),
    "discard.left": QColor(255, 0, 220),
    "remaining_tiles": QColor(255, 255, 255),
    "decision_buttons": QColor(255, 140, 0),
    "game_overlay": QColor(220, 80, 255),
}

EVENT_TYPES = [
    ("game_start", "开局"),
    ("draw", "摸牌"),
    ("discard", "出牌"),
    ("chi", "吃"),
    ("peng", "碰"),
    ("gang", "杠"),
    ("hu", "胡"),
    ("pass", "过"),
    ("decision_prompt", "决策按钮出现"),
    ("remaining_changed", "剩余牌数变化"),
    ("shengpai", "生牌阶段"),
    ("liuju", "流局"),
    ("hupai_result", "胡牌结算"),
]


def _cv_to_pixmap(img: np.ndarray, max_w: int, max_h: int) -> QPixmap:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg).scaled(
        max(max_w, 1), max(max_h, 1),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _capture_region(region: dict) -> np.ndarray | None:
    if not region.get("width") or not region.get("height"):
        return None
    with mss.mss() as sct:
        shot = sct.grab({
            "top": int(region.get("top", 0)),
            "left": int(region.get("left", 0)),
            "width": int(region["width"]),
            "height": int(region["height"]),
        })
        arr = np.frombuffer(shot.raw, dtype=np.uint8)
        return arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()


def _hide_window_for_capture(widget: QWidget) -> QWidget:
    window = widget.window()
    window.hide()
    return window


def _restore_window_after_capture(window: QWidget) -> None:
    window.show()
    window.raise_()
    window.activateWindow()


class RegionDivisionPanel(QWidget):
    """独立区域划分：把视觉层需要的所有区域统一写入 layout 配置。"""

    config_changed = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._screenshot: np.ndarray | None = None
        self._selected_rect: QRect | None = None
        self._hidden_window: QWidget | None = None
        self._overlay = RegionSelectorOverlay()
        self._overlay.cropped_image.connect(self._on_manual_capture_cropped)
        self._overlay.cancelled.connect(self._on_manual_capture_cancelled)
        self._setup_ui()
        self._load_reference_image()
        self._refresh_summary()

    def _setup_ui(self):
        root = QVBoxLayout(self)

        desc = QLabel(
            "<b>区域划分</b> — 独立维护手牌、弃牌、剩余牌、决策按钮、结算覆盖层等识别区域。"
            "这些区域会写入 settings.yaml，供实时识别和事件推断共用。"
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        toolbar = QHBoxLayout()
        self._btn_capture = QPushButton("手动截取画面")
        self._btn_capture.clicked.connect(self._capture_game_window)
        toolbar.addWidget(self._btn_capture)

        self._btn_load = QPushButton("从文件加载...")
        self._btn_load.clicked.connect(self._load_file)
        toolbar.addWidget(self._btn_load)

        toolbar.addWidget(QLabel("当前区域："))
        self._region_combo = QComboBox()
        for key, label, _ in REGION_DEFS:
            self._region_combo.addItem(f"{label} ({key})", key)
        self._region_combo.currentIndexChanged.connect(self._draw_saved_regions)
        toolbar.addWidget(self._region_combo)

        self._btn_save = QPushButton("保存选区")
        self._btn_save.clicked.connect(self._save_selected_region)
        toolbar.addWidget(self._btn_save)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self._canvas = CalibrationCanvas()
        self._canvas.set_mode("select")
        self._canvas.region_selected.connect(self._on_region_selected)
        root.addWidget(self._canvas, stretch=3)

        bottom = QHBoxLayout()
        status_box = QGroupBox("当前选区")
        status_layout = QVBoxLayout(status_box)
        self._status = QLabel("请先截取或加载一张游戏画面，然后在图上框选区域")
        self._status.setWordWrap(True)
        status_layout.addWidget(self._status)
        bottom.addWidget(status_box, stretch=1)

        summary_box = QGroupBox("已保存区域")
        summary_layout = QVBoxLayout(summary_box)
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setMaximumHeight(150)
        summary_layout.addWidget(self._summary)
        bottom.addWidget(summary_box, stretch=1)
        root.addLayout(bottom)

    def _capture_game_window(self):
        self._status.setText("正在隐藏 AI 窗口，请在全屏画面中手动框选游戏区域...")
        self._hidden_window = _hide_window_for_capture(self)
        QTimer.singleShot(350, self._show_manual_capture_overlay)

    def _show_manual_capture_overlay(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._overlay.set_background_image(arr)
        self._overlay.show()

    def _on_manual_capture_cancelled(self):
        self._overlay.clear_background()
        if self._hidden_window is not None:
            _restore_window_after_capture(self._hidden_window)
            self._hidden_window = None
        self._status.setText("手动截取已取消")

    def _on_manual_capture_cropped(self, img: np.ndarray):
        self._overlay.clear_background()
        if self._hidden_window is not None:
            _restore_window_after_capture(self._hidden_window)
            self._hidden_window = None
        if img is None:
            QMessageBox.warning(self, "提示", "未截取到画面")
            return
        self._set_screenshot(img, "已手动截取画面")

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择游戏截图", "", "图片 (*.png *.jpg *.bmp)")
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.warning(self, "错误", "无法读取图片")
            return
        self._set_screenshot(img, f"已加载 {os.path.basename(path)}")

    def _set_screenshot(self, img: np.ndarray, message: str):
        self._screenshot = img
        self._selected_rect = None
        self._canvas.set_image(img)
        self._canvas.set_mode("select")
        self._save_reference_image(img)
        self._draw_saved_regions()
        self._status.setText(f"{message}，请框选要保存的区域")

    def _save_reference_image(self, img: np.ndarray):
        ref_dir = _app_data_path("layout_reference")
        ref_path = os.path.join(ref_dir, "current.png")
        cv2.imwrite(ref_path, img)
        self._config.setdefault("layout_reference", {})["image"] = ref_path
        self._save_config()

    def _load_reference_image(self):
        ref_path = self._config.get("layout_reference", {}).get("image")
        if not ref_path:
            ref_path = _app_data_path("layout_reference", "current.png")
        if not os.path.isfile(ref_path):
            return
        img = cv2.imread(ref_path)
        if img is None:
            return
        self._screenshot = img
        self._selected_rect = None
        self._canvas.set_image(img)
        self._canvas.set_mode("select")
        self._draw_saved_regions()
        self._status.setText(f"已加载上次区域划分底图：{os.path.basename(ref_path)}")

    def _on_region_selected(self, rect: QRect):
        if self._screenshot is None:
            return
        img_h, img_w = self._screenshot.shape[:2]
        x = max(0, min(rect.x(), img_w - 1))
        y = max(0, min(rect.y(), img_h - 1))
        w = min(rect.width(), img_w - x)
        h = min(rect.height(), img_h - y)
        self._selected_rect = QRect(x, y, w, h)
        self._status.setText(f"已选择：({x},{y}) {w}x{h}，点击「保存选区」写入当前区域")

    def _save_selected_region(self):
        if self._screenshot is None or self._selected_rect is None:
            QMessageBox.information(self, "提示", "请先在截图上框选一个区域")
            return

        key = self._region_combo.currentData()
        region_def = next((item for item in REGION_DEFS if item[0] == key), None)
        if region_def is None:
            return

        img_h, img_w = self._screenshot.shape[:2]
        r = self._selected_rect
        values = {
            "x": round(r.x() / img_w, 6),
            "y": round(r.y() / img_h, 6),
            "w": round(r.width() / img_w, 6),
            "h": round(r.height() / img_h, 6),
        }

        node = self._config.setdefault("layout", {})
        path = region_def[2]
        for part in path[:-1]:
            node = node.setdefault(part, {})
        existing = node.setdefault(path[-1], {})
        existing.update(values)

        self._save_config()
        self._refresh_summary()
        self._draw_saved_regions()
        self.config_changed.emit()
        self._status.setText(f"已保存「{region_def[1]}」：{values}")

    def _refresh_summary(self):
        layout = self._config.get("layout", {})
        lines = []
        for key, label, path in REGION_DEFS:
            node = layout
            for part in path:
                node = node.get(part, {}) if isinstance(node, dict) else {}
            if all(k in node for k in ("x", "y", "w", "h")):
                lines.append(
                    f"{label:<8} x={node['x']:.3f} y={node['y']:.3f} "
                    f"w={node['w']:.3f} h={node['h']:.3f}"
                )
            else:
                lines.append(f"{label:<8} 未设置")
        self._summary.setPlainText("\n".join(lines))

    def _draw_saved_regions(self):
        if self._screenshot is None:
            return
        img_h, img_w = self._screenshot.shape[:2]
        layout = self._config.get("layout", {})
        regions = []
        current_key = self._region_combo.currentData()
        for key, label, path in REGION_DEFS:
            if key != current_key:
                continue
            node = layout
            for part in path:
                node = node.get(part, {}) if isinstance(node, dict) else {}
            if not all(k in node for k in ("x", "y", "w", "h")):
                continue
            rect = QRect(
                round(float(node["x"]) * img_w),
                round(float(node["y"]) * img_h),
                round(float(node["w"]) * img_w),
                round(float(node["h"]) * img_h),
            )
            regions.append((rect, label, REGION_COLORS.get(key, QColor(255, 80, 80))))
        self._canvas.set_regions(regions)

    def _save_config(self):
        config_path = os.path.join(data_path("config"), "settings.yaml")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)


class EventCollectionPanel(QWidget):
    """事件收集：按事件类型保存截图/局部裁剪，供后续训练和规则验证使用。"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._screenshot: np.ndarray | None = None
        self._crop: np.ndarray | None = None
        self._crop_rect: QRect | None = None
        self._hidden_window: QWidget | None = None
        self._overlay = RegionSelectorOverlay()
        self._overlay.cropped_image.connect(self._on_manual_capture_cropped)
        self._overlay.cancelled.connect(self._on_manual_capture_cancelled)
        self._setup_ui()
        self._load_reference_image()
        self._refresh_sample_status()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        desc = QLabel(
            "<b>事件收集</b> — 将开局、摸牌、出牌、吃碰杠胡、按钮出现、流局/结算等画面按类型保存。"
            "这些样本用于补齐视觉层事件识别和对局状态机。"
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        toolbar = QHBoxLayout()
        self._btn_capture = QPushButton("手动截取画面")
        self._btn_capture.clicked.connect(self._capture_game_window)
        toolbar.addWidget(self._btn_capture)

        self._btn_load = QPushButton("从文件加载...")
        self._btn_load.clicked.connect(self._load_file)
        toolbar.addWidget(self._btn_load)

        toolbar.addWidget(QLabel("事件类型："))
        self._event_combo = QComboBox()
        for event_id, label in EVENT_TYPES:
            self._event_combo.addItem(f"{label} ({event_id})", event_id)
        self._event_combo.currentIndexChanged.connect(self._on_event_type_changed)
        toolbar.addWidget(self._event_combo)

        self._btn_save = QPushButton("保存事件样本")
        self._btn_save.clicked.connect(self._save_event_sample)
        toolbar.addWidget(self._btn_save)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self._canvas = CalibrationCanvas()
        self._canvas.set_mode("select")
        self._canvas.region_selected.connect(self._on_region_selected)
        root.addWidget(self._canvas, stretch=3)

        info_row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("备注："))
        self._note = QLineEdit()
        self._note.setPlaceholderText("例如：右家打出九筒 / 胡牌按钮出现 / 剩余102张")
        left.addWidget(self._note)
        self._status = QLabel("先截取或加载画面；可直接保存整张，也可框选关键区域后保存")
        self._status.setWordWrap(True)
        left.addWidget(self._status)
        info_row.addLayout(left, stretch=2)

        preview_box = QGroupBox("裁剪预览")
        preview_layout = QVBoxLayout(preview_box)
        self._preview = QLabel("未裁剪")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(120)
        self._preview.setStyleSheet("border:1px solid #aaa; background:#1a1a1a; color:#999;")
        preview_layout.addWidget(self._preview)
        info_row.addWidget(preview_box, stretch=1)
        root.addLayout(info_row)

    def _capture_game_window(self):
        self._status.setText("正在隐藏 AI 窗口，请在全屏画面中手动框选事件画面...")
        self._hidden_window = _hide_window_for_capture(self)
        QTimer.singleShot(350, self._show_manual_capture_overlay)

    def _show_manual_capture_overlay(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._overlay.set_background_image(arr)
        self._overlay.show()

    def _on_manual_capture_cancelled(self):
        self._overlay.clear_background()
        if self._hidden_window is not None:
            _restore_window_after_capture(self._hidden_window)
            self._hidden_window = None
        self._status.setText("手动截取已取消")

    def _on_manual_capture_cropped(self, img: np.ndarray):
        self._overlay.clear_background()
        if self._hidden_window is not None:
            _restore_window_after_capture(self._hidden_window)
            self._hidden_window = None
        if img is None:
            QMessageBox.warning(self, "提示", "未截取到画面")
            return
        self._set_screenshot(img, "已手动截取画面")

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择事件截图", "", "图片 (*.png *.jpg *.bmp)")
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.warning(self, "错误", "无法读取图片")
            return
        self._set_screenshot(img, f"已加载 {os.path.basename(path)}")

    def _set_screenshot(self, img: np.ndarray, message: str):
        self._screenshot = img
        self._crop = None
        self._crop_rect = None
        self._canvas.set_image(img)
        self._canvas.set_mode("select")
        self._save_reference_image(img)
        self._preview.setText("未裁剪")
        self._preview.setPixmap(QPixmap())
        self._status.setText(f"{message}，可框选事件关键区域，也可直接保存整张")

    def _on_region_selected(self, rect: QRect):
        if self._screenshot is None:
            return
        img_h, img_w = self._screenshot.shape[:2]
        x = max(0, min(rect.x(), img_w - 1))
        y = max(0, min(rect.y(), img_h - 1))
        w = min(rect.width(), img_w - x)
        h = min(rect.height(), img_h - y)
        if w <= 0 or h <= 0:
            return
        self._crop_rect = QRect(x, y, w, h)
        self._crop = self._screenshot[y:y + h, x:x + w].copy()
        self._preview.setPixmap(_cv_to_pixmap(self._crop, self._preview.width() - 8, 120))
        self._status.setText(f"已裁剪事件区域：({x},{y}) {w}x{h}")

    def _save_reference_image(self, img: np.ndarray):
        ref_dir = _app_data_path("event_reference")
        ref_path = os.path.join(ref_dir, "current.png")
        cv2.imwrite(ref_path, img)
        self._config.setdefault("event_reference", {})["image"] = ref_path
        self._save_config()

    def _save_config(self):
        config_path = os.path.join(data_path("config"), "settings.yaml")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

    def _load_reference_image(self):
        ref_path = self._config.get("event_reference", {}).get("image")
        if not ref_path:
            ref_path = _app_data_path("event_reference", "current.png")
        if not os.path.isfile(ref_path):
            return
        img = cv2.imread(ref_path)
        if img is None:
            return
        self._screenshot = img
        self._crop = None
        self._crop_rect = None
        self._canvas.set_image(img)
        self._canvas.set_mode("select")
        self._preview.setText("未裁剪")
        self._preview.setPixmap(QPixmap())
        self._status.setText(f"已加载上次事件收集底图：{os.path.basename(ref_path)}")

    def _save_event_sample(self):
        if self._screenshot is None:
            QMessageBox.information(self, "提示", "请先截取或加载一张事件画面")
            return

        self._save_reference_image(self._screenshot)
        event_id = self._event_combo.currentData()
        event_label = self._event_combo.currentText()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base_dir = _app_data_path("event_samples", event_id)
        os.makedirs(base_dir, exist_ok=True)

        image = self._crop if self._crop is not None else self._screenshot
        image_path = os.path.join(base_dir, f"{ts}.png")
        cv2.imwrite(image_path, image)

        full_path = None
        if self._crop is not None:
            full_path = os.path.join(base_dir, f"{ts}_full.png")
            cv2.imwrite(full_path, self._screenshot)

        rect = None
        if self._crop_rect is not None:
            rect = {
                "x": self._crop_rect.x(),
                "y": self._crop_rect.y(),
                "w": self._crop_rect.width(),
                "h": self._crop_rect.height(),
            }

        meta = {
            "ts": ts,
            "event_id": event_id,
            "event_label": event_label,
            "image": image_path,
            "full_image": full_path,
            "crop_rect": rect,
            "note": self._note.text().strip(),
            "game_window": self._config.get("game_window", {}),
            "app_version": self._config.get("app", {}).get("version"),
        }
        index_path = _app_data_path("event_samples", "events.jsonl")
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

        self._refresh_sample_status()
        QMessageBox.information(self, "保存成功", f"事件样本已保存：\n{image_path}")

    def _refresh_sample_status(self):
        index_path = _app_data_path("event_samples", "events.jsonl")
        if not os.path.isfile(index_path):
            self._status.setText("先截取或加载画面；可直接保存整张，也可框选关键区域后保存")
            return
        try:
            from collections import Counter
            with open(index_path, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
            counts = Counter(r["event_id"] for r in records)
            summary = "  ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
            self._status.setText(f"已有 {len(records)} 个样本：{summary}")
        except Exception:
            pass

    def _on_event_type_changed(self):
        """切换事件类型时，加载该类型最近保存的一张图作为参考。"""
        event_id = self._event_combo.currentData()
        event_dir = _app_data_path("event_samples", event_id)
        if not os.path.isdir(event_dir):
            self._screenshot = None
            self._crop = None
            self._crop_rect = None
            self._canvas.set_image(None)
            self._preview.setText("未裁剪")
            self._preview.setPixmap(QPixmap())
            self._refresh_sample_status()
            return
        pngs = sorted(
            [f for f in os.listdir(event_dir) if f.endswith(".png") and not f.endswith("_full.png")],
            reverse=True,
        )
        if not pngs:
            self._screenshot = None
            self._canvas.set_image(None)
            self._refresh_sample_status()
            return
        img = cv2.imread(os.path.join(event_dir, pngs[0]))
        if img is None:
            self._refresh_sample_status()
            return
        self._screenshot = img
        self._crop = None
        self._crop_rect = None
        self._canvas.set_image(img)
        self._canvas.set_mode("select")
        self._preview.setText("未裁剪")
        self._preview.setPixmap(QPixmap())
        self._refresh_sample_status()
