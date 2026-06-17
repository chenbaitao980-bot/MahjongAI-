"""
main.py — MahjongAI Noconfig Relay 入口

从同目录 config.yaml 读取配置（fallback: ../relay/config_noconfig.yaml），
注入到 app.py，然后启动 uvicorn。

用法:
  python main.py                          # 默认 0.0.0.0:8002
  python main.py --port 8080
  python main.py --host 127.0.0.1
  python main.py --config /path/to/cfg.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# ─── sys.path 设置 ──────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RELAY_DIR = os.path.join(_ROOT, "remote", "relay")

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _RELAY_DIR not in sys.path:
    sys.path.insert(0, _RELAY_DIR)
# 强制让 noconfig 目录排在最前：noconfig 与 relay 都有 app.py / state_store.py，
# 直接 `python main.py` 时脚本目录已在 sys.path 中，`not in` 判断会跳过插入，
# 导致 _RELAY_DIR 抢到首位、`from app import app` 误加载 relay/app.py（单用户版）。
while _HERE in sys.path:
    sys.path.remove(_HERE)
sys.path.insert(0, _HERE)

# ─── 日志 ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("remote.noconfig")

# ─── 默认配置路径 ────────────────────────────────────────────────

_DEFAULT_CONFIG = os.path.join(_HERE, "config.yaml")
_FALLBACK_CONFIG = os.path.join(_RELAY_DIR, "config_noconfig.yaml")


def load_config(path: str) -> dict:
    """加载 YAML 配置文件，不存在时返回空字典"""
    import yaml

    if not os.path.isfile(path):
        _LOGGER.warning("配置文件不存在: %s", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_config_path(override: str = "") -> str:
    """确定最终使用的配置文件路径。

    优先级：
    1. 命令行 --config 参数（若指定且文件存在）
    2. 同目录 config.yaml
    3. ../relay/config_noconfig.yaml（fallback）
    """
    if override and os.path.isfile(override):
        return os.path.abspath(override)
    if os.path.isfile(_DEFAULT_CONFIG):
        return _DEFAULT_CONFIG
    return _FALLBACK_CONFIG


def main():
    parser = argparse.ArgumentParser(
        description="MahjongAI Noconfig Relay — 无配置模式独立服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                          # 默认 0.0.0.0:8002
  python main.py --port 8080              # 自定义端口
  python main.py --host 127.0.0.1        # 仅本地监听
  python main.py --config my_cfg.yaml    # 自定义配置
        """,
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8002, help="监听端口（默认 8002）")
    parser.add_argument("--config", default="", help="自定义配置文件路径")
    args = parser.parse_args()

    cfg_path = resolve_config_path(args.config)
    cfg = load_config(cfg_path)

    # 将命令行端口注入配置（命令行优先）
    port = args.port if args.port != 8002 else int(cfg.get("port", 8002))
    if args.port != 8002:
        port = args.port
    cfg["port"] = port

    _LOGGER.info("=" * 50)
    _LOGGER.info("MahjongAI Noconfig Relay")
    _LOGGER.info("配置文件: %s", cfg_path)
    _LOGGER.info("监听: %s:%d", args.host, port)

    hs = cfg.get("handshake_blob", "")
    at = cfg.get("auth_token_12b", "")
    srs_sid = cfg.get("srs_sessionid", "")
    if hs and at:
        _LOGGER.info("[凭证] 已有持久化凭证: hs=%d bytes, auth=%d bytes",
                     len(hs) // 2, len(at) // 2)
    else:
        _LOGGER.info("[凭证] 无持久化凭证，需要通过 extractor 注册")
    if srs_sid:
        _LOGGER.info("[SRS] srs_sessionid 已有: %d bytes", len(srs_sid) // 2)
    else:
        _LOGGER.info("[SRS] 无 srs_sessionid，spectator 不会自动启动")
    _LOGGER.info("=" * 50)

    # 注入配置到 app 模块
    from app import app, configure
    configure(cfg=cfg, cfg_path=cfg_path)

    import uvicorn
    uvicorn.run(app, host=args.host, port=port)


if __name__ == "__main__":
    main()
