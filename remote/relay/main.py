"""
main.py — relay 入口

加载配置，启动 uvicorn FastAPI 服务。

用法:
  python main.py [--config CONFIG] [--host HOST] [--port PORT]
  或:
  uvicorn main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
)

# 额外挂文件日志 handler，便于事后诊断 GameClient 连接问题
# （console 是独立黑窗口，用户看不到也存不下）
_LOG_FILE = os.path.join(os.path.dirname(__file__), "relay.log")


def _attach_file_handler():
    root = logging.getLogger()
    # 避免重复添加（模块可能被多次导入 / uvicorn reload）
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and \
                getattr(h, "baseFilename", None) == os.path.abspath(_LOG_FILE):
            return
    file_handler = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)


_attach_file_handler()

_LOGGER = logging.getLogger("remote.relay")

# 加载配置并注入到 app 模块
_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "config.yaml")


def _load_config(path):
    if not os.path.isfile(path):
        _LOGGER.warning("配置文件不存在: %s，使用默认值", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 加载配置（模块导入时执行，支持 uvicorn main:app 直接启动）
_cfg = _load_config(_DEFAULT_CONFIG)

# 注入配置到 app
from app import app, configure
configure(_cfg)


def main():
    parser = argparse.ArgumentParser(description="MahjongAI Remote Relay 服务")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    args = parser.parse_args()

    # 重新加载指定配置文件
    if args.config != _DEFAULT_CONFIG:
        cfg = _load_config(args.config)
        configure(cfg)

    import uvicorn
    _LOGGER.info("启动 relay 服务: http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
