#!/usr/bin/env python3
"""
bootstrap_remote_config.py — 幂等生成/同步 remote/ 两个 config.yaml

作用（全本机 + 电脑模拟路由器拓扑）：
  - 读取 remote/relay/config.yaml 和 remote/extractor/config.yaml
  - 若 relay 的 api_token 为空或仍是占位符 change-me-shared-secret，
    用 secrets.token_hex(12) 随机生成新 token；否则沿用现有真 token（幂等）
  - 把该 api_token 同步写进 relay + extractor 两个 config
  - 设 extractor 的 relay_url = http://127.0.0.1:8000
  - 保留两个 config 的其它字段，用 yaml.safe_dump 写回（允许丢注释）
  - stdout 打印最终使用的 api_token 明文（本地工具，方便复制到浏览器）

退出码：0 成功；非 0 失败（找不到 config 文件等）。
Python 3.8+，文件读写 encoding=utf-8。
"""
import os
import secrets
import sys

_PLACEHOLDER = "change-me-shared-secret"
_RELAY_URL = "http://127.0.0.1:8000"

_HERE = os.path.dirname(os.path.abspath(__file__))
_RELAY_CFG = os.path.join(_HERE, "remote", "relay", "config.yaml")
_EXTRACTOR_CFG = os.path.join(_HERE, "remote", "extractor", "config.yaml")


def _load_yaml(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dump_yaml(path, data):
    import yaml
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def main():
    try:
        import yaml  # noqa: F401  仅用于尽早暴露缺依赖
    except ImportError:
        print("[ERROR] missing dependency pyyaml. Run: pip install pyyaml")
        return 1

    for path, name in ((_RELAY_CFG, "relay"), (_EXTRACTOR_CFG, "extractor")):
        if not os.path.isfile(path):
            print("[ERROR] config not found ({}): {}".format(name, path))
            return 1

    try:
        relay_cfg = _load_yaml(_RELAY_CFG)
        extractor_cfg = _load_yaml(_EXTRACTOR_CFG)
    except Exception as exc:
        print("[ERROR] failed to read config: {}: {}".format(type(exc).__name__, exc))
        return 1

    existing = (relay_cfg.get("api_token") or "").strip()
    if (not existing) or existing == _PLACEHOLDER:
        api_token = secrets.token_hex(12)
        generated = True
    else:
        api_token = existing
        generated = False

    relay_cfg["api_token"] = api_token
    extractor_cfg["api_token"] = api_token
    extractor_cfg["relay_url"] = _RELAY_URL

    try:
        _dump_yaml(_RELAY_CFG, relay_cfg)
        _dump_yaml(_EXTRACTOR_CFG, extractor_cfg)
    except Exception as exc:
        print("[ERROR] failed to write config: {}: {}".format(type(exc).__name__, exc))
        return 1

    print("API_TOKEN={}".format(api_token))
    if generated:
        print("[ok] generated a new shared api_token and synced relay + extractor.")
    else:
        print("[ok] reused existing api_token and synced relay + extractor (idempotent).")
    print("[ok] extractor relay_url set to {}".format(_RELAY_URL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
