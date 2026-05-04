from __future__ import annotations
import os
import cv2
import numpy as np
import mss

from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage
from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QSpinBox, QComboBox, QFileDialog, QScrollArea,
    QWidget, QGridLayout, QGroupBox, QLineEdit, QMessageBox,
    QProgressBar, QFrame,
)

from ui.calibration_canvas import CalibrationCanvas
from ui.region_selector import RegionSelectorOverlay
from vision.recognizer import TileRecognizer, ButtonRecognizer
from game.state import ALL_TILE_IDS, BUTTON_IDS


TILE_LABELS = {
    **{f"{i}m": f"{i}万" for i in range(1, 10)},
    **{f"{i}p": f"{i}筒" for i in range(1, 10)},
    **{f"{i}s": f"{i}条" for i in range(1, 10)},
    "1z": "东", "2z": "南", "3z": "西", "4z": "北",
    "5z": "中", "6z": "发", "7z": "白",
}

BTN_LABELS = {
    "碰": "碰", "吃": "吃", "杠_明": "明杠",
    "杠_暗": "暗杠", "杠_补": "补杠", "胡": "胡", "过": "过",
}


class CalibrationWizard(QWizard):
    """牌面收集向导：截图 → 牌面裁剪 → 完成。区域划分与事件采集在主界面独立维护。"""

    calibration_complete = pyqtSignal(str)   # 模板目录路径

    def __init__(self, tile_recognizer: TileRecognizer,
                 button_recognizer: ButtonRecognizer,
                 tile_template_dir: str,
                 button_template_dir: str,
                 overlay_template_dir: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("牌面收集向导")
        self.resize(880, 640)
        self.setMinimumSize(720, 520)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        self._tile_rec = tile_recognizer
        self._btn_rec = button_recognizer
        self._tile_dir = tile_template_dir
        self._btn_dir = button_template_dir
        self._overlay_dir = overlay_template_dir

        self._screenshot: np.ndarray | None = None
        self._hand_rect: QRect | None = None        # 手牌区（图片坐标）

        self.addPage(WelcomePage())
        self.addPage(ScreenshotPage(self))
        self.addPage(SlotLabelPage(self))
        self.addPage(FinishPage(self))

        self.finished.connect(self._on_finished)

    def _on_finished(self, result):
        if result == QWizard.DialogCode.Accepted:
            self.calibration_complete.emit(self._tile_dir)


# ------------------------------------------------------------------ #
#  页面0：欢迎                                                         #
# ------------------------------------------------------------------ #

class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("欢迎使用标定向导")
        layout = QVBoxLayout(self)
        text = QLabel(
            "<h3>本向导将帮助你收集牌面样本</h3>"
            "<p>整个过程分为以下步骤：</p>"
            "<ol>"
            "<li>截取一帧游戏画面（或从文件加载）</li>"
            "<li>收集 34 种牌的单张牌面样本（从截图裁剪或文件上传）</li>"
            "<li>保存所有模板，完成</li>"
            "</ol>"
            "<p><b>提示：</b>手牌、弃牌、按钮等区域请到主界面的「区域划分」中设置；"
            "事件画面请到「事件收集」中保存。</p>"
        )
        text.setWordWrap(True)
        layout.addWidget(text)


# ------------------------------------------------------------------ #
#  页面1：截图获取                                                     #
# ------------------------------------------------------------------ #

class ScreenshotPage(QWizardPage):
    def __init__(self, wizard: CalibrationWizard):
        super().__init__()
        self._wiz = wizard
        self.setTitle("获取参考截图")
        self.setSubTitle("截取游戏画面，或从文件加载一张截图。")

        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self._btn_capture = QPushButton("截取当前屏幕")
        self._btn_load = QPushButton("从文件加载...")
        btn_row.addWidget(self._btn_capture)
        btn_row.addWidget(self._btn_load)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._preview = QLabel("尚未加载截图")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(300)
        self._preview.setStyleSheet("border: 1px solid #aaa; background: #1a1a1a; color: #999;")
        layout.addWidget(self._preview)

        self._overlay = RegionSelectorOverlay()
        self._overlay.region_selected.connect(self._on_screen_region)
        self._overlay.cropped_image.connect(self._on_cropped_image)
        self._overlay.cancelled.connect(self._on_capture_cancelled)

        self._btn_capture.clicked.connect(self._start_capture)
        self._btn_load.clicked.connect(self._load_file)

    def _start_capture(self):
        """隐藏向导和主窗口 → 静默截全屏 → 传给覆盖层 → 显示选区。"""
        self._wiz.hide()
        if self._wiz.parent():
            self._wiz.parent().hide()
        QTimer.singleShot(400, self._do_silent_capture)

    def _do_silent_capture(self):
        """静默截取全屏，存入覆盖层，然后才显示选区界面。"""
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._overlay.set_background_image(arr)
        self._overlay.show()

    def _on_capture_cancelled(self):
        self._overlay.clear_background()
        self._wiz.show()
        self._wiz.raise_()
        if self._wiz.parent():
            self._wiz.parent().show()
            self._wiz.parent().raise_()

    def _on_screen_region(self, region: dict):
        pass

    def _on_cropped_image(self, cropped: np.ndarray):
        """用户选区完成后，等向导布局完成再显示截图（确保 preview 尺寸有效）。"""
        self._overlay.clear_background()
        self._wiz.show()
        self._wiz.raise_()
        if self._wiz.parent():
            self._wiz.parent().show()
            self._wiz.parent().raise_()
        self._pending_screenshot = cropped
        QTimer.singleShot(50, self._apply_pending_screenshot)

    def _apply_pending_screenshot(self):
        if hasattr(self, '_pending_screenshot') and self._pending_screenshot is not None:
            self._set_screenshot(self._pending_screenshot)
            self._pending_screenshot = None

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择截图", "", "图片 (*.png *.jpg *.bmp)")
        if path:
            img = cv2.imread(path)
            if img is not None:
                self._set_screenshot(img)

    def _set_screenshot(self, img: np.ndarray):
        self._wiz._screenshot = img
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        label_w = max(self._preview.width(), 1)
        label_h = max(self._preview.height(), 1)
        scaled = pix.scaled(
            label_w, label_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._wiz._screenshot is not None


# ------------------------------------------------------------------ #
#  页面2：手牌区框选                                                   #
# ------------------------------------------------------------------ #

class HandRegionPage(QWizardPage):
    def __init__(self, wizard: CalibrationWizard):
        super().__init__()
        self._wiz = wizard
        self.setTitle("框选手牌区域")
        self.setSubTitle("用鼠标拖拽框选包含全部手牌的矩形区域。运行时系统会自动识别所有手牌。")

        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        self._status = QLabel("请框选手牌区域（不需要精确，包住全部手牌即可）")
        ctrl.addWidget(self._status)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self._canvas = CalibrationCanvas()
        self._canvas.region_selected.connect(self._on_region)
        layout.addWidget(self._canvas)

    def initializePage(self):
        if self._wiz._screenshot is not None:
            self._canvas.set_image(self._wiz._screenshot)
            self._canvas.set_mode("select")

    def _on_region(self, rect: QRect):
        self._wiz._hand_rect = rect
        self._status.setText(f"已选手牌区：({rect.x()},{rect.y()}) {rect.width()}×{rect.height()}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._wiz._hand_rect is not None


# ------------------------------------------------------------------ #
#  牌面收集（图鉴样本）                                                #
# ------------------------------------------------------------------ #

class SlotLabelPage(QWizardPage):
    """
    牌面模板收集页面 —— 不需要分槽！

    用户只需：
      1. 在左侧截图上框选一张牌（或从文件上传单张牌截图）
      2. 在右侧选择牌种，点击"保存为模板"
      3. 重复 34 次，直到所有牌种都收集完成
    """

    def __init__(self, wizard: CalibrationWizard):
        super().__init__()
        self._wiz = wizard
        self.setTitle("牌面收集")
        self.setSubTitle(
            "收集 34 种牌的单张牌面样本。在左侧截图上框选一张牌（或上传文件），"
            "选择牌种后保存。可分多次补齐。"
        )

        layout = QVBoxLayout(self)

        # 左右分栏
        main = QHBoxLayout()

        # ---- 左侧：截图预览 + 操作 -----------------------------------
        left = QVBoxLayout()

        self._canvas = CalibrationCanvas()
        self._canvas.set_mode("view")
        self._canvas.region_selected.connect(self._on_crop_from_screenshot)
        left.addWidget(self._canvas, stretch=3)

        self._status = QLabel("提示：点击「从截图裁剪」后，在截图上框选一张牌")
        self._status.setWordWrap(True)
        left.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._btn_crop = QPushButton("从截图裁剪")
        self._btn_crop.setCheckable(True)
        self._btn_crop.clicked.connect(self._toggle_crop_mode)
        btn_row.addWidget(self._btn_crop)

        self._btn_upload = QPushButton("从文件上传...")
        self._btn_upload.clicked.connect(self._upload_file)
        btn_row.addWidget(self._btn_upload)

        self._btn_restore = QPushButton("恢复截图")
        self._btn_restore.clicked.connect(self._restore_screenshot)
        btn_row.addWidget(self._btn_restore)
        btn_row.addStretch()
        left.addLayout(btn_row)

        main.addLayout(left, stretch=3)

        # ---- 右侧：牌种选择 + 保存 + 进度 ------------------------------
        right = QVBoxLayout()

        self._preview_label = QLabel("裁剪预览")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(120)
        self._preview_label.setStyleSheet("border:1px solid #aaa; background:#1a1a1a; color:#999;")
        right.addWidget(self._preview_label)

        right.addWidget(QLabel("选择牌种："))
        self._combo = QComboBox()
        self._combo.addItems([f"{tid} ({TILE_LABELS.get(tid, tid)})" for tid in ALL_TILE_IDS])
        right.addWidget(self._combo)

        self._btn_save = QPushButton("保存为牌面样本")
        self._btn_save.clicked.connect(self._save_template)
        right.addWidget(self._btn_save)

        right.addWidget(QLabel("模板收集进度（绿色=已收集）："))
        prog_widget = QWidget()
        self._prog_grid = QGridLayout(prog_widget)
        self._prog_grid.setSpacing(2)
        self._prog_cells: dict[str, QLabel] = {}
        for i, tid in enumerate(ALL_TILE_IDS):
            cell = QLabel(TILE_LABELS.get(tid, tid))
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setFixedSize(44, 30)
            cell.setStyleSheet("border:1px solid #ccc; border-radius:3px; background:#f0f0f0; font-size:11px;")
            self._prog_grid.addWidget(cell, i // 9, i % 9)
            self._prog_cells[tid] = cell
        right.addWidget(prog_widget)

        self._progress_text = QLabel("已收集：0 / 34 种")
        right.addWidget(self._progress_text)

        right.addStretch()
        main.addLayout(right, stretch=1)

        layout.addLayout(main)

        self._pending_roi: np.ndarray | None = None

    # ------------------------------------------------------------------ #
    #  公共接口                                                            #
    # ------------------------------------------------------------------ #

    def initializePage(self):
        self._pending_roi = None
        self._btn_crop.setChecked(False)
        if self._wiz._screenshot is not None:
            self._canvas.set_image(self._wiz._screenshot)
        self._canvas.set_mode("view")
        self._update_preview(None)
        self._update_progress_grid()

    def _toggle_crop_mode(self, checked: bool):
        """切换截图裁剪模式。"""
        if checked:
            self._canvas.set_mode("select")
            self._status.setText("裁剪模式：在截图上拖拽框选一张牌")
        else:
            self._canvas.set_mode("view")
            self._status.setText("提示：点击「从截图裁剪」后，在截图上框选一张牌")

    def _on_crop_from_screenshot(self, rect: QRect):
        """用户在截图上框选了一张牌。"""
        if self._wiz._screenshot is None:
            return
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        img_h, img_w = self._wiz._screenshot.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)
        if w > 10 and h > 10:
            self._pending_roi = self._wiz._screenshot[y:y + h, x:x + w].copy()
            self._update_preview(self._pending_roi)
            self._status.setText(f"已裁剪 {w}×{h}，选择牌种后点击「保存为模板」")
            self._btn_crop.setChecked(False)
            self._canvas.set_mode("view")

    def _upload_file(self):
        """从文件上传单张牌截图。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择单张牌截图", "", "图片 (*.png *.jpg *.bmp)"
        )
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.warning(self, "错误", "无法读取图片")
            return
        self._pending_roi = img
        self._update_preview(img)
        self._canvas.set_image(img)
        self._status.setText(f"已加载文件 {img.shape[1]}×{img.shape[0]}，选择牌种后点击「保存为模板」")

    def _restore_screenshot(self):
        """恢复显示原始截图。"""
        if self._wiz._screenshot is not None:
            self._canvas.set_image(self._wiz._screenshot)
            self._status.setText("已恢复截图预览")

    def _save_template(self):
        """保存当前裁剪图为模板。"""
        if self._pending_roi is None:
            QMessageBox.warning(self, "提示", "请先框选一张牌或从文件上传")
            return
        text = self._combo.currentText().split(" ")[0]
        if text not in ALL_TILE_IDS:
            QMessageBox.warning(self, "提示", "请选择有效的牌种")
            return
        self._wiz._tile_rec.save_template(self._pending_roi, text, self._wiz._tile_dir)
        self._update_progress_grid()
        name = TILE_LABELS.get(text, text)
        self._status.setText(f"✓ 已保存「{name}」模板")
        self._pending_roi = None
        self._update_preview(None)
        self.completeChanged.emit()

    def _update_preview(self, img: np.ndarray | None):
        """更新右侧裁剪预览。"""
        if img is None:
            self._preview_label.setText("裁剪预览\n（框选或上传后显示）")
            return
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        label_w = self._preview_label.width()
        label_h = self._preview_label.height()
        scaled = pix.scaled(
            max(label_w - 10, 1), max(label_h - 10, 1),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

    def _update_progress_grid(self):
        """刷新 34 格收集状态。"""
        loaded = set(self._wiz._tile_rec.loaded_tiles)
        for tid, cell in self._prog_cells.items():
            if tid in loaded:
                cell.setStyleSheet(
                    "border:1px solid #2a7; border-radius:3px; background:#90ee90; font-size:11px;"
                )
            else:
                cell.setStyleSheet(
                    "border:1px solid #ccc; border-radius:3px; background:#f0f0f0; font-size:11px;"
                )
        self._progress_text.setText(f"已收集：{len(loaded)} / 34 种")

    def isComplete(self) -> bool:
        """允许部分收集，随时可进入下一步（未收集的牌种运行时会识别为 ?）。"""
        return True


# ------------------------------------------------------------------ #
#  旧按钮模板页面（保留类定义，当前入口已迁移到独立事件/区域采集）       #
# ------------------------------------------------------------------ #

class ButtonCalibPage(QWizardPage):
    def __init__(self, wizard: CalibrationWizard):
        super().__init__()
        self._wiz = wizard
        self.setTitle("决策按钮标定（可跳过）")
        self.setSubTitle(
            "截取含有碰/吃/杠/胡/过按钮的画面，逐个框选并保存为模板。\n"
            "如果现在没有合适的截图，可以直接点击下一步，以后补充。"
        )

        layout = QVBoxLayout(self)

        # 截图获取行
        shot_row = QHBoxLayout()
        self._btn_capture = QPushButton("重新截取画面")
        self._btn_load = QPushButton("从文件加载...")
        shot_row.addWidget(self._btn_capture)
        shot_row.addWidget(self._btn_load)
        shot_row.addStretch()
        layout.addLayout(shot_row)

        self._canvas = CalibrationCanvas()
        self._canvas.region_selected.connect(self._on_region_selected)
        layout.addWidget(self._canvas, stretch=2)

        # 按钮类型选择
        btn_row = QHBoxLayout()
        btn_row.addWidget(QLabel("当前标定："))
        self._combo = QComboBox()
        for bid, label in BTN_LABELS.items():
            self._combo.addItem(f"{label} ({bid})", bid)
        self._combo.addItem("流局（覆盖层）", "overlay_流局")
        self._combo.addItem("胡牌结算（覆盖层）", "overlay_胡牌")
        btn_row.addWidget(self._combo)
        self._save_btn = QPushButton("框选并保存此模板")
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 进度
        self._progress_label = QLabel("已保存：0 / 9")
        layout.addWidget(self._progress_label)

        self._saved: set[str] = set()
        self._btn_screenshot: np.ndarray | None = None

        self._overlay = RegionSelectorOverlay()
        self._overlay.region_selected.connect(self._on_capture_region)
        self._overlay.cropped_image.connect(self._on_cropped_image)
        self._overlay.cancelled.connect(self._on_capture_cancelled)

        self._btn_capture.clicked.connect(self._start_capture)
        self._btn_load.clicked.connect(self._load_file)
        self._save_btn.clicked.connect(self._do_save)

    def _start_capture(self):
        """隐藏向导和主窗口 → 静默截全屏 → 传给覆盖层 → 显示选区。"""
        self._wiz.hide()
        if self._wiz.parent():
            self._wiz.parent().hide()
        QTimer.singleShot(400, self._do_silent_capture)

    def _do_silent_capture(self):
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            arr = np.frombuffer(shot.raw, dtype=np.uint8)
            arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
        self._overlay.set_background_image(arr)
        self._overlay.show()

    def _on_capture_cancelled(self):
        self._overlay.clear_background()
        self._wiz.show()
        self._wiz.raise_()
        if self._wiz.parent():
            self._wiz.parent().show()
            self._wiz.parent().raise_()

    def initializePage(self):
        # 复用手牌截图作为初始画面
        if self._wiz._screenshot is not None:
            self._btn_screenshot = self._wiz._screenshot.copy()
            self._canvas.set_image(self._btn_screenshot)
            self._canvas.set_mode("select")

    def _on_capture_region(self, region: dict):
        pass

    def _on_cropped_image(self, cropped: np.ndarray):
        """用户选区完成后，用裁剪好的图片更新画布。"""
        self._overlay.clear_background()
        self._wiz.show()
        self._wiz.raise_()
        if self._wiz.parent():
            self._wiz.parent().show()
            self._wiz.parent().raise_()
        self._btn_screenshot = cropped
        self._canvas.set_image(cropped)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择截图", "", "图片 (*.png *.jpg)")
        if path:
            img = cv2.imread(path)
            if img is not None:
                self._btn_screenshot = img
                self._canvas.set_image(img)

    def _on_region_selected(self, rect: QRect):
        self._pending_rect = rect

    def _do_save(self):
        rect = getattr(self, "_pending_rect", None)
        if rect is None or self._btn_screenshot is None:
            QMessageBox.warning(self, "提示", "请先在画面上框选按钮区域")
            return
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        img_h, img_w = self._btn_screenshot.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)
        roi = self._btn_screenshot[y:y + h, x:x + w]

        item_data = self._combo.currentData()
        if item_data.startswith("overlay_"):
            overlay_id = item_data[len("overlay_"):]
            self._btn_rec.save_overlay_template(roi, overlay_id, self._wiz._overlay_dir)
        else:
            self._btn_rec.save_button_template(roi, item_data, self._wiz._btn_dir)

        self._saved.add(item_data)
        self._progress_label.setText(f"已保存：{len(self._saved)} / 9")
        self._pending_rect = None

    def isComplete(self) -> bool:
        return True   # 可跳过


# ------------------------------------------------------------------ #
#  完成                                                                #
# ------------------------------------------------------------------ #

class FinishPage(QWizardPage):
    def __init__(self, wizard: CalibrationWizard):
        super().__init__()
        self._wiz = wizard
        self.setTitle("牌面收集完成")

    def initializePage(self):
        layout = self.layout()
        if layout is None:
            layout = QVBoxLayout(self)

        loaded = set(self._wiz._tile_rec.loaded_tiles)
        info = QLabel(
            f"<h3>牌面收集完成</h3>"
            f"<p>已收集 <b>{len(loaded)}</b> 种牌面样本（共34种）。</p>"
            f"<p>样本保存在：<code>{self._wiz._tile_dir}</code></p>"
            f"<p>区域划分和事件样本可继续在主界面独立补充。</p>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
