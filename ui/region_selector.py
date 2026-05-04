from __future__ import annotations
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QImage, QPixmap
from PyQt6.QtWidgets import QWidget
import numpy as np
import mss
import cv2


class RegionSelectorOverlay(QWidget):
    """
    全屏半透明覆盖层，用鼠标拖拽框选区域。

    关键流程（解决截图截到覆盖层自身的问题）：
      1. show() 前必须先调用 set_background_image() 传入已截好的全屏图像
      2. 选区完成后，用图片坐标裁剪背景图并发出 cropped_image 信号
         （而不是用 mss 再次截图）

    DPI 适配说明：
      - mss 截图返回的是物理像素
      - PyQt 鼠标事件返回逻辑坐标（受 Windows DPI 缩放影响）
      - 通过 devicePixelRatio() 把逻辑坐标转回物理坐标后再裁剪
      - 背景图 QPixmap 设置 devicePixelRatio，使 drawPixmap 时 1:1 物理像素绘制
    """

    region_selected = pyqtSignal(dict)   # {"top", "left", "width", "height"}
    cropped_image   = pyqtSignal(np.ndarray)  # 裁剪后的 BGR 图像
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._bg_image: np.ndarray | None = None   # 全屏背景图（物理像素，BGR）
        self._bg_qpixmap: QPixmap | None = None     # 缓存的 QPixmap

    # ------------------------------------------------------------------ #
    #  公共 API                                                           #
    # ------------------------------------------------------------------ #

    def set_background_image(self, full_screen_bgr: np.ndarray):
        """在 show() 前调用，传入已截好的全屏 BGR 图像（物理像素）。"""
        self._bg_image = full_screen_bgr
        rgb = cv2.cvtColor(full_screen_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimg)
        # 关键：设置 devicePixelRatio，让 drawPixmap 时按物理像素 1:1 绘制
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self._bg_qpixmap = pixmap

    def clear_background(self):
        self._bg_image = None
        self._bg_qpixmap = None
        self.update()

    # ------------------------------------------------------------------ #
    #  Qt 事件                                                            #
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        super().showEvent(event)
        # 显示时重新同步 DPR（窗口可能刚关联到屏幕）
        if self._bg_qpixmap is not None:
            self._bg_qpixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self.grabMouse()
        self.grabKeyboard()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.releaseMouse()
        self.releaseKeyboard()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pos()
            self._current = event.pos()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start is not None:
            end = event.pos()
            x1, y1 = min(self._start.x(), end.x()), min(self._start.y(), end.y())
            x2, y2 = max(self._start.x(), end.x()), max(self._start.y(), end.y())
            w, h = x2 - x1, y2 - y1

            self._start = None
            self._current = None
            self.hide()

            if w > 10 and h > 10:
                # === DPI 适配：把逻辑坐标转回物理像素 ===
                dpr = self.devicePixelRatioF()
                x1_p = int(x1 * dpr)
                y1_p = int(y1 * dpr)
                x2_p = int(x2 * dpr)
                y2_p = int(y2 * dpr)
                w_p = x2_p - x1_p
                h_p = y2_p - y1_p

                self.region_selected.emit({
                    "top": y1_p,
                    "left": x1_p,
                    "width": w_p,
                    "height": h_p,
                })
                # 从背景图（物理像素）中裁剪对应区域
                if self._bg_image is not None:
                    clipped = self._bg_image[y1_p:y1_p + h_p, x1_p:x1_p + w_p].copy()
                    self.cropped_image.emit(clipped)
                else:
                    # 兜底：没有背景图时用 mss 截（不推荐，但兼容）
                    with mss.mss() as sct:
                        shot = sct.grab({"top": y1_p, "left": x1_p, "width": w_p, "height": h_p})
                        arr = np.frombuffer(shot.raw, dtype=np.uint8)
                        arr = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()
                    self.cropped_image.emit(arr)
            else:
                self.cancelled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景图（已设置 devicePixelRatio，会以物理像素 1:1 绘制）
        if self._bg_qpixmap:
            painter.drawPixmap(self.rect(), self._bg_qpixmap)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        # 半透明遮罩（让背景图变暗，便于看清选框）
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))

        if self._start and self._current:
            x1 = min(self._start.x(), self._current.x())
            y1 = min(self._start.y(), self._current.y())
            x2 = max(self._start.x(), self._current.x())
            y2 = max(self._start.y(), self._current.y())
            sel = QRect(x1, y1, x2 - x1, y2 - y1)

            # 选中区域更透明（让用户看到背景图内容）
            painter.fillRect(sel, QColor(255, 255, 255, 30))

            # 橙色边框
            pen = QPen(QColor(255, 140, 0), 2)
            painter.setPen(pen)
            painter.drawRect(sel)

            # 尺寸提示（显示物理像素尺寸，和最终裁剪结果一致）
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Arial", 12)
            painter.setFont(font)
            dpr = self.devicePixelRatioF()
            label = f"{int(sel.width() * dpr)} × {int(sel.height() * dpr)}"
            painter.drawText(x1 + 5, y1 - 5 if y1 > 20 else y2 + 18, label)

        # 顶部提示文字
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 14)
        painter.setFont(font)
        painter.drawText(10, 28, "拖拽选择游戏窗口区域   |   ESC 取消")
