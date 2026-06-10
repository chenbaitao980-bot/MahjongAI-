#!/usr/bin/env python3
"""
test_remote.py — 一键测试 remote/ 子项目
用法：python test_remote.py
日志：logs/test_remote_<timestamp>.log
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import textwrap
from collections import namedtuple
from datetime import datetime

# ---------------------------------------------------------------------------
# stdout/stderr 容错 — 控制台可能是 cp936/GBK，避免 UnicodeEncodeError 崩溃
# (Python 3.7+ reconfigure; 失败忽略，纯加固，不改变正常行为)
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 日志初始化 — 同时输出到终端和文件
# ---------------------------------------------------------------------------
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_FILE = os.path.join(_LOG_DIR, f"test_remote_{_TIMESTAMP}.log")

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_root_logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_root_logger.addHandler(_console_handler)

log = logging.getLogger("test_remote")

# ---------------------------------------------------------------------------
# 结果收集
# ---------------------------------------------------------------------------
_results: list[tuple[str, bool, str]] = []  # (label, passed, msg)


def _record(suite: str, name: str, passed: bool, err: str = ""):
    label = f"{suite}.{name}"
    _results.append((label, passed, err))
    if passed:
        log.info("[PASS] %s", label)
    else:
        log.error("[FAIL] %s: %s", label, err)


def _run(suite: str, name: str, fn):
    try:
        fn()
        _record(suite, name, True)
    except AssertionError as exc:
        _record(suite, name, False, str(exc))
    except Exception as exc:
        _record(suite, name, False, f"{type(exc).__name__}: {exc}")


# ===========================================================================
# Suite 1 — StateStore 单元测试
# ===========================================================================

def _suite_state_store():
    suite = "StateStore"
    log.info("=== %s ===", suite)

    # 动态导入，确保能找到模块
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "remote", "relay"))
    from state_store import StateStore  # type: ignore

    # test_state_store_idle
    def test_idle():
        ss = StateStore()
        snap = ss.get_snapshot()
        assert snap == {"phase": "idle"}, f"expected idle, got {snap}"

    _run(suite, "test_state_store_idle", test_idle)

    # test_state_store_push
    def test_push():
        ss = StateStore()
        payload = {"phase": "playing", "hand": ["1m"]}
        ss.on_push(payload)
        snap = ss.get_snapshot()
        assert snap == payload, f"expected {payload}, got {snap}"

    _run(suite, "test_state_store_push", test_push)

    # test_state_store_timeout
    def test_timeout():
        ss = StateStore()
        ss.last_push_time = time.time() - 61.0  # 61 秒前
        result = ss.should_use_game_client()
        assert result is True, "expected True when push is stale"

    _run(suite, "test_state_store_timeout", test_timeout)

    # test_state_store_fresh
    def test_fresh():
        ss = StateStore()
        ss.last_push_time = time.time()  # 刚刚推送
        result = ss.should_use_game_client()
        assert result is False, "expected False when push is fresh"

    _run(suite, "test_state_store_fresh", test_fresh)


# ===========================================================================
# Suite 2 — TokenExtractor 单元测试
# ===========================================================================

def _suite_token_extractor():
    suite = "TokenExtractor"
    log.info("=== %s ===", suite)

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "remote", "extractor"))
        # token_extractor.py 会导入 stable.protocol，确保项目根在 path 中
        _project_root = os.path.dirname(__file__)
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from token_extractor import TokenExtractor  # type: ignore
    except ImportError as exc:
        log.warning("[SKIP] TokenExtractor 导入失败（缺少依赖）: %s", exc)
        for name in [
            "test_extract_handshake_blob",
            "test_extract_auth_token",
            "test_ignore_wrong_direction",
            "test_callback_triggered",
        ]:
            _results.append((f"{suite}.{name}", None, "SKIP"))
            log.info("[SKIP] %s.%s", suite, name)
        return

    # fake ProtocolMessage
    FakeMsg = namedtuple("FakeMsg", ["msg_type", "direction", "raw_hex", "pay_len"])

    def _make_hex(header_bytes: bytes, payload: bytes) -> str:
        return (header_bytes + payload).hex()

    _HEADER = bytes(12)  # 12 字节全零头

    # test_extract_handshake_blob
    def test_handshake():
        ext = TokenExtractor()
        payload = bytes(range(19))  # 19 字节 payload
        raw = _make_hex(_HEADER, payload)
        msg = FakeMsg(msg_type=0x0001, direction="C->S", raw_hex=raw, pay_len=19)
        ext.feed(msg)
        assert ext.handshake_blob is not None, "handshake_blob should be extracted"
        assert len(ext.handshake_blob) == 19, f"expected 19 bytes, got {len(ext.handshake_blob)}"

    _run(suite, "test_extract_handshake_blob", test_handshake)

    # test_extract_auth_token
    def test_auth_token():
        ext = TokenExtractor()
        rand4 = bytes([0xAA, 0xBB, 0xCC, 0xDD])
        token12 = bytes(range(12, 24))  # 12 bytes token
        payload = rand4 + token12  # total 16 bytes
        raw = _make_hex(_HEADER, payload)
        msg = FakeMsg(msg_type=0x0006, direction="C->S", raw_hex=raw, pay_len=16)
        ext.feed(msg)
        assert ext.auth_token_12b is not None, "auth_token_12b should be extracted"
        assert ext.auth_token_12b == token12, (
            f"expected payload[4:16], got {ext.auth_token_12b.hex()}"
        )

    _run(suite, "test_extract_auth_token", test_auth_token)

    # test_ignore_wrong_direction
    def test_wrong_dir():
        ext = TokenExtractor()
        payload = bytes(range(19))
        raw = _make_hex(_HEADER, payload)
        msg = FakeMsg(msg_type=0x0001, direction="S->C", raw_hex=raw, pay_len=19)
        ext.feed(msg)
        assert ext.handshake_blob is None, "S->C should be ignored"

    _run(suite, "test_ignore_wrong_direction", test_wrong_dir)

    # test_callback_triggered
    def test_callback():
        callback_calls: list = []

        def _on_reg(blob, tok):
            callback_calls.append((blob, tok))

        ext = TokenExtractor(on_registered=_on_reg)

        # Feed handshake msg
        hs_payload = bytes(range(19))
        hs_raw = _make_hex(_HEADER, hs_payload)
        hs_msg = FakeMsg(msg_type=0x0001, direction="C->S", raw_hex=hs_raw, pay_len=19)
        ext.feed(hs_msg)

        # Feed auth token msg
        rand4 = bytes(4)
        tok12 = bytes(range(12))
        auth_payload = rand4 + tok12
        auth_raw = _make_hex(_HEADER, auth_payload)
        auth_msg = FakeMsg(msg_type=0x0006, direction="C->S", raw_hex=auth_raw, pay_len=16)
        ext.feed(auth_msg)

        assert len(callback_calls) == 1, (
            f"callback should be called once, got {len(callback_calls)}"
        )

    _run(suite, "test_callback_triggered", test_callback)


# ===========================================================================
# Suite 3 — Relay API 集成测试（启动真实服务器）
# ===========================================================================

def _suite_relay_api():
    suite = "RelayAPI"
    log.info("=== %s ===", suite)

    try:
        import requests  # type: ignore
    except ImportError:
        log.warning("[SKIP] requests 未安装，跳过 Suite 3")
        return

    # 生成临时 config
    tmp_cfg_path = os.path.join(os.path.dirname(__file__), "remote", "relay", "test_config_tmp.yaml")
    cfg_content = textwrap.dedent("""\
        api_token: "test_secret"
        game_server_ip: "127.0.0.1"
        game_server_port: 7777
        handshake_blob: ""
        auth_token_12b: ""
    """)
    with open(tmp_cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg_content)

    relay_main = os.path.join(os.path.dirname(__file__), "remote", "relay", "main.py")
    port = 18765
    base_url = f"http://127.0.0.1:{port}"

    proc = None
    try:
        log.info("启动 relay 子进程: port=%d", port)
        proc = subprocess.Popen(
            [
                sys.executable,
                relay_main,
                "--config", tmp_cfg_path,
                "--host", "127.0.0.1",
                "--port", str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 等待服务就绪（最多 10 秒）
        ready = False
        for _ in range(20):
            time.sleep(0.5)
            try:
                resp = requests.get(f"{base_url}/state", params={"token": "test_secret"}, timeout=2)
                if resp.status_code in (200, 401):
                    ready = True
                    break
            except Exception:
                pass

        if not ready:
            # 读取子进程输出以便诊断
            try:
                out, err = proc.communicate(timeout=2)
                log.error("relay stdout: %s", out.decode(errors="replace"))
                log.error("relay stderr: %s", err.decode(errors="replace"))
            except Exception:
                pass
            for name in [
                "test_state_unauthorized",
                "test_state_idle",
                "test_register_valid",
                "test_register_unauthorized",
                "test_push_and_state",
            ]:
                _record(suite, name, False, "relay 服务器未能在 10 秒内就绪")
            return

        log.info("relay 服务器就绪")

        # test_state_unauthorized
        def test_state_unauth():
            r = requests.get(f"{base_url}/state", params={"token": "wrong"}, timeout=5)
            assert r.status_code == 401, f"expected 401, got {r.status_code}"

        _run(suite, "test_state_unauthorized", test_state_unauth)

        # test_state_idle
        def test_state_idle():
            r = requests.get(f"{base_url}/state", params={"token": "test_secret"}, timeout=5)
            assert r.status_code == 200, f"expected 200, got {r.status_code}"
            data = r.json()
            assert data.get("phase") == "idle", f"expected phase=idle, got {data}"

        _run(suite, "test_state_idle", test_state_idle)

        # test_register_valid
        def test_register_valid():
            r = requests.post(
                f"{base_url}/register",
                json={
                    "api_token": "test_secret",
                    "handshake_blob": "deadbeef",
                    "auth_token_12b": "aabbccddeeff00112233445566778899",
                },
                timeout=5,
            )
            assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
            data = r.json()
            assert data.get("status") == "ok", f"expected status=ok, got {data}"

        _run(suite, "test_register_valid", test_register_valid)

        # test_register_unauthorized
        def test_register_unauth():
            r = requests.post(
                f"{base_url}/register",
                json={
                    "api_token": "wrong_token",
                    "handshake_blob": "deadbeef",
                    "auth_token_12b": "aabbccddeeff001122334455",
                },
                timeout=5,
            )
            assert r.status_code == 401, f"expected 401, got {r.status_code}"

        _run(suite, "test_register_unauthorized", test_register_unauth)

        # test_push_and_state
        def test_push_and_state():
            snapshot = {"phase": "playing", "hand": ["1m", "2m"]}
            r = requests.post(
                f"{base_url}/push",
                json={"api_token": "test_secret", "snapshot": snapshot},
                timeout=5,
            )
            assert r.status_code == 200, f"push failed: {r.status_code} {r.text}"

            r2 = requests.get(f"{base_url}/state", params={"token": "test_secret"}, timeout=5)
            assert r2.status_code == 200, f"state failed: {r2.status_code}"
            data = r2.json()
            assert data == snapshot, f"expected {snapshot}, got {data}"

        _run(suite, "test_push_and_state", test_push_and_state)

    except Exception as exc:
        log.warning("[SKIP] Suite 3 启动失败（可能缺少依赖）: %s", exc)
        for name in [
            "test_state_unauthorized",
            "test_state_idle",
            "test_register_valid",
            "test_register_unauthorized",
            "test_push_and_state",
        ]:
            _results.append((f"{suite}.{name}", None, "SKIP"))
            log.info("[SKIP] %s.%s", suite, name)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info("relay 子进程已关闭")
        if os.path.isfile(tmp_cfg_path):
            os.remove(tmp_cfg_path)
            log.info("临时配置已删除: %s", tmp_cfg_path)


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    log.info("test_remote.py 开始，日志: %s", _LOG_FILE)

    _suite_state_store()
    _suite_token_extractor()
    _suite_relay_api()

    # 汇总
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok is True)
    skipped = sum(1 for _, ok, _ in _results if ok is None)
    failed = total - passed - skipped

    log.info("=" * 50)
    log.info("Results: %d/%d passed  (%d skipped, %d failed)", passed, total - skipped, skipped, failed)

    if failed > 0:
        log.info("Failed tests:")
        for label, ok, err in _results:
            if ok is False:
                log.info("  [FAIL] %s: %s", label, err)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
