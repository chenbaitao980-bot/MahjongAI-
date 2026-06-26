"""Test scanner rejection, IP skip DNS, healthz endpoint, and origin fetch timeout.

Run: python -m pytest interface/tests/test_setup_mitm_hardening.py -v
"""
from __future__ import annotations

import json
import socket

import pytest
import requests
import urllib3

urllib3.disable_warnings()

from mahjong_mitm.setup_mitm import (
    _is_scanner_path,
    _resolve_real_ip,
    make_http_handler,
    PATH_VERSION,
)


class FakeAssets:
    """Minimal stub for make_http_handler tests."""

    served_name = "aa/netconf.luac"
    served_md5 = "deadbeef"
    netconf_luac = b"netconf-data"
    resensure_name = None
    reschecker_name = None
    file_url_mode = "official"
    real_manifest_paths = set()
    real_manifest_host = None
    real_manifest_path = None


class TestResolveRealIp:
    """R1: IP 地址跳过 DNS 查询。"""

    def test_ipv4_returns_itself(self, monkeypatch):
        # 清空缓存
        from mahjong_mitm import setup_mitm as mod
        monkeypatch.setattr(mod, "_resolve_cache", {})
        assert _resolve_real_ip("8.136.37.136") == "8.136.37.136"

    def test_ipv6_returns_itself(self, monkeypatch):
        from mahjong_mitm import setup_mitm as mod
        monkeypatch.setattr(mod, "_resolve_cache", {})
        assert _resolve_real_ip("::1") == "::1"

    def test_hostname_goes_to_dns(self, monkeypatch):
        from mahjong_mitm import setup_mitm as mod
        monkeypatch.setattr(mod, "_resolve_cache", {})
        # 完全 mock socket 操作，避免真实 UDP 超时
        called = []

        def fake_socket(*args, **kwargs):
            class FakeSock:
                def settimeout(self, t): pass
                def sendto(self, data, addr): called.append(("sendto", addr))
                def recvfrom(self, size): return b"fake-resp", ("1.1.1.1", 53)
                def close(self): pass
            return FakeSock()

        monkeypatch.setattr(socket, "socket", fake_socket)

        def fake_parse(resp):
            return "1.2.3.4"

        monkeypatch.setattr(mod, "_parse_first_a", fake_parse)

        # 用一个不是 IP 的字符串
        result = _resolve_real_ip("example.com")
        assert any(c[0] == "sendto" for c in called)
        assert result == "1.2.3.4"


class TestScannerPathBlacklist:
    """R2: 扫描器路径快速拒绝。"""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/.git/config", True),
            ("/favicon.ico", True),
            ("/sitemap.xml", True),
            ("/", True),
            ("/.env", True),
            ("/nmap", True),
            ("/nmap/something", True),
            ("/evox/about", True),
            ("/cgi-bin/test", True),
            ("/wp-admin", True),
            ("/hotfix_update", False),
            ("/yj/Lobby/project.manifest", False),
            ("/yj/files/aa/test.luac", False),
        ],
    )
    def test_scanner_paths(self, path, expected):
        assert _is_scanner_path(path) is expected


class TestHandlerHardening:
    """R2/R4/R5: Handler 级别的扫描器拒绝 + healthz + CLOSE-WAIT 防护。"""

    @pytest.fixture(scope="class")
    def server(self):
        from http.server import ThreadingHTTPServer
        import threading

        assets = FakeAssets()
        handler = make_http_handler(assets, enable_origin=False)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()

    def test_healthz_returns_ok(self, server):
        r = requests.get(f"{server}/healthz", timeout=2)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_scanner_path_returns_404(self, server):
        for path in ["/.git/config", "/favicon.ico", "/nmap", "/.env"]:
            r = requests.get(f"{server}{path}", timeout=2)
            assert r.status_code == 404, f"{path} should return 404, got {r.status_code}"

    def test_normal_path_still_works(self, server):
        # NetConf file request should return 200 with the stub data
        r = requests.get(f"{server}/yj/files/aa/netconf.luac", timeout=2)
        assert r.status_code == 200
        assert r.content == b"netconf-data"

    def test_many_scanner_requests_dont_kill_server(self, server):
        # Simulate scanner flood: 100 rapid 404s followed by a valid request
        for _ in range(100):
            requests.get(f"{server}/.git/config", timeout=2)
        r = requests.get(f"{server}/healthz", timeout=2)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
