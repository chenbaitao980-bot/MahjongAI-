import logging
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from remote.noconfig.hijack import tcp_proxy


class _DeferredThread:
    scheduled = []

    def __init__(self, target, args=(), daemon=None):
        self._target = target
        self._args = args
        self._daemon = daemon

    def start(self):
        self.scheduled.append((self._target, self._args))


def test_lobby_connect_reports_default_fallback_and_gap_warning(monkeypatch, caplog):
    reports = []

    monkeypatch.setattr(tcp_proxy.time, "sleep", lambda _: None)
    monkeypatch.setattr(tcp_proxy.threading, "Thread", _DeferredThread)
    _DeferredThread.scheduled = []
    caplog.set_level(logging.WARNING, logger="remote.noconfig.hijack.tcp_proxy")

    player_reporter, lobby_reporter = tcp_proxy._make_presence_gap_reporters(reports.append)

    lobby_reporter(5748, ("1.2.3.4", 10000))

    assert reports == [{"user_id": "default", "name": "default", "client_ip": "1.2.3.4"}]
    assert len(_DeferredThread.scheduled) == 1

    target, args = _DeferredThread.scheduled.pop()
    target(*args)

    assert any("without real PlayerData" in rec.message for rec in caplog.records)
    player_reporter({"client_ip": "1.2.3.4", "user_id": "real-user"})


def test_real_playerdata_clears_pending_default_fallback(monkeypatch, caplog):
    reports = []

    monkeypatch.setattr(tcp_proxy.threading, "Thread", _DeferredThread)
    _DeferredThread.scheduled = []
    caplog.set_level(logging.INFO, logger="remote.noconfig.hijack.tcp_proxy")

    player_reporter, lobby_reporter = tcp_proxy._make_presence_gap_reporters(reports.append)

    lobby_reporter(5749, ("5.6.7.8", 10001))
    player_reporter({"client_ip": "5.6.7.8", "user_id": "real-user", "name": "nick"})

    assert reports == [
        {"user_id": "default", "name": "default", "client_ip": "5.6.7.8"},
        {"client_ip": "5.6.7.8", "user_id": "real-user", "name": "nick"},
    ]
    assert any("clearing default fallback" in rec.message for rec in caplog.records)

    target, args = _DeferredThread.scheduled.pop()
    target(*args)

    assert not any("without real PlayerData" in rec.message for rec in caplog.records)
