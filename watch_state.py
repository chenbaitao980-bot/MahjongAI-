#!/usr/bin/env python3
"""
watch_state.py — 实时轮询打印 relay /state 牌局快照

读 remote/extractor/config.yaml 的 relay_url + api_token（bootstrap 后已就绪），
每 2 秒 GET relay_url+/state，snapshot 内容变化时才打印（带时间戳 + phase + 关键字段）。

  - ConnectionError：relay 还没起来，连不上时每 5s 提示一次（不刷屏），继续重试
  - 401：api_token 不匹配，提示重跑 bootstrap 并退出
  - Ctrl+C：优雅退出打印 "已停止"

Python 3.8+。
"""
import json
import os
import sys
from datetime import datetime

# stdout/stderr 容错 — 控制台可能是 cp936/GBK，避免 UnicodeEncodeError 崩溃
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXTRACTOR_CFG = os.path.join(_HERE, "remote", "extractor", "config.yaml")

_POLL_INTERVAL = 2.0      # 秒
_WAIT_HINT_EVERY = 5.0    # 连不上时提示间隔（秒）


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _load_config():
    import yaml
    with open(_EXTRACTOR_CFG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    relay_url = (cfg.get("relay_url") or "").strip().rstrip("/")
    api_token = (cfg.get("api_token") or "").strip()
    return relay_url, api_token


def _format_snapshot(snap):
    """把 snapshot dict 格式化成简要可读行。"""
    if not isinstance(snap, dict):
        return "phase=<not-dict> " + json.dumps(snap, ensure_ascii=False)
    phase = snap.get("phase", "<no-phase>")
    line = "phase={}".format(phase)
    keys = ("hand", "discards", "melds", "draw", "last_discard", "round", "seat")
    shown = []
    for k in keys:
        if k in snap:
            v = snap[k]
            shown.append("{}={}".format(k, json.dumps(v, ensure_ascii=False)))
    if shown:
        return line + " " + " ".join(shown)
    # 没有已知关键字段时打印整个 dict 的紧凑 json
    return line + " " + json.dumps(snap, ensure_ascii=False, sort_keys=True)


def main():
    try:
        import requests
    except ImportError:
        print("[ERROR] missing dependency requests. Run: pip install requests")
        return 1
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("[ERROR] missing dependency pyyaml. Run: pip install pyyaml")
        return 1

    try:
        relay_url, api_token = _load_config()
    except Exception as exc:
        print("[ERROR] failed to read extractor config: {}: {}".format(
            type(exc).__name__, exc))
        return 1

    if not relay_url:
        print("[ERROR] relay_url empty, run bootstrap_remote_config.py first")
        return 1

    url = relay_url + "/state"
    print("[{}] watching {} (every {:.0f}s, Ctrl+C to stop)".format(
        _now(), url, _POLL_INTERVAL))

    import time

    last_key = None          # 上次打印的 snapshot 规范化字符串
    waiting = False          # 是否处于连不上状态
    last_wait_hint = 0.0     # 上次打印等待提示的时间

    try:
        while True:
            try:
                resp = requests.get(url, params={"token": api_token}, timeout=3)
            except requests.exceptions.ConnectionError:
                now = time.monotonic()
                if (not waiting) or (now - last_wait_hint >= _WAIT_HINT_EVERY):
                    print("[{}] 等待 relay 启动...".format(_now()))
                    last_wait_hint = now
                waiting = True
                time.sleep(_POLL_INTERVAL)
                continue
            except requests.exceptions.RequestException as exc:
                print("[{}] 请求异常: {}: {}".format(_now(), type(exc).__name__, exc))
                time.sleep(_POLL_INTERVAL)
                continue

            if waiting:
                print("[{}] relay 已连接".format(_now()))
                waiting = False

            if resp.status_code == 401:
                print("[{}] api_token 不匹配，请重跑 bootstrap_remote_config.py".format(_now()))
                return 1
            if resp.status_code != 200:
                print("[{}] 意外状态码 {}".format(_now(), resp.status_code))
                time.sleep(_POLL_INTERVAL)
                continue

            try:
                snap = resp.json()
            except Exception:
                snap = {"raw": resp.text}

            key = json.dumps(snap, ensure_ascii=False, sort_keys=True)
            if key != last_key:
                last_key = key
                print("[{}] {}".format(_now(), _format_snapshot(snap)))

            time.sleep(_POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n已停止")
        return 0


if __name__ == "__main__":
    sys.exit(main())
