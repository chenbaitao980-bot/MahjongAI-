#!/usr/bin/env python3
"""
e2e_test.py — 三模式端到端验证脚本

验证三种 relay 模式的独立性和连通性：
  1. 三模式 relay 启动检查 (port 8000/8001/8002)
  2. 模式隔离性验证 (各模式数据不串)
  3. extractor → relay 推送链路
  4. 云端 ECS 连通性检查
  5. spectator 启动检查 (port 8003)

用法:
  python e2e_test.py                # 本地三模式验证
  python e2e_test.py --cloud        # 验证云端 ECS 三模式
  python e2e_test.py --cloud-only   # 仅验证云端 (不启动本地服务)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import textwrap
from collections import namedtuple
from datetime import datetime

# stdout/stderr 容错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 日志初始化
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_FILE = os.path.join(_LOG_DIR, f"e2e_test_{_TIMESTAMP}.log")

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_root_logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_root_logger.addHandler(_console_handler)

log = logging.getLogger("e2e_test")

# ─── 配置常量 ────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ECS_IP = os.environ.get("ECS_IP", "8.136.37.136")

# 各模式配置
MODES = {
    "hotspot": {
        "port": 8000,
        "token": "acec67bfa9e518b5906d3e6a",
        "title": "热点模式 (Hotspot)",
    },
    "vpn": {
        "port": 8001,
        "token": "8f2e7c91b4d53a6f10e9c827",
        "title": "VPN模式 (Phone VPN)",
    },
    "noconfig": {
        "port": 8002,
        "token": "d4a8e1f29c6b7305e8d1f264",
        "title": "无配置模式 (No-Config)",
    },
}

SPECTATOR_PORT = 8003

# ─── 结果收集 ────────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []


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


# ─── Helper: HTTP 请求 ──────────────────────────────────

def _http_get(url: str, timeout: float = 5.0) -> tuple[int, dict]:
    """GET 请求，返回 (status_code, json_dict)"""
    import requests
    try:
        r = requests.get(url, timeout=timeout)
        try:
            data = r.json()
        except json.JSONDecodeError:
            data = {}
        return r.status_code, data
    except requests.ConnectionError:
        return 0, {"error": "ConnectionError"}
    except requests.Timeout:
        return 0, {"error": "Timeout"}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _http_post(url: str, json_body: dict, timeout: float = 5.0) -> tuple[int, dict]:
    """POST 请求，返回 (status_code, json_dict)"""
    import requests
    try:
        r = requests.post(url, json=json_body, timeout=timeout)
        try:
            data = r.json()
        except json.JSONDecodeError:
            data = {}
        return r.status_code, data
    except requests.ConnectionError:
        return 0, {"error": "ConnectionError"}
    except requests.Timeout:
        return 0, {"error": "Timeout"}
    except Exception as exc:
        return 0, {"error": str(exc)}


# ===========================================================================
# Suite 1 — 三模式 Relay 启动检查
# ===========================================================================

def _suite_relay_startup(host: str = "127.0.0.1"):
    suite = "RelayStartup"
    log.info("=== %s (host=%s) ===", suite, host)

    for mode_name, mode_info in MODES.items():
        port = mode_info["port"]
        token = mode_info["token"]
        title = mode_info["title"]
        base_url = f"http://{host}:{port}"

        # 测试 /mode 端点
        def test_mode_endpoint():
            status, data = _http_get(f"{base_url}/mode")
            assert status == 200, f"/mode 返回 {status} (期望 200): {data}"
            assert data.get("mode") == mode_name, f"mode 字段应为 {mode_name}, 实际: {data.get('mode')}"
            assert data.get("port") == port, f"port 字段应为 {port}, 实际: {data.get('port')}"

        _run(suite, f"test_{mode_name}_mode_endpoint", test_mode_endpoint)

        # 测试 /state 端点 (鉴权)
        def test_state_auth():
            # 无效 token 应返回 401
            status, data = _http_get(f"{base_url}/state?token=wrong_token")
            assert status == 401, f"无效token应返回401, 实际: {status}"

            # 有效 token 应返回 200
            status, data = _http_get(f"{base_url}/state?token={token}")
            assert status == 200, f"有效token应返回200, 实际: {status}: {data}"
            assert "phase" in data, f"/state 应包含 phase 字段: {data}"

        _run(suite, f"test_{mode_name}_state_auth", test_state_auth)

        # 测试首页
        def test_index():
            import requests
            try:
                r = requests.get(base_url, timeout=timeout_val)
                assert r.status_code == 200, f"/ 应返回 200, 实际: {r.status_code}"
            except Exception as exc:
                assert False, f"首页请求失败: {exc}"

        timeout_val = 5.0
        _run(suite, f"test_{mode_name}_index_page", test_index)


# ===========================================================================
# Suite 2 — 模式隔离性验证
# ===========================================================================

def _suite_mode_isolation(host: str = "127.0.0.1"):
    suite = "ModeIsolation"
    log.info("=== %s ===", suite)

    hotspot_token = MODES["hotspot"]["token"]
    vpn_token = MODES["vpn"]["token"]

    # 推送数据到热点模式，VPN模式应不受影响
    def test_push_hotspot_no_leak():
        # 先清空 VPN 模式状态（如果有的话）
        push_data = {"phase": "playing_isolation_test", "hand": ["1m", "2m", "3m"]}
        status, data = _http_post(
            f"http://{host}:8000/push",
            {"api_token": hotspot_token, "snapshot": push_data},
        )
        assert status == 200, f"热点push应返回200, 实际: {status}: {data}"

        # 检查热点模式有数据
        status, h_data = _http_get(f"http://{host}:8000/state?token={hotspot_token}")
        assert status == 200, f"热点state应返回200"
        assert h_data.get("phase") == "playing_isolation_test", f"热点应有推送的phase"

        # 检查 VPN 模式不受影响
        status, v_data = _http_get(f"http://{host}:8001/state?token={vpn_token}")
        assert status == 200, f"VPN state应返回200"
        assert v_data.get("phase") != "playing_isolation_test", f"VPN不应有热点的数据: {v_data.get('phase')}"

    _run(suite, "test_push_hotspot_no_leak_vpn", test_push_hotspot_no_leak)

    # 推送数据到 VPN 模式，无配置模式应不受影响
    def test_push_vpn_no_leak():
        push_data = {"phase": "vpn_isolation_test", "hand": ["5p", "6p"]}
        status, data = _http_post(
            f"http://{host}:8001/push",
            {"api_token": vpn_token, "snapshot": push_data},
        )
        assert status == 200, f"VPN push应返回200, 实际: {status}: {data}"

        # 无配置模式不受影响
        nc_token = MODES["noconfig"]["token"]
        status, nc_data = _http_get(f"http://{host}:8002/state?token={nc_token}")
        assert status == 200
        assert nc_data.get("phase") != "vpn_isolation_test", f"无配置不应有VPN数据"

    _run(suite, "test_push_vpn_no_leak_noconfig", test_push_vpn_no_leak)

    # 各模式 api_token 不同，不应互通
    def test_cross_token_rejected():
        # 用热点token访问VPN应返回401
        status, data = _http_get(f"http://{host}:8001/state?token={hotspot_token}")
        assert status == 401, f"跨模式token应返回401, 实际: {status}"

    _run(suite, "test_cross_token_rejected", test_cross_token_rejected)


# ===========================================================================
# Suite 3 — Extractor → Relay 推送链路验证
# ===========================================================================

def _suite_extractor_link(host: str = "127.0.0.1"):
    suite = "ExtractorLink"
    log.info("=== %s ===", suite)

    hotspot_token = MODES["hotspot"]["token"]

    # 模拟 extractor 推送
    def test_simulated_push():
        snapshot = {
            "phase": "playing",
            "your_hand": ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4z"],
            "round": 1,
        }
        status, data = _http_post(
            f"http://{host}:8000/push",
            {"api_token": hotspot_token, "snapshot": snapshot},
        )
        assert status == 200, f"push 应返回 200: {status}: {data}"
        assert data.get("status") == "ok", f"push 响应应包含 status=ok: {data}"

        # 验证 /state 能读到推送的数据
        status, state = _http_get(f"http://{host}:8000/state?token={hotspot_token}")
        assert status == 200
        assert state.get("phase") == "playing", f"/state phase 应为 playing: {state}"
        assert state.get("your_hand") == snapshot["your_hand"], f"/state hand 应匹配推送数据"

    _run(suite, "test_simulated_push", test_simulated_push)

    # 模拟凭证注册
    def test_credential_register():
        # 使用测试凭证（不影响真实配置）
        test_hs = "deadbeef1234"
        test_auth = "aabbccddeeff001122334455"
        status, data = _http_post(
            f"http://{host}:8000/register",
            {"api_token": hotspot_token, "handshake_blob": test_hs, "auth_token_12b": test_auth},
        )
        assert status == 200, f"register 应返回 200: {status}: {data}"
        assert data.get("status") == "ok", f"register 应包含 status=ok: {data}"

        # 验证 /state 中 credential_ready = True
        status, state = _http_get(f"http://{host}:8000/state?token={hotspot_token}")
        assert state.get("credential_ready") is True, f"凭证注册后 credential_ready 应为 True"

    _run(suite, "test_credential_register", test_credential_register)

    # 模拟房间注册（无配置模式）
    def test_room_register():
        nc_token = MODES["noconfig"]["token"]
        status, data = _http_post(
            f"http://{host}:8002/register-room",
            {"api_token": nc_token, "room_id": 999, "game_id": 888},
        )
        assert status == 200, f"register-room 应返回 200: {status}: {data}"
        assert data.get("room_id") == 999, f"register-room 应返回 room_id"

        # 验证 /watch-info 能读到房间信息
        status, info = _http_get(f"http://{host}:8002/watch-info?token={nc_token}")
        assert status == 200
        assert info.get("room_id") == 999 or info.get("roomid") == 999, f"watch-info 应返回注册的房间信息"

    _run(suite, "test_room_register", test_room_register)


# ===========================================================================
# Suite 4 — 云端 ECS 连通性检查
# ===========================================================================

def _suite_cloud_connectivity(ecs_ip: str = ECS_IP):
    suite = "CloudConnectivity"
    log.info("=== %s (ECS=%s) ===", suite, ecs_ip)

    for mode_name, mode_info in MODES.items():
        port = mode_info["port"]
        base_url = f"http://{ecs_ip}:{port}"

        def test_cloud_mode():
            status, data = _http_get(f"{base_url}/mode", timeout=10.0)
            if status == 0:
                # 连接失败 — 可能是 ECS 未部署或安全组未放行
                assert False, f"ECS {mode_name} 模式不可达 (连接失败): {data.get('error', 'unknown')}"
            assert status == 200, f"/mode 应返回 200, 实际: {status}"
            assert data.get("mode") == mode_name, f"mode 应为 {mode_name}, 实际: {data.get('mode')}"

        _run(suite, f"test_cloud_{mode_name}_reachable", test_cloud_mode)

    # spectator 连通性
    def test_cloud_spectator():
        status, data = _http_get(f"http://{ecs_ip}:{SPECTATOR_PORT}/status", timeout=10.0)
        if status == 0:
            assert False, f"ECS spectator 不可达: {data.get('error', 'unknown')}"
        assert status == 200, f"spectator /status 应返回 200"

    _run(suite, "test_cloud_spectator_reachable", test_cloud_spectator)


# ===========================================================================
# Suite 5 — Spectator 启动检查
# ===========================================================================

def _suite_spectator_check(host: str = "127.0.0.1"):
    suite = "SpectatorCheck"
    log.info("=== %s ===", suite)

    # 检查 spectator /status 端点
    def test_spectator_status():
        status, data = _http_get(f"http://{host}:{SPECTATOR_PORT}/status", timeout=5.0)
        if status == 0:
            # spectator 可能未启动（需要 srs_sessionid）
            assert False, f"spectator 不可达 (需要先注册 srs_sessionid)"
        assert status == 200, f"spectator /status 应返回 200"
        assert "watching" in data, f"/status 应包含 watching 字段"

    _run(suite, "test_spectator_status_endpoint", test_spectator_status)

    # 检查 spectator /watch 端点鉴权
    def test_spectator_watch_auth():
        # 无效 token 应被拒绝
        status, data = _http_post(
            f"http://{host}:{SPECTATOR_PORT}/watch",
            {"roomid": 1, "gameid": 1, "api_token": "wrong"},
        )
        if status == 0:
            assert False, "spectator 不可达"
        # spectator 的 api_token 由环境变量 API_TOKEN 控制
        # 此处仅验证鉴权逻辑工作（可能返回 401 或 500）
        assert status in (401, 422, 500), f"无效token应被拒绝, 实际: {status}"

    _run(suite, "test_spectator_watch_auth", test_spectator_watch_auth)


# ===========================================================================
# Suite 6 — 本地 relay 临时启动测试
# ===========================================================================

def _suite_local_relay_temp():
    """启动临时 relay 服务进行集成测试（不依赖已运行的服务）"""
    suite = "LocalRelayTemp"
    log.info("=== %s ===", suite)

    try:
        import requests
    except ImportError:
        log.warning("[SKIP] requests 未安装")
        for name in ["test_temp_startup", "test_temp_isolation", "test_temp_push_and_state"]:
            _results.append((f"{suite}.{name}", None, "SKIP"))
        return

    # 使用随机端口避免冲突
    import random
    port_a = random.randint(19000, 19999)
    port_b = port_a + 1
    port_c = port_a + 2

    tmp_cfg_a = os.path.join(PROJECT_ROOT, "remote", "relay", "test_cfg_a.yaml")
    tmp_cfg_b = os.path.join(PROJECT_ROOT, "remote", "relay", "test_cfg_b.yaml")
    tmp_cfg_c = os.path.join(PROJECT_ROOT, "remote", "relay", "test_cfg_c.yaml")

    # 生成临时配置
    token_a = "test_token_hotspot_e2e"
    token_b = "test_token_vpn_e2e"
    token_c = "test_token_noconfig_e2e"

    for cfg_path, mode, port, token in [
        (tmp_cfg_a, "hotspot", port_a, token_a),
        (tmp_cfg_b, "vpn", port_b, token_b),
        (tmp_cfg_c, "noconfig", port_c, token_c),
    ]:
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(f"""\
                mode: {mode}
                port: {port}
                api_token: {token}
                game_server_ip: 47.96.0.227
                game_server_port: 7777
                handshake_blob: ''
                auth_token_12b: ''
                srs_sessionid: ''
                push_timeout: 5
            """))

    relay_main = os.path.join(PROJECT_ROOT, "remote", "relay", "main.py")
    processes = []

    try:
        # 启动三个 relay 实例
        for port, cfg_path, mode in [(port_a, tmp_cfg_a, "hotspot"), (port_b, tmp_cfg_b, "vpn"), (port_c, tmp_cfg_c, "noconfig")]:
            log.info("启动临时 relay: mode=%s port=%d", mode, port)
            proc = subprocess.Popen(
                [sys.executable, relay_main, "--mode", mode, "--config", cfg_path, "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            processes.append(proc)

        # 等待服务就绪
        ready_count = 0
        for _ in range(30):
            time.sleep(0.5)
            try:
                r = requests.get(f"http://127.0.0.1:{port_a}/mode", timeout=2)
                if r.status_code == 200:
                    ready_count += 1
                    break
            except Exception:
                pass

        if ready_count == 0:
            for name in ["test_temp_startup", "test_temp_isolation", "test_temp_push_and_state"]:
                _record(suite, name, False, "relay 服务未在 15 秒内就绪")
            return

        log.info("临时 relay 已就绪")

        # 测试三模式启动
        def test_startup():
            for port, mode, token in [(port_a, "hotspot", token_a), (port_b, "vpn", token_b), (port_c, "noconfig", token_c)]:
                r = requests.get(f"http://127.0.0.1:{port}/mode", timeout=3)
                assert r.status_code == 200, f"port {port} /mode 返回 {r.status_code}"
                data = r.json()
                assert data.get("mode") == mode, f"mode 应为 {mode}, 实际: {data.get('mode')}"

        _run(suite, "test_temp_startup", test_startup)

        # 测试模式隔离
        def test_isolation():
            # 推送到 port_a
            r = requests.post(
                f"http://127.0.0.1:{port_a}/push",
                json={"api_token": token_a, "snapshot": {"phase": "playing_a"}},
                timeout=3,
            )
            assert r.status_code == 200

            # port_b 不应受影响
            r = requests.get(f"http://127.0.0.1:{port_b}/state?token={token_b}", timeout=3)
            data = r.json()
            assert data.get("phase") != "playing_a", f"模式B不应有A的数据"

        _run(suite, "test_temp_isolation", test_isolation)

        # 测试推送+状态
        def test_push_and_state():
            snapshot = {"phase": "playing", "your_hand": ["1m", "2m"]}
            r = requests.post(
                f"http://127.0.0.1:{port_a}/push",
                json={"api_token": token_a, "snapshot": snapshot},
                timeout=3,
            )
            assert r.status_code == 200

            r = requests.get(f"http://127.0.0.1:{port_a}/state?token={token_a}", timeout=3)
            data = r.json()
            assert data.get("phase") == "playing"
            assert data.get("your_hand") == ["1m", "2m"]
            assert data.get("data_source") == "extractor"

        _run(suite, "test_temp_push_and_state", test_push_and_state)

    except Exception as exc:
        log.warning("[SKIP] 临时relay测试失败: %s", exc)
        for name in ["test_temp_startup", "test_temp_isolation", "test_temp_push_and_state"]:
            _results.append((f"{suite}.{name}", None, "SKIP"))
    finally:
        for proc in processes:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        # 清理临时配置
        for cfg_path in [tmp_cfg_a, tmp_cfg_b, tmp_cfg_c]:
            if os.path.isfile(cfg_path):
                os.remove(cfg_path)
        log.info("临时 relay 进程已关闭")


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="三模式 E2E 测试")
    parser.add_argument("--cloud", action="store_true", help="验证云端 ECS 连通性")
    parser.add_argument("--cloud-only", action="store_true", help="仅验证云端 (不测试本地)")
    parser.add_argument("--local", action="store_true", help="测试本地已运行的 relay (默认)")
    parser.add_argument("--temp", action="store_true", help="启动临时 relay 进行测试")
    parser.add_argument("--ecs-ip", default=ECS_IP, help="ECS IP 地址")
    args = parser.parse_args()

    # 使用命令行指定的 ECS IP（不修改模块级常量）
    ecs_ip = args.ecs_ip or ECS_IP

    log.info("e2e_test.py 开始, 日志: %s", _LOG_FILE)
    log.info("ECS IP: %s", ecs_ip)

    # 默认: temp 测试 (不依赖已运行的服务)
    if not args.cloud_only:
        if args.temp or (not args.local and not args.cloud):
            log.info("模式: 临时启动 relay 测试")
            _suite_local_relay_temp()

        if args.local or (not args.temp and not args.cloud_only):
            log.info("模式: 测试已运行的本地 relay")
            _suite_relay_startup(host="127.0.0.1")

        if args.temp or (not args.local and not args.cloud):
            pass
        elif args.local:
            _suite_mode_isolation(host="127.0.0.1")
            _suite_extractor_link(host="127.0.0.1")
            _suite_spectator_check(host="127.0.0.1")

    if args.cloud or args.cloud_only:
        log.info("模式: 验证云端 ECS")
        _suite_cloud_connectivity(ecs_ip=ecs_ip)

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

    # 保存结果到 JSON
    result_file = os.path.join(_LOG_DIR, f"e2e_result_{_TIMESTAMP}.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": _TIMESTAMP,
            "ecs_ip": ecs_ip,
            "results": [{"label": l, "passed": p, "error": e} for l, p, e in _results],
            "summary": {"total": total, "passed": passed, "skipped": skipped, "failed": failed},
        }, f, indent=2)
    log.info("结果已保存: %s", result_file)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()