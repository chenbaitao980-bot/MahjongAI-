"""test_win_task.py — 计划任务开机自启的纯逻辑自测（mock schtasks，无副作用）。

真正建/删计划任务有副作用只能真机验；这里 mock subprocess，断言：
  - 源码态（非 frozen）enable 跳过且不调 schtasks
  - frozen 态 enable 拼出 ONLOGON + HIGHEST + 带引号 exe 的正确命令行
  - disable 对"任务不存在"幂等返回成功
  - is_autostart_enabled 用 returncode 判存在
  - config 首跑标记往返

运行:
  cd apps/router_runtime
  python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from windows import config, win_task


def _cp(returncode: int, stderr: str = "", stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["schtasks"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_enable_skips_in_source_mode(monkeypatch):
    monkeypatch.setattr(win_task, "_frozen", lambda: False)
    called = []
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: called.append(args) or _cp(0))
    assert win_task.enable_autostart() is False
    assert called == []  # 源码态不应调 schtasks


def test_enable_builds_onlogon_highest_command(monkeypatch):
    monkeypatch.setattr(win_task, "_frozen", lambda: True)
    monkeypatch.setattr(win_task, "_exe_path", lambda: r"C:\Program Files\MahjongMITM\MahjongMITM.exe")
    seen = {}

    def fake(args):
        seen["args"] = args
        return _cp(0)

    monkeypatch.setattr(win_task, "_run_schtasks", fake)
    assert win_task.enable_autostart() is True
    args = seen["args"]
    assert args[0] == "/Create"
    assert "ONLOGON" in args
    assert "HIGHEST" in args
    assert "/F" in args
    # /TR 值须为带引号的 exe 路径，容纳空格
    tr_idx = args.index("/TR")
    assert args[tr_idx + 1] == r'"C:\Program Files\MahjongMITM\MahjongMITM.exe"'
    # /TN 值为固定任务名
    tn_idx = args.index("/TN")
    assert args[tn_idx + 1] == "MahjongMITM"


def test_enable_returns_false_on_schtasks_error(monkeypatch):
    monkeypatch.setattr(win_task, "_frozen", lambda: True)
    monkeypatch.setattr(win_task, "_exe_path", lambda: r"C:\x\app.exe")
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: _cp(1, stderr="ERROR: Access denied."))
    assert win_task.enable_autostart() is False


def test_disable_success(monkeypatch):
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: _cp(0))
    assert win_task.disable_autostart() is True


def test_disable_idempotent_when_task_missing(monkeypatch):
    monkeypatch.setattr(win_task, "_run_schtasks",
                        lambda args: _cp(1, stderr="ERROR: The system cannot find the task specified."))
    assert win_task.disable_autostart() is True


def test_disable_returns_false_on_real_error(monkeypatch):
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: _cp(1, stderr="ERROR: Access is denied."))
    assert win_task.disable_autostart() is False


def test_is_enabled_uses_returncode(monkeypatch):
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: _cp(0))
    assert win_task.is_autostart_enabled() is True
    monkeypatch.setattr(win_task, "_run_schtasks", lambda args: _cp(1, stderr="cannot find"))
    assert win_task.is_autostart_enabled() is False


def test_autostart_marker_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_app_dir", lambda: str(tmp_path))
    assert config.autostart_was_initialized() is False
    config.mark_autostart_initialized()
    assert config.autostart_was_initialized() is True
