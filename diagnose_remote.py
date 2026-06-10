#!/usr/bin/env python3
"""
diagnose_remote.py — remote/ 子项目本机链路在线诊断

适配「全本机 + 电脑模拟路由器」拓扑：
    手机登录游戏 → Wi-Fi → 电脑(Windows 移动热点/ICS) → 互联网 → 游戏服务器
    手机流量经过电脑网卡 → extractor 嗅探共享网卡 → POST /register/push → 本机 relay

逐项检查，帮你一眼确认「依赖就绪? relay 可达? 路由器模拟开了没? 游戏服务器通不通?」。

用法：
    python diagnose_remote.py
日志：
    logs/diagnose_remote_<YYYYMMDD_HHMMSS>.log

退出码：有 FAIL → 1；否则 → 0（WARN/SKIP 不算失败）。

安全：绝不把 api_token / auth_token / handshake_blob 等敏感值完整写入日志，
      只打印长度或前 4 位 + ***。

Python 3.8+ 兼容。
"""
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 日志初始化 — 同时输出到终端和文件（格式对齐 test_remote.py）
# ---------------------------------------------------------------------------
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_FILE = os.path.join(_LOG_DIR, "diagnose_remote_{}.log".format(_TIMESTAMP))

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_root_logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_root_logger.addHandler(_console_handler)

log = logging.getLogger("diagnose_remote")

# ---------------------------------------------------------------------------
# 结果收集 — 四态 PASS / WARN / FAIL / SKIP
# ---------------------------------------------------------------------------
_results = []  # list of (label, status, detail)


def _record(label, status, detail=""):
    _results.append((label, status, detail))
    line = "[{}] {}".format(status, label)
    if detail:
        line += ": " + detail
    if status == "PASS":
        log.info(line)
    elif status == "WARN":
        log.warning(line)
    elif status == "FAIL":
        log.error(line)
    else:  # SKIP
        log.info(line)


def _mask(value):
    """脱敏：只露前 4 位 + ***，或仅长度。"""
    if value is None:
        return "<none>"
    s = str(value)
    if not s:
        return "<empty>"
    if len(s) <= 4:
        return "***(len={})".format(len(s))
    return "{}***(len={})".format(s[:4], len(s))


def _load_yaml(path):
    """读取 yaml 配置，失败抛异常由调用方处理。"""
    import yaml  # 局部 import，B 项未装 yaml 时不影响其它检查
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_EXTRACTOR_CFG = os.path.join(os.path.dirname(__file__), "remote", "extractor", "config.yaml")
_RELAY_CFG = os.path.join(os.path.dirname(__file__), "remote", "relay", "config.yaml")


# ===========================================================================
# A. relay 依赖
# ===========================================================================
def check_a_relay_deps():
    label = "A.relay依赖(fastapi/uvicorn/pyyaml)"
    try:
        missing = []
        for mod in ("fastapi", "uvicorn", "yaml"):
            try:
                __import__(mod)
            except ImportError:
                missing.append("pyyaml" if mod == "yaml" else mod)
        if missing:
            _record(label, "FAIL", "缺少: {}（pip install {}）".format(
                ", ".join(missing), " ".join(missing)))
        else:
            _record(label, "PASS", "fastapi / uvicorn / pyyaml 均就绪")
    except Exception as exc:
        _record(label, "FAIL", "{}: {}".format(type(exc).__name__, exc))


# ===========================================================================
# B. extractor 抓包依赖
# ===========================================================================
def check_b_extractor_deps():
    label = "B.extractor抓包依赖(requests/yaml/scapy/Npcap)"
    try:
        missing = []
        for mod in ("requests", "yaml"):
            try:
                __import__(mod)
            except ImportError:
                missing.append("pyyaml" if mod == "yaml" else mod)
        if missing:
            _record(label, "FAIL", "缺少基础依赖: {}".format(", ".join(missing)))
            return

        try:
            __import__("scapy")
            have_scapy = True
        except ImportError:
            have_scapy = False

        if not have_scapy:
            _record(label, "FAIL",
                    "缺少 scapy（pip install scapy）；Windows 被动嗅探无法工作")
            return

        # Windows 下检查 Npcap 驱动
        if sys.platform.startswith("win"):
            npcap_dir = os.path.exists(r"C:\Windows\System32\Npcap")
            wpcap_dll = os.path.exists(r"C:\Windows\System32\wpcap.dll")
            if npcap_dir or wpcap_dll:
                _record(label, "PASS", "scapy + Npcap 驱动均就绪")
            else:
                _record(label, "WARN",
                        "scapy 已装但未检测到 Npcap 驱动；请安装 Npcap: https://npcap.com")
        else:
            _record(label, "PASS", "scapy 就绪（非 Windows，使用 tcpdump 路径）")
    except Exception as exc:
        _record(label, "FAIL", "{}: {}".format(type(exc).__name__, exc))


# ===========================================================================
# C. relay /state 可达性
# ===========================================================================
def check_c_relay_reachable():
    label = "C.relay /state 可达性"
    try:
        try:
            import requests  # type: ignore
        except ImportError:
            _record(label, "WARN", "未安装 requests，无法发起 HTTP 请求")
            return

        try:
            cfg = _load_yaml(_EXTRACTOR_CFG)
        except Exception as exc:
            _record(label, "WARN", "无法读取 extractor/config.yaml: {}".format(exc))
            return

        relay_url = (cfg.get("relay_url") or "").strip()
        api_token = (cfg.get("api_token") or "").strip()
        log.info("    relay_url=%s  api_token=%s", relay_url or "<empty>", _mask(api_token))

        if (not relay_url) or ("your-relay-server" in relay_url):
            _record(label, "WARN",
                    "relay_url 仍是占位符，全本机拓扑应改为 http://127.0.0.1:8000")
            return

        if ("127.0.0.1" not in relay_url) and ("localhost" not in relay_url):
            _record(label, "WARN",
                    "检测到非本机地址 {}，当前拓扑 relay 与 extractor 同机，建议用 127.0.0.1".format(relay_url))
            return

        url = relay_url.rstrip("/") + "/state"
        try:
            resp = requests.get(url, params={"token": api_token}, timeout=3)
        except requests.exceptions.ConnectionError:
            _record(label, "WARN", "无法连接 {}，relay 未启动? 请先跑 remote/relay/main.py".format(url))
            return

        if resp.status_code == 200:
            try:
                data = resp.json()
                phase = data.get("phase", "<no phase>") if isinstance(data, dict) else "<not dict>"
            except Exception:
                phase = "<non-json body>"
            _record(label, "PASS", "200 OK，relay phase={}".format(phase))
        elif resp.status_code == 401:
            _record(label, "WARN",
                    "401 未授权，extractor/config.yaml 的 api_token 与 relay/config.yaml 不一致")
        else:
            _record(label, "WARN", "意外状态码 {}".format(resp.status_code))
    except Exception as exc:
        _record(label, "FAIL", "{}: {}".format(type(exc).__name__, exc))


# ===========================================================================
# D. 路由器模拟自检（核心）
# ===========================================================================
def check_d_router_emulation():
    label = "D.路由器模拟自检(移动热点/ICS 网卡)"
    try:
        if not sys.platform.startswith("win"):
            _record(label, "SKIP", "非 Windows，跳过移动热点/ICS 检测")
            return
        try:
            proc = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            _record(label, "SKIP", "未找到 ipconfig 命令")
            return

        output = (proc.stdout or "") + (proc.stderr or "")
        if "192.168.137.1" in output:
            _record(label, "PASS",
                    "检测到 192.168.137.1，移动热点/ICS 已启用；"
                    "请确认手机已连此热点，extractor 需嗅探该共享网卡")
        else:
            _record(label, "WARN",
                    "未检测到 192.168.137.1，电脑可能未开启移动热点/ICS。"
                    "请在 Windows 设置→移动热点→开启，并让手机连接，"
                    "否则游戏流量不经过本机网卡，extractor 抓不到包")
    except Exception as exc:
        _record(label, "FAIL", "{}: {}".format(type(exc).__name__, exc))


# ===========================================================================
# E. 游戏服务器 TCP 连通（参考项）
# ===========================================================================
def check_e_game_server():
    label = "E.游戏服务器 TCP 连通(参考项)"
    try:
        try:
            cfg = _load_yaml(_RELAY_CFG)
        except Exception as exc:
            _record(label, "WARN", "无法读取 relay/config.yaml: {}".format(exc))
            return

        ip = (cfg.get("game_server_ip") or "").strip()
        port = cfg.get("game_server_port") or 7777
        try:
            port = int(port)
        except (TypeError, ValueError):
            _record(label, "WARN", "game_server_port 非法: {}".format(port))
            return

        if not ip:
            _record(label, "WARN", "relay/config.yaml 未配置 game_server_ip")
            return

        log.info("    尝试连接游戏服务器 %s:%d", ip, port)
        try:
            sock = socket.create_connection((ip, port), timeout=5)
            sock.close()
            _record(label, "PASS", "{}:{} TCP 可达".format(ip, port))
        except (socket.timeout, OSError) as exc:
            _record(label, "WARN",
                    "{}:{} 不可达（{}）；本机拓扑下走被动嗅探，此项非必需".format(ip, port, exc))
    except Exception as exc:
        _record(label, "FAIL", "{}: {}".format(type(exc).__name__, exc))


# ===========================================================================
# 主入口
# ===========================================================================
def main():
    log.info("diagnose_remote.py 开始，日志: %s", _LOG_FILE)
    log.info("拓扑: 全本机 + 电脑模拟路由器（移动热点/ICS）")

    check_a_relay_deps()
    check_b_extractor_deps()
    check_c_relay_reachable()
    check_d_router_emulation()
    check_e_game_server()

    n_pass = sum(1 for _, s, _ in _results if s == "PASS")
    n_warn = sum(1 for _, s, _ in _results if s == "WARN")
    n_fail = sum(1 for _, s, _ in _results if s == "FAIL")
    n_skip = sum(1 for _, s, _ in _results if s == "SKIP")

    log.info("=" * 50)
    log.info("Results: %d PASS / %d WARN / %d FAIL / %d SKIP",
             n_pass, n_warn, n_fail, n_skip)

    if n_fail > 0:
        log.info("Failed checks:")
        for label, status, detail in _results:
            if status == "FAIL":
                log.info("  [FAIL] %s: %s", label, detail)

    log.info("日志已写入: %s", _LOG_FILE)
    sys.exit(1 if n_fail > 0 else 0)


if __name__ == "__main__":
    main()
