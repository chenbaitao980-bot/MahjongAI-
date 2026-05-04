from __future__ import annotations
import numpy as np
import cv2

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QImage, QFont
from PyQt6.QtWidgets import QWidget, QSizePolicy


def _cv2_to_qimage(img: np.ndarray) -> QImage:
    """BGR numpy array → QImage。"""
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w, ch = img.shape
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


class CalibrationCanvas(QWidget):
    """
    标定画布：显示截图，支持鼠标框选区域。
    - set_image()：加载截图
    - set_slots()：显示手牌槽网格（灰色边框）
    - highlight_slot()：高亮当前待标注的槽（橙色填充）
    - region_selected 信号：用户框选完成后发出 QRect（图片像素坐标）

    DPI 适配说明：
      - QPixmap 设置 devicePixelRatio，使逻辑尺寸与 Widget 逻辑尺寸对齐
      - 所有坐标转换（_scale_factor、_offset）均基于逻辑尺寸，计算结果正确
    """

    region_selected = pyqtSignal(QRect)   # 图片像素坐标

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(640, 360)

        self._image: np.ndarray | None = None
        self._pixmap: QPixmap | None = None
        self._slots: list[QRect] = []          # 全部槽（图片坐标）
        self._highlight_idx: int = -1
        self._confirmed: dict[int, str] = {}   # slot_idx → tile_id
        self._regions: list[tuple[QRect, str, QColor]] = []

        # 框选状态
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._mode: str = "select"    # "select" 或 "view"

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------ #
    #  公共接口                                                            #
    # ------------------------------------------------------------------ #

    def set_image(self, img: np.ndarray | None) -> None:
        if img is None:
            self._image = None
            self._pixmap = QPixmap()
            self._slots = []
            self._highlight_idx = -1
            self._confirmed = {}
            self._regions = []
            self.update()
            return
        self._image = img.copy()
        pixmap = QPixmap.fromImage(_cv2_to_qimage(img))
        # 关键：设置 devicePixelRatio，让 pixmap 的逻辑尺寸与 Widget 对齐
        self._pixmap = pixmap
        self._slots = []
        self._highlight_idx = -1
        self._confirmed = {}
        self._regions = []
        self.update()

    def set_slots(self, slots: list[QRect]) -> None:
        """设置手牌槽轮廓（图片坐标）。"""
        self._slots = slots
        self.update()

    def set_regions(self, regions: list[tuple[QRect, str, QColor]]) -> None:
        """设置持久区域标注（图片坐标），用于显示已保存的区域划分。"""
        self._regions = regions
        self.update()

    def highlight_slot(self, idx: int) -> None:
        """高亮第 idx 个槽。"""
        self._highlight_idx = idx
        self.update()

    def confirm_slot(self, idx: int, tile_id: str) -> None:
        """标记第 idx 槽已标注。"""
        self._confirmed[idx] = tile_id
        self.update()

    def set_mode(self, mode: str) -> None:
        """mode: "select"（框选模式） 或 "view"（只查看）。"""
        self._mode = mode
        cursor = Qt.CursorShape.CrossCursor if mode == "select" else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    # ------------------------------------------------------------------ #
    #  坐标转换                                                            #
    # ------------------------------------------------------------------ #

    def _img_to_widget(self, pt: QPoint) -> QPoint:
        if self._pixmap is None:
            return pt
        scale = self._scale_factor()
        ox, oy = self._offset()
        return QPoint(round(pt.x() * scale + ox), round(pt.y() * scale + oy))

    def _widget_to_img(self, pt: QPoint) -> QPoint:
        if self._pixmap is None:
            return pt
        scale = self._scale_factor()
        ox, oy = self._offset()
        return QPoint(round((pt.x() - ox) / scale), round((pt.y() - oy) / scale))

    def _scale_factor(self) -> float:
        if self._image is None:
            return 1.0
        # 由于 pixmap 设置了 devicePixelRatio，pixmap.width() 返回的是逻辑宽度
        img_h, img_w = self._image.shape[:2]
        sx = self.width() / max(img_w, 1)
        sy = self.height() / max(img_h, 1)
        return min(sx, sy)

    def _offset(self) -> tuple[int, int]:
        if self._image is None:
            return 0, 0
        scale = self._scale_factor()
        img_h, img_w = self._image.shape[:2]
        ox = (self.width() - img_w * scale) / 2
        oy = (self.height() - img_h * scale) / 2
        return round(ox), round(oy)

    def _rect_to_widget(self, r: QRect) -> QRect:
        tl = self._img_to_widget(r.topLeft())
        br = self._img_to_widget(r.bottomRight())
        return QRect(tl, br)

    # ------------------------------------------------------------------ #
    #  绘制                                                                #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._pixmap:
            scale = self._scale_factor()
            ox, oy = self._offset()
            # 绘制尺寸是逻辑像素（和 Widget 对齐）
            img_h, img_w = self._image.shape[:2] if self._image is not None else (self._pixmap.height(), self._pixmap.width())
            draw_w = round(img_w * scale)
            draw_h = round(img_h * scale)
            scaled = self._pixmap.scaled(
                draw_w,
                draw_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(ox, oy, scaled)

        # 绘制槽轮廓
        for i, slot in enumerate(self._slots):
            wr = self._rect_to_widget(slot)
            if i == self._highlight_idx:
                painter.fillRect(wr, QColor(255, 165, 0, 100))
                pen = QPen(QColor(255, 140, 0), 2)
            elif i in self._confirmed:
                painter.fillRect(wr, QColor(0, 200, 0, 60))
                pen = QPen(QColor(0, 180, 0), 1)
            else:
                pen = QPen(QColor(180, 180, 180), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(wr)

            # 已标注的槽显示牌名
            if i in self._confirmed:
                painter.setPen(QColor(0, 100, 0))
                painter.setFont(QFont("Arial", max(8, wr.height() // 4)))
                painter.drawText(wr, Qt.AlignmentFlag.AlignCenter, self._confirmed[i])

        # 绘制持久区域标注
        for region, label, color in self._regions:
            wr = self._rect_to_widget(region)
            fill = QColor(color)
            fill.setAlpha(35)
            painter.fillRect(wr, fill)
            painter.setPen(QPen(color, 2))
            painter.drawRect(wr)
            painter.setFont(QFont("Microsoft YaHei", max(9, min(14, wr.height() // 6 if wr.height() else 10))))
            text_rect = QRect(wr.x() + 3, wr.y() + 3, max(wr.width() - 6, 1), 22)
            painter.fillRect(text_rect, QColor(0, 0, 0, 110))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        # 当前拖拽框
        if self._drag_start and self._drag_current:
            x1 = min(self._drag_start.x(), self._drag_current.x())
            y1 = min(self._drag_start.y(), self._drag_current.y())
            x2 = max(self._drag_start.x(), self._drag_current.x())
            y2 = max(self._drag_start.y(), self._drag_current.y())
            sel = QRect(x1, y1, x2 - x1, y2 - y1)
            painter.fillRect(sel, QColor(255, 140, 0, 40))
            painter.setPen(QPen(QColor(255, 140, 0), 2))
            painter.drawRect(sel)

    # ------------------------------------------------------------------ #
    #  鼠标事件                                                            #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        if self._mode == "select" and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
            self._drag_current = event.pos()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            self._drag_current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            end = event.pos()
            x1 = min(self._drag_start.x(), end.x())
            y1 = min(self._drag_start.y(), end.y())
            x2 = max(self._drag_start.x(), end.x())
            y2 = max(self._drag_start.y(), end.y())
            self._drag_start = None
            self._drag_current = None
            self.update()

            if x2 - x1 > 5 and y2 - y1 > 5:
                # 转换为图片坐标
                tl_img = self._widget_to_img(QPoint(x1, y1))
                br_img = self._widget_to_img(QPoint(x2, y2))
                self.region_selected.emit(QRect(tl_img, br_img))

    def get_slot_roi(self, idx: int) -> np.ndarray | None:
        """获取第 idx 槽对应的图片区域（numpy array）。"""
        if self._image is None or idx >= len(self._slots):
            return None
        r = self._slots[idx]
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        img_h, img_w = self._image.shape[:2]
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)
        if w <= 0 or h <= 0:
            return None
        return self._image[y:y + h, x:x + w].copy()
