"""
main.py — relay 多模式入口

支持三种独立模式，各自监听不同端口：
  --mode hotspot   :8000  共享热点模式，接收PC端extractor推送
  --mode vpn       :8001  VPN隧道模式，接收云端extractor推送
  --mode noconfig  :8002  无配置模式，SRS spectator直连游戏服务器

也可一次性启动全部三种模式：
  python main.py --all

用法:
  python main.py --mode hotspot
  python main.py --mode vpn --config custom_vpn.yaml
  python main.py --all
"""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import signal
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
)
_LOGGER = logging.getLogger("remote.relay")


def _attach_file_handler(logfile: str):
    """挂载文件日志 handler"""
    import logging as _l
    root = _l.getLogger()
    for h in root.handlers:
        if isinstance(h, _l.FileHandler) and \
                getattr(h, "baseFilename", None) == os.path.abspath(logfile):
            return
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    fh = _l.FileHandler(logfile, mode="a", encoding="utf-8")
    fh.setLevel(_l.INFO)
    fh.setFormatter(_l.Formatter(_LOG_FORMAT))
    root.addHandler(fh)


# ─── 模式定义 ────────────────────────────────────────────────

MODE_CONFIGS = {
    "hotspot": {
        "title": "热点模式 (Hotspot)",
        "port": 8000,
        "config": os.path.join(os.path.dirname(__file__), "config_hotspot.yaml"),
        "desc": "手机连PC共享热点，PC运行extractor抓包推送到此端口",
    },
    "vpn": {
        "title": "VPN模式 (Phone VPN)",
        "port": 8001,
        "config": os.path.join(os.path.dirname(__file__), "config_vpn.yaml"),
        "desc": "手机配置IPSec VPN连云端，云端ECS抓包推送到此端口",
    },
    "noconfig": {
        "title": "无配置模式 (No-Config / SRS Spectator)",
        "port": 8002,
        "config": os.path.join(os.path.dirname(__file__), "config_noconfig.yaml"),
        "desc": "SRS旁观协议直连游戏服务器，手机无需任何配置",
    },
    "cloud": {
        "title": "云端玩家模式 (Cloud Player)",
        "port": 8003,
        "config": os.path.join(os.path.dirname(__file__), "config_cloud.yaml"),
        "desc": "连一次热点抓凭证，之后任意网络云端以玩家身份接收手牌",
    },
}


def load_config(path: str) -> dict:
    """加载 YAML 配置"""
    import yaml
    if not os.path.isfile(path):
        _LOGGER.warning("配置文件不存在: %s，使用默认值", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def start_single_mode(mode: str, config_path: str = "", host: str = "0.0.0.0", port: int = 0):
    """启动单个模式"""
    import uvicorn
    from core import RelayApp

    mode_info = MODE_CONFIGS.get(mode)
    if not mode_info:
        _LOGGER.error("未知模式: %s。可选: %s", mode, list(MODE_CONFIGS.keys()))
        return

    # 确定配置文件和端口
    cfg_path = config_path or mode_info["config"]
    if port == 0:
        port = mode_info["port"]

    cfg = load_config(cfg_path)
    # 注入 mode 和 port（如果配置文件未设置）
    cfg.setdefault("mode", mode)
    cfg.setdefault("port", port)

    # 设置日志文件
    logfile = os.path.join(os.path.dirname(__file__), f"relay_{mode}.log")
    _attach_file_handler(logfile)

    # 创建 RelayApp 实例
    relay = RelayApp(cfg=cfg, cfg_path=cfg_path, mode=mode, port=port)

    _LOGGER.info("=" * 50)
    _LOGGER.info("启动 %s — %s", mode_info["title"], mode_info["desc"])
    _LOGGER.info("端口: %d | 配置: %s | 日志: %s", port, cfg_path, logfile)

    # 报告凭证状态
    hs = cfg.get("handshake_blob", "")
    at = cfg.get("auth_token_12b", "")
    sid = cfg.get("srs_sessionid", "")
    if hs and at:
        _LOGGER.info("[凭证] 已有持久化凭证: hs=%d bytes, auth=%d bytes, srs_sid=%s",
                     len(hs) // 2, len(at) // 2, "present" if sid else "absent")
    else:
        _LOGGER.info("[凭证] 无持久化凭证，需要通过 extractor 注册")
    _LOGGER.info("=" * 50)

    uvicorn.run(relay.app, host=host, port=port)


def _run_mode_worker(mode: str, host: str):
    """子进程入口（模块级函数，可被 Windows spawn pickle）

    必须是模块级函数：Windows multiprocessing 默认使用 spawn 启动方式，
    需要 pickle target 函数。嵌套局部函数无法被 pickle，会抛
    AttributeError: Can't get local object 'start_all_modes.<locals>._run_mode'。

    所有依赖均从可 pickle 的参数（mode/host 字符串）和模块级常量
    MODE_CONFIGS 获取，不依赖闭包。
    """
    # spawn 子进程需要重新确保脚本目录在 sys.path，否则找不到 core 模块
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    info = MODE_CONFIGS[mode]
    # 子进程重新设置日志
    logfile = os.path.join(os.path.dirname(__file__), f"relay_{mode}.log")
    _attach_file_handler(logfile)

    from core import RelayApp
    import uvicorn

    cfg_path = info["config"]
    port = info["port"]
    cfg = load_config(cfg_path)
    cfg.setdefault("mode", mode)
    cfg.setdefault("port", port)

    relay = RelayApp(cfg=cfg, cfg_path=cfg_path, mode=mode, port=port)
    _LOGGER.info("[子进程] %s 启动: port=%d", mode.upper(), port)

    # 抑制 uvicorn 的重复日志
    uvicorn.run(relay.app, host=host, port=port, log_level="warning")


def start_all_modes(host: str = "0.0.0.0"):
    """同时启动全部三种模式（使用多进程）"""
    processes = []
    modes = list(MODE_CONFIGS.keys())

    print("=" * 60)
    print("  MahjongAI Remote Relay — 全部模式")
    print("=" * 60)

    for mode in modes:
        info = MODE_CONFIGS[mode]
        print(f"  [{mode.upper()}] :{info['port']} — {info['desc']}")
        p = multiprocessing.Process(
            target=_run_mode_worker, args=(mode, host), daemon=True
        )
        p.start()
        processes.append(p)
        time.sleep(0.5)  # 错开启动，避免日志混淆

    print("=" * 60)
    print(f"  全部 {len(processes)} 个 relay 实例已启动")
    print(f"  按 Ctrl+C 停止全部")
    print("=" * 60)

    # 等待子进程
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\n正在停止全部 relay 实例...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join(timeout=5)
        print("已停止。")


def main():
    parser = argparse.ArgumentParser(
        description="MahjongAI Remote Relay — 多模式启动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --mode hotspot          # 仅启动热点模式 :8000
  python main.py --mode vpn              # 仅启动VPN模式 :8001
  python main.py --mode noconfig         # 仅启动无配置模式 :8002
  python main.py --all                   # 同时启动全部三种模式
  python main.py --mode hotspot --port 9000   # 自定义端口
        """,
    )
    parser.add_argument(
        "--mode",
        choices=list(MODE_CONFIGS.keys()),
        default=None,
        help="启动指定模式（不指定则启动全部）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="同时启动全部三种模式",
    )
    parser.add_argument(
        "--config",
        default="",
        help="自定义配置文件路径（覆盖默认配置）",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="监听地址（默认 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="监听端口（默认使用模式默认端口）",
    )
    args = parser.parse_args()

    if args.all:
        start_all_modes(host=args.host)
    elif args.mode is not None:
        start_single_mode(mode=args.mode, config_path=args.config,
                         host=args.host, port=args.port)
    else:
        # 无 --mode 且无 --all：如果指定了 --port 或 --config，默认 hotspot 模式
        if args.port > 0 or args.config:
            _LOGGER.info("未指定模式，默认使用热点模式")
            start_single_mode(mode="hotspot", config_path=args.config,
                             host=args.host, port=args.port)
        else:
            start_all_modes(host=args.host)


if __name__ == "__main__":
    main()
