"""台州麻将AI视觉识别层 — 应用入口。"""
import sys
import os
import yaml
import logging
from datetime import datetime

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow
from utils.paths import resource_path, data_path


def setup_logging() -> None:
    """配置日志：输出到控制台 + 文件滚动记录。"""
    log_dir = data_path("logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"mahjongai_{datetime.now():%Y%m%d_%H%M%S}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("日志初始化完成 → %s", log_file)


def load_config() -> dict:
    """优先加载 exe 同级 config/settings.yaml（用户可写），fallback 到打包内资源。"""
    writable_cfg = os.path.join(data_path("config"), "settings.yaml")
    if os.path.isfile(writable_cfg):
        cfg_path = writable_cfg
    else:
        cfg_path = resource_path(os.path.join("config", "settings.yaml"))

    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("台州麻将AI")
    app.setOrganizationName("MahjongAI")

    setup_logging()

    config = load_config()
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
