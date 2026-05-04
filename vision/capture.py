from __future__ import annotations
import numpy as np
import mss
import mss.tools
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vision.layout import Rect


class ScreenCapture:
    """基于 mss 的屏幕截图封装，单次截图 <5ms。"""

    def __init__(self, region: dict | None = None):
        """
        region: {"top": int, "left": int, "width": int, "height": int}
        传 None 时需在 update_region 后才能使用 grab()。
        """
        self._local = threading.local()
        self._sct = None
        self._region = region

    def _get_sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
            self._sct = sct
        return sct

    def update_region(self, region: dict) -> None:
        self._region = region

    def grab(self) -> np.ndarray:
        """截取当前配置区域，返回 BGR numpy array。"""
        if self._region is None:
            raise RuntimeError("截图区域未设置，请先调用 update_region()")
        shot = self._get_sct().grab(self._region)
        # mss 返回 BGRA，去掉 alpha 通道
        arr = np.frombuffer(shot.raw, dtype=np.uint8)
        arr = arr.reshape((shot.height, shot.width, 4))
        return arr[:, :, :3].copy()  # BGR

    def grab_from_frame(self, frame: np.ndarray, rect: "Rect") -> np.ndarray:
        """从已截取的全帧中裁剪子区域，避免重复截屏。"""
        return frame[rect.y: rect.y + rect.h, rect.x: rect.x + rect.w].copy()

    def grab_file(self, path: str) -> np.ndarray:
        """从文件加载图片（用于开发测试和标定工具）。"""
        import cv2
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {path}")
        return img

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct:
            sct.close()
            self._local.sct = None
        if self._sct and self._sct is not sct:
            self._sct.close()
        self._sct = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
